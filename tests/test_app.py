import importlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from io import BytesIO

from PIL import Image
from fastapi.testclient import TestClient


class MemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ['MEMO_DATA_DIR'] = cls.temp.name
        import app
        cls.module = app
        cls.client = TestClient(app.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.temp.cleanup()
        os.environ.pop('MEMO_DATA_DIR', None)

    def setUp(self):
        with self.module.database() as db:
            db.execute('DELETE FROM pages')
        for file in self.module.UPLOADS.iterdir():
            file.unlink()

    def post(self, path, **kwargs):
        return self.client.post(path + '?token=' + self.module.TOKEN, **kwargs)

    def create_page(self):
        image = BytesIO()
        Image.new('RGB', (80, 120), '#eddbb8').save(image, format='PNG')
        response = self.post('/pages', data={'title': '中文笔记 English'}, files={'photo': ('note.png', image.getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 200)
        with self.module.database() as db:
            return db.execute('SELECT id FROM pages').fetchone()['id']

    def test_full_workflow_and_cascade(self):
        page = self.create_page()
        response = self.client.get(f'/pages/{page}/photo')
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(self.post(f'/pages/{page}/items', data={'title': '阅读第六章'}).status_code, 200)
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items').fetchone()['id']
        response = self.post(f'/items/{item}/edit', data={'title': '阅读并做笔记', 'status': 'doing'})
        self.assertIn('阅读并做笔记', response.text)
        self.assertEqual(self.post(f'/items/{item}/updates', data={'body': '完成六章\n明天继续'}).status_code, 200)
        self.post(f'/items/{item}/edit', data={'title': '阅读并做笔记', 'status': 'done'})
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM updates').fetchone()[0], 3)
        self.assertEqual(self.post(f'/pages/{page}/delete').status_code, 200)
        self.assertEqual(self.post(f'/trash/pages/{page}/purge').status_code, 200)
        with self.module.database() as db:
            for table in ['pages', 'items', 'updates']:
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(list(self.module.UPLOADS.iterdir()), [])

    def test_optional_photo_workflow(self):
        for kwargs in ({}, {'files': {'photo': ('', b'', 'application/octet-stream')}}):
            response = self.post('/pages', data={'title': '纯文字 memo'}, **kwargs)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('class="photo-section"', response.text)
            self.assertIn('行动与进展', response.text)
            with self.module.database() as db:
                page = db.execute('SELECT * FROM pages ORDER BY id DESC').fetchone()
            self.assertEqual(page['image'], '')
            self.assertEqual(self.client.get(f'/pages/{page["id"]}/photo').status_code, 404)
            self.post(f'/pages/{page["id"]}/items', data={'title': '新想法'})
            with self.module.database() as db:
                item = db.execute('SELECT id FROM items WHERE page_id=?', (page['id'],)).fetchone()[0]
            response = self.post(f'/items/{item}/updates', data={'body': '开始行动'})
            self.assertIn('开始行动', response.text)
            self.assertEqual(self.post(f'/pages/{page["id"]}/delete').status_code, 200)
        self.assertTrue(self.module.UPLOADS.is_dir())

    def test_invalid_inputs_and_missing_records(self):
        bad = self.post('/pages', data={'title': 'test'}, files={'photo': ('fake.jpg', b'not an image', 'image/jpeg')})
        self.assertEqual(bad.status_code, 400)
        page = self.create_page()
        self.assertEqual(self.post(f'/pages/{page}/items', data={'title': '   '}).status_code, 400)
        self.assertEqual(self.post(f'/pages/{page}/items', data={'title': 'a' * 201}).status_code, 400)
        self.assertEqual(self.client.get('/?page=999999').status_code, 404)
        self.assertEqual(self.post('/items/999999/updates', data={'body': 'test'}).status_code, 404)
        self.post(f'/pages/{page}/items', data={'title': 'test'})
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items').fetchone()[0]
        self.assertEqual(self.post(f'/items/{item}/edit', data={'title': 'test', 'status': 'bad'}).status_code, 400)

    def test_request_protection_and_html_escaping(self):
        self.assertEqual(self.client.post('/pages/1/delete').status_code, 403)
        self.assertEqual(self.post('/pages/1/delete', headers={'sec-fetch-site': 'cross-site'}).status_code, 403)
        page = self.create_page()
        response = self.post(f'/pages/{page}/items', data={'title': '<script>alert(1)</script>'})
        self.assertIn('&lt;script&gt;', response.text)
        self.assertNotIn('<script>alert(1)</script>', response.text)

    def test_oversized_photo_rejected_without_record(self):
        response = self.post('/pages', data={'title': 'too large'}, files={'photo': ('large.jpg', b'x' * (20 * 1024 * 1024 + 1), 'image/jpeg')})
        self.assertEqual(response.status_code, 400)
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pages').fetchone()[0], 0)
        self.assertEqual(list(self.module.UPLOADS.iterdir()), [])

    def test_restart_and_backup_restore(self):
        page = self.create_page()
        self.post(f'/pages/{page}/items', data={'title': '备份测试'})
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items').fetchone()[0]
        self.post(f'/items/{item}/updates', data={'body': '需要保留的进度'})
        original = Path(self.temp.name)
        with tempfile.TemporaryDirectory() as backup_root:
            backup = Path(backup_root) / 'data'
            shutil.copytree(original, backup)
            os.environ['MEMO_DATA_DIR'] = str(backup)
            try:
                importlib.reload(self.module)
                with TestClient(self.module.app) as restored:
                    response = restored.get('/')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('备份测试', response.text)
                    self.assertIn('需要保留的进度', response.text)
                    self.assertEqual(restored.get(f'/pages/{page}/photo').status_code, 200)
            finally:
                os.environ['MEMO_DATA_DIR'] = str(original)
                importlib.reload(self.module)
                self.client.close()
                self.__class__.client = TestClient(self.module.app)

    def test_item_deletion_preserves_page(self):
        page = self.create_page()
        self.post(f'/pages/{page}/items', data={'title': 'delete me'})
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items').fetchone()[0]
        self.post(f'/items/{item}/updates', data={'body': 'history'})
        self.assertEqual(self.post(f'/items/{item}/delete').status_code, 200)
        self.assertEqual(self.post(f'/trash/items/{item}/purge').status_code, 200)
        self.assertEqual(self.client.get(f'/pages/{page}/photo').status_code, 200)
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM updates').fetchone()[0], 0)

    def test_sidebar_orders_by_latest_change(self):
        first = self.create_page()
        self.post('/pages', data={'title': 'newer page'})
        with self.module.database() as db:
            second = db.execute('SELECT max(id) FROM pages').fetchone()[0]

        def assert_first(page_id):
            html = self.client.get('/').text
            nav = html.split('<nav aria-label="笔记页">')[1].split('</nav>')[0]
            self.assertIn(f'href="/?page={page_id}"', nav.split('</a>')[0])

        def make_old():
            with self.module.database() as db:
                db.execute("UPDATE pages SET updated_at='2000-01-01 00:00' WHERE id=?", (first,))
            assert_first(second)

        assert_first(second)
        self.post(f'/pages/{first}/items', data={'title': 'first item'})
        assert_first(first)
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items WHERE page_id=?', (first,)).fetchone()[0]
        for title, status in [('edited title', 'todo'), ('edited title', 'doing')]:
            make_old()
            self.post(f'/items/{item}/edit', data={'title': title, 'status': status})
            assert_first(first)
        make_old()
        self.post(f'/items/{item}/updates', data={'body': 'new progress'})
        assert_first(first)
        make_old()
        self.post(f'/items/{item}/delete')
        assert_first(first)

    def test_pinned_pages_stay_above_newer_pages(self):
        first = self.create_page()
        self.post('/pages', data={'title': 'newer'})
        with self.module.database() as db:
            second = db.execute('SELECT max(id) FROM pages').fetchone()[0]
            before = db.execute('SELECT updated_at FROM pages WHERE id=?', (first,)).fetchone()[0]

        def assert_first(page_id):
            nav = self.client.get('/').text.split('<nav aria-label="笔记页">')[1].split('</nav>')[0]
            self.assertIn(f'href="/?page={page_id}"', nav.split('</a>')[0])

        self.assertEqual(self.post(f'/pages/{first}/pin', data={'pinned': 1}).status_code, 200)
        self.post(f'/pages/{second}/items', data={'title': 'latest activity'})
        assert_first(first)
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT updated_at FROM pages WHERE id=?', (first,)).fetchone()[0], before)
        self.post(f'/pages/{second}/pin', data={'pinned': 1})
        assert_first(second)
        self.post(f'/pages/{first}/items', data={'title': 'newest pinned activity'})
        assert_first(first)
        self.post(f'/pages/{first}/pin', data={'pinned': 0})
        assert_first(second)
        self.post(f'/pages/{second}/pin', data={'pinned': 0})
        assert_first(first)
        self.assertEqual(self.post(f'/pages/{first}/pin', data={'pinned': 2}).status_code, 400)

    def test_pin_limit_is_five(self):
        for number in range(6):
            self.post('/pages', data={'title': f'memo {number}'})
        with self.module.database() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM pages ORDER BY id')]
        for page in ids[:5]:
            self.assertEqual(self.post(f'/pages/{page}/pin', data={'pinned': 1}).status_code, 200)
        self.assertEqual(self.post(f'/pages/{ids[5]}/pin', data={'pinned': 1}).status_code, 400)
        self.assertEqual(self.post(f'/pages/{ids[0]}/pin', data={'pinned': 1}).status_code, 200)
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pages WHERE pinned=1').fetchone()[0], 5)
        self.post(f'/pages/{ids[0]}/pin', data={'pinned': 0})
        self.assertEqual(self.post(f'/pages/{ids[5]}/pin', data={'pinned': 1}).status_code, 200)

    def test_favorite_is_saved_independently_of_pin_and_activity(self):
        page = self.create_page()
        with self.module.database() as db:
            before = dict(db.execute('SELECT * FROM pages WHERE id=?', (page,)).fetchone())
        response = self.post(f'/pages/{page}/favorite', data={'favorite': 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-favorite="1"', response.text)
        self.assertIn('★ 已收藏', response.text)
        with self.module.database() as db:
            after = dict(db.execute('SELECT * FROM pages WHERE id=?', (page,)).fetchone())
        self.assertEqual(after, {**before, 'favorite': 1})
        self.assertIn('data-favorite="1"', self.client.get('/').text)
        response = self.post(f'/pages/{page}/favorite', data={'favorite': 0})
        self.assertIn('data-favorite="0"', response.text)
        self.assertEqual(self.post(f'/pages/{page}/favorite', data={'favorite': 2}).status_code, 400)
        self.assertEqual(self.post('/pages/99999/favorite', data={'favorite': 1}).status_code, 404)

    def test_search_titles_items_history_and_tags(self):
        first = self.create_page()
        self.post(f'/pages/{first}/edit', data={'title': 'Travel plans', 'tags': '家庭，学习,学习'})
        self.post(f'/pages/{first}/items', data={'title': '买机票'})
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items WHERE page_id=?', (first,)).fetchone()[0]
        self.post(f'/items/{item}/updates', data={'body': '已经联系航空公司'})
        self.post('/pages', data={'title': 'unrelated'})
        for word in ('travel', '机票', '航空', '家庭'):
            response = self.client.get('/', params={'q': word})
            self.assertEqual(response.status_code, 200)
            nav = response.text.split('<nav aria-label="笔记页">')[1].split('</nav>')[0]
            self.assertIn('Travel plans', nav)
            self.assertNotIn('unrelated', nav)
        response = self.client.get('/', params={'tag': '学习', 'q': '航空'})
        self.assertIn('<h1>Travel plans</h1>', response.text)
        self.assertIn('没有找到匹配的笔记', self.client.get('/', params={'q': '%_'}).text)
        self.post(f'/items/{item}/delete')
        self.assertIn('没有找到匹配的笔记', self.client.get('/', params={'q': '航空'}).text)
        self.post(f'/pages/{first}/delete')
        self.assertIn('没有找到匹配的笔记', self.client.get('/', params={'tag': '学习'}).text)

    def test_rename_and_tag_validation_preserve_content(self):
        page = self.create_page()
        self.post(f'/pages/{page}/items', data={'title': 'keep this'})
        self.post(f'/pages/{page}/edit', data={'title': '新标题', 'tags': '学习,学习,Work,work'})
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT title FROM pages WHERE id=?', (page,)).fetchone()[0], '新标题')
            self.assertEqual(db.execute('SELECT count(*) FROM page_tags WHERE page_id=?', (page,)).fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM items').fetchone()[0], 1)
        for data in ({'title': ' ', 'tags': ''}, {'title': 'changed', 'tags': 'x'*31}, {'title': 'changed', 'tags': ','.join(map(str, range(11)))}):
            self.assertEqual(self.post(f'/pages/{page}/edit', data=data).status_code, 400)
        self.assertIn('<h1>新标题</h1>', self.client.get('/').text)
        self.post(f'/pages/{page}/edit', data={'title': '新标题', 'tags': ''})
        with self.module.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM page_tags').fetchone()[0], 0)

    def test_trash_restore_preserves_photo_tags_history_and_favorite(self):
        page = self.create_page()
        self.post(f'/pages/{page}/edit', data={'title': 'recover me', 'tags': '记录'})
        self.post(f'/pages/{page}/favorite', data={'favorite': 1})
        self.post(f'/pages/{page}/pin', data={'pinned': 1})
        self.post(f'/pages/{page}/items', data={'title': 'keep item'})
        with self.module.database() as db:
            item = db.execute('SELECT id FROM items WHERE page_id=?', (page,)).fetchone()[0]
        self.post(f'/items/{item}/updates', data={'body': 'keep history'})
        self.assertEqual(self.post(f'/trash/pages/{page}/purge').status_code, 400)
        self.post(f'/pages/{page}/delete')
        self.assertNotIn('recover me', self.client.get('/').text)
        self.assertIn('recover me', self.client.get('/trash').text)
        self.assertEqual(self.client.get(f'/?page={page}').status_code, 404)
        self.assertEqual(self.post(f'/items/{item}/updates', data={'body': 'blocked'}).status_code, 404)
        self.assertEqual(len(list(self.module.UPLOADS.iterdir())), 1)
        response = self.post(f'/trash/pages/{page}/restore')
        self.assertIn('keep history', response.text)
        self.assertEqual(self.client.get(f'/pages/{page}/photo').status_code, 200)
        with self.module.database() as db:
            row = db.execute('SELECT * FROM pages WHERE id=?', (page,)).fetchone()
            self.assertEqual((row['favorite'],row['pinned']), (1,0))
            self.assertEqual(db.execute('SELECT tag FROM page_tags WHERE page_id=?', (page,)).fetchone()[0], '记录')
        self.post(f'/items/{item}/delete')
        self.assertNotIn('keep history', self.client.get('/').text)
        self.assertIn('keep item', self.client.get('/trash').text)
        self.assertIn('keep history', self.post(f'/trash/items/{item}/restore').text)


if __name__ == '__main__':
    unittest.main()
