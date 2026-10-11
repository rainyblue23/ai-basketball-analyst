import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from aihoop import api
from aihoop.sample_gallery import entries, resolve


class PublishedExamplesTest(unittest.TestCase):
    def test_portable_catalog_and_local_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'examples/one').mkdir(parents=True)
            (root / 'data').mkdir()
            shipped = {'id': 'one', 'bundled': True, 'prepared_at': 'yes', 'video_path': 'examples/one/video.mp4'}
            (root / 'examples/catalog.json').write_text(json.dumps({'examples': [shipped]}))
            (root / 'examples/one/game.json').write_text('{}')
            local = dict(shipped, bundled=False, video_path='missing.mp4')
            catalog = root / 'data/example_gallery.json'
            catalog.write_text(json.dumps({'examples': [local]}))
            self.assertTrue(entries(root)[0]['bundled'])
            self.assertEqual(resolve(root, 'example_one')[1], root / 'examples/one')
            (root / 'missing.mp4').write_bytes(b'video')
            self.assertFalse(entries(root)[0]['bundled'])

    def test_published_snapshot_integrity_and_http(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / 'examples/manifest.json').read_text(encoding='utf-8'))
        # The manifest structure is verified independently of API output.
        rows = manifest['files']
        for row in rows:
            path = root / 'examples' / row['path']
            self.assertEqual(path.stat().st_size, row['bytes'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])
        with patch('aihoop.auth.internal_ok', return_value=True), TestClient(api.app) as client:
            for name, count in [('lillard', 15), ('harden', 34)]:
                job = 'example_' + name
                # Force the shipped snapshot even on a developer machine.
                shipped = json.loads((root / 'examples/catalog.json').read_text(encoding='utf-8'))['examples']
                for row in shipped:
                    row['video_path'] = str(root / row['video_path'])
                with patch('aihoop.sample_gallery.entries', return_value=shipped):
                    game = client.get('/api/games/' + job)
                    self.assertEqual(game.status_code, 200)
                    self.assertEqual(len(game.json()['timeline']), count)
                    self.assertEqual(client.get('/api/games/' + job + '/detections').status_code, 200)
                    self.assertEqual(client.get('/api/games/' + job + '/video', headers={'Range': 'bytes=0-99'}).status_code, 206)
                    self.assertEqual(client.get('/api/media/' + job + '/highlights/review_01.mp4', headers={'Range': 'bytes=0-99'}).status_code, 206)


if __name__ == '__main__':
    unittest.main()
