from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from memo.application import create_app
from memo.errors import MemoError


class LayerTests(unittest.TestCase):
    def test_app_instances_do_not_share_data_or_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            first = create_app(Path(directory) / 'first')
            second = create_app(Path(directory) / 'second')
            page_id = first.state.service.create_page('only in first')
            with TestClient(first) as a, TestClient(second) as b:
                self.assertIn('only in first', a.get('/').text)
                self.assertNotIn('only in first', b.get('/').text)
                self.assertEqual(b.get(f'/?page={page_id}').status_code, 404)
                self.assertNotEqual(first.state.token, second.state.token)

    def test_service_can_be_used_without_http_and_rejects_invalid_change(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            service = app.state.service
            page_id = service.create_page('study', tags='work')
            with self.assertRaises(MemoError):
                service.edit_page(page_id, '   ', 'changed')
            data = service.home(page_id)
            self.assertEqual(data['selected']['title'], 'study')
            self.assertEqual(data['page_tags'][page_id], ['work'])
            service.favorite_page(page_id, 1)
            service.delete_page(page_id)
            self.assertEqual(len(service.trash()['pages']), 1)
            service.restore_record('pages', page_id)
            self.assertEqual(service.home(page_id)['selected']['favorite'], 1)


if __name__ == '__main__':
    unittest.main()
