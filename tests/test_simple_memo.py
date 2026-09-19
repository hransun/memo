from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from memo.application import create_app


class SimpleMemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.service = self.app.state.service
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self, path, **kwargs):
        return self.client.post(path + '?token=' + self.app.state.token, **kwargs)

    def test_recent_is_five_unpinned_and_all_remains_accessible(self):
        ids = [self.service.create_page(f'memo {n}') for n in range(12)]
        for page in ids[:3]:
            self.service.pin_page(page, 1)
        context = self.service.home()
        self.assertEqual(len(context['pinned_pages']), 3)
        self.assertEqual(len(context['recent_pages']), 5)
        pinned = {p['id'] for p in context['pinned_pages']}
        recent = {p['id'] for p in context['recent_pages']}
        self.assertFalse(pinned & recent)
        self.assertEqual(recent, set(ids[-5:]))
        self.assertEqual(len(self.service.home(view='all')['pages']), 12)
        self.assertEqual(len(self.service.home(q='memo')['pages']), 12)
        for page in ids[:7]:
            self.service.favorite_page(page, 1)
        self.assertEqual(len(self.service.home(view='favorites')['pages']), 7)
        response = self.client.get('/?view=all')
        self.assertEqual(response.status_code, 200)
        self.assertIn('memo 0', response.text)
        # An older page can be opened even when it isn't in the recent list.
        self.assertEqual(self.client.get(f'/?page={ids[4]}').status_code, 200)

    def test_direct_entry_needs_no_task_and_updates_search_and_recency(self):
        page = self.service.create_page('日记')
        self.service.create_page('newer memo')
        response = self.post(f'/pages/{page}/entries', data={'body': '今天有一点进展\n明天继续'})
        self.assertEqual(response.status_code, 200)
        context = self.service.home()
        self.assertEqual(context['pages'][0]['id'], page)
        self.assertEqual(context['items'], [])
        self.assertEqual(context['timeline'][0]['body'], '今天有一点进展\n明天继续')
        self.assertEqual(len(self.service.home(q='明天继续')['pages']), 1)
        self.assertEqual(self.post(f'/pages/{page}/entries', data={'body': '  '}).status_code, 400)
        self.assertEqual(self.post(f'/pages/{page}/entries', data={'body': 'x' * 5001}).status_code, 400)
        self.assertEqual(len(self.service.home(page)['timeline']), 1)
        with TestClient(create_app(Path(self.temp.name))) as restarted:
            self.assertIn('明天继续', restarted.get(f'/?page={page}').text)

    def test_direct_entries_survive_trash_restore_and_purge_with_page(self):
        page = self.service.create_page('journal')
        self.service.add_page_entry(page, 'private entry')
        self.service.add_item(page, 'existing task')
        item = self.service.home(page)['items'][0]['id']
        self.service.add_update(item, 'existing history')
        self.assertEqual(len(self.service.home(page)['timeline']), 2)
        self.service.delete_page(page)
        self.assertEqual(len(self.service.home(q='private entry')['pages']), 0)
        self.assertEqual(self.post(f'/pages/{page}/entries', data={'body': 'blocked'}).status_code, 404)
        self.service.restore_record('pages', page)
        self.assertEqual(len(self.service.home(page)['timeline']), 2)
        self.service.delete_page(page)
        self.service.purge_record('pages', page)
        with self.app.state.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM page_entries').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')


if __name__ == '__main__':
    unittest.main()
