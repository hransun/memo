from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
from memo.application import create_app
from memo.errors import MemoError
from memo.attachments import COPY_CHUNK


def photo_bytes():
    stream = BytesIO()
    Image.new('RGB', (24, 18), 'blue').save(stream, 'PNG')
    return stream.getvalue()


# Transport fixtures with format signatures; browser decoding is checked separately.
MP3 = b'ID3\x04\x00\x00\x00\x00\x00\x00' + bytes(range(256)) * 20
MP4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2' + bytes(range(256)) * 20


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.service = self.app.state.service
        self.client = TestClient(self.app)
        self.page = self.service.create_page('attachments')

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def upload(self, filename, content, body='', page=None):
        return self.client.post(f'/pages/{page or self.page}/entries?token={self.app.state.token}',
                                data={'body': body}, files={'attachment': (filename, content)})

    def entry(self):
        return self.service.home(self.page)['timeline'][0]

    def test_photo_only_caption_restart_and_original_image(self):
        self.assertEqual(self.upload('picture.PNG', photo_bytes()).status_code, 200)
        entry = self.entry()
        self.assertEqual(entry['body'], '')
        self.assertEqual(entry['media_type'], 'image/jpeg')
        response = self.client.get(f"/entries/{entry['id']}/attachment")
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        with Image.open(BytesIO(response.content)) as image:
            self.assertEqual(image.size, (24, 18))
        self.assertEqual(self.upload('picture.png', photo_bytes(), 'with caption').status_code, 200)
        with TestClient(create_app(self.temp.name)) as restarted:
            html = restarted.get(f'/?page={self.page}').text
            self.assertIn('with caption', html)
            self.assertEqual(html.count('alt="记录图片"'), 2)

    def test_audio_video_range_seek_head_and_player_markup(self):
        for filename, content, mime, tag in [('song.mp3', MP3, 'audio/mpeg', 'audio'),
                                               ('clip.mp4', MP4, 'video/mp4', 'video')]:
            with self.subTest(filename=filename):
                result = self.upload(filename, content)
                self.assertEqual(result.status_code, 200)
                self.assertIn(f'<{tag} controls preload="none"', result.text)
                self.assertNotIn(' autoplay', result.text)
                self.assertIn("media-src 'self'", result.headers['content-security-policy'])
                url = f"/entries/{self.entry()['id']}/attachment"
                head = self.client.head(url)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b'')
                self.assertEqual(head.headers['content-length'], str(len(content)))
                for value, expected in [('bytes=0-15', content[:16]), ('bytes=100-299', content[100:300]),
                                        ('bytes=4000-', content[4000:]), ('bytes=-12', content[-12:])]:
                    partial = self.client.get(url, headers={'Range': value})
                    self.assertEqual(partial.status_code, 206)
                    self.assertEqual(partial.content, expected)
                    self.assertEqual(partial.headers['accept-ranges'], 'bytes')
                    self.assertEqual(partial.headers['content-type'], mime)
                    self.assertEqual(partial.headers['content-length'], str(len(expected)))
                    self.assertTrue(partial.headers['content-range'].endswith('/' + str(len(content))))
                invalid = self.client.get(url, headers={'Range': f'bytes={len(content)}-'})
                self.assertEqual(invalid.status_code, 416)
                self.assertEqual(invalid.headers['content-range'], f'bytes */{len(content)}')
                self.assertEqual(self.client.get(url).content, content)

    def test_bad_empty_oversize_and_missing_page_leave_no_files(self):
        for name, content in [('bad.mp4', b'<script>bad</script>'), ('bad.mp3', b'not music'),
                              ('bad.png', b'bad image'), ('empty.mp3', b''), ('bad.html', MP3)]:
            self.assertEqual(self.upload(name, content).status_code, 400)
        with patch('memo.attachments.MAX_MEDIA_BYTES', 100):
            self.assertEqual(self.upload('large.mp3', MP3).status_code, 400)
        with patch('memo.attachments.MAX_PHOTO_BYTES', 10):
            self.assertEqual(self.upload('large.png', photo_bytes()).status_code, 400)
        self.assertEqual(self.upload('song.mp3', MP3, body='x' * 5001).status_code, 400)
        self.assertEqual(self.upload('song.mp3', MP3, page=99999).status_code, 404)
        self.assertEqual(list(self.service.uploads.iterdir()), [])
        self.assertEqual(self.service.home(self.page)['timeline'], [])

    def test_trash_restore_and_purge_include_all_attachment_types(self):
        urls = []
        for name, content in [('photo.png', photo_bytes()), ('song.mp3', MP3), ('clip.mp4', MP4)]:
            self.assertEqual(self.upload(name, content).status_code, 200)
            urls.append(f"/entries/{self.entry()['id']}/attachment")
        self.service.delete_page(self.page)
        for url in urls:
            self.assertEqual(self.client.get(url, headers={'Range': 'bytes=0-3'}).status_code, 404)
        self.assertEqual(self.upload('blocked.mp3', MP3).status_code, 404)
        self.assertEqual(len(list(self.service.uploads.iterdir())), 3)
        self.service.restore_record('pages', self.page)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.service.delete_page(self.page)
        self.service.purge_record('pages', self.page)
        self.assertEqual(list(self.service.uploads.iterdir()), [])
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_bounded_copy_and_database_failure_cleanup(self):
        class BoundedReader(BytesIO):
            def read(self, size=-1):
                if not 0 <= size <= COPY_CHUNK:
                    raise AssertionError('unbounded read')
                return super().read(size)
        payload = MP3 + b'\x00' * (COPY_CHUNK * 2)
        self.service.add_page_entry(self.page, '', BoundedReader(payload), 'song.mp3')
        path, _ = self.service.entry_attachment(self.entry()['id'])
        self.assertEqual(path.stat().st_size, len(payload))
        with patch('memo.models.insert_page_entry', side_effect=sqlite3.OperationalError('test failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.service.add_page_entry(self.page, '', BytesIO(MP4), 'clip.mp4')
        self.assertEqual(len(list(self.service.uploads.iterdir())), 1)
        self.assertEqual(len(self.service.home(self.page)['timeline']), 1)
        path.unlink()
        self.assertEqual(self.client.get(f"/entries/{self.entry()['id']}/attachment").status_code, 404)

    def test_existing_entry_schema_migration_preserves_records(self):
        self.service.add_page_entry(self.page, 'old entry')
        with self.app.state.store.connection() as db:
            db.execute('ALTER TABLE page_entries DROP COLUMN attachment')
            db.execute('ALTER TABLE page_entries DROP COLUMN media_type')
        upgraded = create_app(self.temp.name)
        timeline = upgraded.state.service.home(self.page)['timeline']
        self.assertEqual(timeline[0]['body'], 'old entry')
        self.assertEqual(timeline[0]['attachment'], '')
        self.assertEqual(timeline[0]['media_type'], '')
        with upgraded.state.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')


    def test_edit_caption_preserves_attachment_and_allows_image_only(self):
        self.upload('photo.png', photo_bytes(), 'old caption')
        entry = self.entry()
        url = f"/entries/{entry['id']}/edit?token={self.app.state.token}"
        attachment_url = f"/entries/{entry['id']}/attachment"
        original = self.client.get(attachment_url).content
        for caption in ['new caption', '']:
            self.assertEqual(self.client.post(url, data={'body': caption}).status_code, 200)
            current = self.entry()
            self.assertEqual(current['body'], caption)
            self.assertEqual(current['created'], entry['created'])
            self.assertEqual(current['attachment'], entry['attachment'])
            self.assertEqual(self.client.get(attachment_url).content, original)
        self.assertEqual(len(list(self.service.uploads.iterdir())), 1)


if __name__ == '__main__':
    unittest.main()