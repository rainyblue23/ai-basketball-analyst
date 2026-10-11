import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('feedback',Path(__file__).parents[1]/'src/aihoop/ball_feedback.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class FeedbackTests(unittest.TestCase):
 def test_bad_inputs(self):
  for body in ({'t':float('nan'),'boxes':[]},{'t':True,'boxes':[]},{'t':0,'boxes':[]},{'t':0,'boxes':[{'kind':'ball','xyxy':[0,0,2,1]}]},{'t':0,'boxes':[{'kind':'ball','xyxy':[.5,0,.2,1]}]}):
   with self.assertRaises(ValueError):m.validate_feedback(body)
 def test_save_isolated_and_not_training_approved(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'read_frame',return_value=(b'PNG',{'frame_index':30,'frame_t':1.,'fps':30,'width':100,'height':100})):
   body={'t':1.,'boxes':[{'kind':'decoy','xyxy':[0,0,.1,.1]},{'kind':'ball','xyxy':[.2,.2,.3,.3]}]}
   a=m.save_feedback(d,'video.mp4',body,'job');b=m.save_feedback(d,'video.mp4',body,'job')
   self.assertNotEqual(a['id'],b['id'])
   record=json.loads((Path(d)/a['id']/'record.json').read_text(encoding='utf-8'))
   self.assertFalse(record['training_approved']);self.assertEqual(record['boxes'],body['boxes']);self.assertEqual(record['frame_index'],30)
 def test_bad_save_creates_nothing(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):m.save_feedback(d,'x',{'t':-1,'boxes':[]},'job')
   self.assertEqual(list(Path(d).iterdir()),[])
 def test_real_frame_roundtrip(self):
  import cv2,numpy as np
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.avi';writer=cv2.VideoWriter(str(p),cv2.VideoWriter_fourcc(*'MJPG'),10,(32,24))
   for i in range(10):writer.write(np.full((24,32,3),i*20,dtype=np.uint8))
   writer.release();png,meta=m.read_frame(p,.35)
   self.assertEqual(meta['frame_index'],3);self.assertAlmostEqual(meta['frame_t'],.3)
   im=cv2.imdecode(np.frombuffer(png,np.uint8),1);self.assertEqual(im.shape[:2],(24,32));self.assertAlmostEqual(float(im.mean()),60,delta=3)
   with self.assertRaises(ValueError):m.read_frame(p,1)
if __name__=='__main__':unittest.main()
