import unittest
from types import SimpleNamespace
import numpy as np
from aihoop.ball_recovery import measured_detections,recovery_region,recover_region
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.settings import resolve_detect,LegacyDetectOptions

def ball(x,y,conf=.8):return Det('basketball',conf,(x-8,y-8,x+8,y+8))

class RecoveryTests(unittest.TestCase):
 def test_motion_decoy_does_not_count_as_viable(self):
  s=LegacyShotStream(30,1920);s.update(0,0,[ball(100,100)])
  selected,a=s.preview_ball(1,[ball(1400,800,.99)])
  self.assertIsNone(selected);self.assertEqual(a[0]['selection_reason'],'motion_rejected')
  self.assertEqual(s.last_frame,0);self.assertEqual(len(s.frames),1)
 def test_cut_ignores_old_motion_without_mutation(self):
  s=LegacyShotStream(30,1920);s.update(0,0,[ball(100,100)])
  selected,_=s.preview_ball(1,[ball(1400,800)],cut=True)
  self.assertIsNotNone(selected);self.assertEqual(s.last_frame,0)
 def test_stale_track_cannot_generate_crop(self):
  s=LegacyShotStream(30,640);s.update(0,0,[ball(100,100)])
  self.assertIsNone(recovery_region(s,20,640,360))
 def test_region_clipped_to_image(self):
  s=LegacyShotStream(30,640);s.update(0,0,[ball(12,12)])
  x1,y1,x2,y2=recovery_region(s,1,640,360)
  self.assertEqual((x1,y1),(0,0));self.assertLessEqual(x2,640);self.assertLessEqual(y2,360)
 def test_mapping_uses_offset_and_drops_crop_rim(self):
  r=SimpleNamespace(names={0:'basketball',1:'rim'},boxes=[SimpleNamespace(cls=[0],conf=[.8],xyxy=[(10,20,30,40)]),SimpleNamespace(cls=[1],conf=[.9],xyxy=[(1,2,3,4)])])
  d=measured_detections(r,(100,200),balls_only=True)
  self.assertEqual(len(d),1);self.assertEqual(d[0].xyxy,(110,220,130,240));self.assertFalse(d[0].predicted)
 def test_roi_does_not_create_measurement_without_model_output(self):
  s=LegacyShotStream(30,640);s.update(0,0,[ball(100,100)])
  model=SimpleNamespace(predict=lambda *a,**k:[SimpleNamespace(names={},boxes=[])])
  d,a=recover_region(model,np.zeros((360,640,3),np.uint8),{},s,1)
  self.assertEqual(d,[]);self.assertTrue(a['ran']);self.assertEqual(s.real_seen,1)
 def test_roi_opt_in_default_and_explicit(self):
  self.assertFalse(resolve_detect()['ball_roi_recovery'])
  self.assertTrue(resolve_detect({'ball_roi_recovery':True})['ball_roi_recovery'])
  self.assertTrue(LegacyDetectOptions(ball_roi_recovery=True).ball_roi_recovery)

if __name__=='__main__':unittest.main()
