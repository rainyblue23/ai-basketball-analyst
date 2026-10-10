import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from aihoop import api
from aihoop.sample_gallery import catalog,resolve

class ExamplesTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'data').mkdir();d=self.root/'out/examples/one';d.mkdir(parents=True)
  self.d=d;self.video=self.root/'source.mp4';self.video.write_bytes(b'0123456789')
  self.item=dict(id='one',title='测试',description='集锦',duration=10,prepared_at='test',video_path=str(self.video))
  (d/'game.json').write_text(json.dumps({'timeline':[{'type':'shot','result':'made'},{'type':'shot','result':'unknown'}]}),encoding='utf-8')
  self.save()
  self.rootpatch=patch.object(api,'ROOT',self.root);self.rootpatch.start()
  self.authpatch=patch('aihoop.auth.internal_ok',return_value=True);self.authpatch.start()
  self.client=TestClient(api.app)
 def save(self): (self.root/'data/example_gallery.json').write_text(json.dumps({'examples':[self.item]}),encoding='utf-8')
 def tearDown(self): self.client.close();self.authpatch.stop();self.rootpatch.stop();self.tmp.cleanup()
 def test_catalog_counts_and_no_local_paths(self):
  row=self.client.get('/api/examples').json()['examples'][0]
  self.assertEqual((row['shots'],row['made'],row['unknown']),(2,1,1));self.assertNotIn('video_path',row)
 def test_gallery_preserves_login_requirement(self):
  with patch("aihoop.auth.internal_ok",return_value=False):
   self.assertEqual(self.client.get("/api/examples").status_code,401)
 def test_pending_not_published(self):
  self.item.pop('prepared_at');self.save();self.assertFalse(catalog(self.root)[0]['ready'])
  self.assertEqual(self.client.get('/api/games/example_one').status_code,409)
 def test_readonly_snapshots(self):
  before=(self.d/'game.json').read_bytes()
  for suffix in ['/shots/0/correct','/shots/add','/export/highlights','/report/llm']:
   self.assertEqual(self.client.post('/api/games/example_one'+suffix,json={'made':False}).status_code,403)
  self.assertEqual(before,(self.d/'game.json').read_bytes())
 def test_media_stays_in_example_directory(self):
  from fastapi import HTTPException
  import asyncio
  sibling=self.d.parent/"one_secret";sibling.mkdir();(sibling/"secret.txt").write_text("private")
  with self.assertRaises(HTTPException) as caught:
   asyncio.run(api.media("example_one","../one_secret/secret.txt"))
  self.assertEqual(caught.exception.status_code,403)
 def test_video_range(self):
  r=self.client.get('/api/games/example_one/video',headers={'Range':'bytes=2-5'})
  self.assertEqual(r.status_code,206);self.assertEqual(r.content,b'2345')
 def test_unknown_sample_and_traversal(self):
  self.assertEqual(self.client.get('/api/games/example_absent').status_code,404)
  self.item['id']='../escape';self.save()
  from fastapi import HTTPException
  with self.assertRaises(HTTPException):resolve(self.root,'example_../escape')

if __name__=='__main__':unittest.main()
