import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from aihoop import api
from aihoop.legacy_court import CourtModel,full_landmarks,preview_lines
from aihoop.court import calibrate_from_keypoints

class HoopaiCalibration(unittest.TestCase):
 def test_geometry_translation_and_preview(self):
  targets=full_landmarks()
  self.assertEqual(targets['lane_left_baseline'],(-2.45,-14.0))
  self.assertEqual(targets['hoop_ground'],(0.,-12.425))
  pixels={n:(200+x*20,300-y*20) for n,(x,y) in CourtModel().landmarks.items()}
  cal=calibrate_from_keypoints(pixels,targets)
  from aihoop.court import apply_homography
  for n,xy in pixels.items():
   actual=apply_homography(cal.H,*xy)
   self.assertAlmostEqual(actual[0],targets[n][0],places=5)
   self.assertAlmostEqual(actual[1],targets[n][1],places=5)
  self.assertTrue(preview_lines(cal,640,480))

 def test_preview_save_reload_delete_and_conflict(self):
  with tempfile.TemporaryDirectory() as td:
   video=Path(td)/'video.mp4';video.touch();output=Path(td)/'calibration.json'
   cap=MagicMock();cap.get.side_effect=lambda key:640 if key==3 else 480
   landmarks={n:[(200+x*20)/640,(300-y*20)/480] for n,(x,y) in CourtModel().landmarks.items()}
   with patch('cv2.VideoCapture',return_value=cap),patch.object(api,'_calibration_path_for',return_value=output):
    req=api.CourtMarkRequest(video_path=str(video),court_model='hoopai',landmarks=landmarks,at=2.5,revision=0)
    preview=asyncio.run(api.post_calibrate(req))
    self.assertTrue(preview['ok']);self.assertTrue(preview['lines']);self.assertFalse(output.exists())
    req.confirm=True
    with self.assertRaises(HTTPException) as err:asyncio.run(api.post_calibrate(req))
    self.assertEqual(err.exception.status_code,400)
    req.fixed_camera=True
    saved=asyncio.run(api.post_calibrate(req));self.assertTrue(saved['saved'])
    read=asyncio.run(api.get_calibration(str(video)))
    self.assertEqual(read['court_model'],'hoopai');self.assertEqual(read['capture_time_s'],2.5)
    self.assertEqual(len(read['normalized_points']),9)
    with self.assertRaises(HTTPException) as err:asyncio.run(api.post_calibrate(req))
    self.assertEqual(err.exception.status_code,409)
    asyncio.run(api.delete_calibration(str(video),read['revision']))
    self.assertFalse(output.exists())

 def test_old_model_has_nine_ground_landmarks(self):
  model=asyncio.run(api.hoopai_court_model())
  self.assertEqual(len(model['landmarks']),9)
  self.assertEqual(len(model['default_names']),4)

if __name__=='__main__':unittest.main()
