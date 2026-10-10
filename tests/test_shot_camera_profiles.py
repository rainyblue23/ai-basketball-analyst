import asyncio, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from aihoop import api
from aihoop.court import Calibration
from aihoop.legacy_court import CourtModel

class Profiles(unittest.TestCase):
 def test_reuse_requires_confirmation_and_rechecks_target(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); a=root/'a.mp4'; b=root/'b.mp4'; a.touch(); b.touch()
   cap=MagicMock(); cap.get.side_effect=lambda k:640 if k==3 else 480
   marks={n:[(200+x*20)/640,(300-y*20)/480] for n,(x,y) in CourtModel().landmarks.items()}
   quality={'degenerate':False,'reason':'','hoop_check':{},'metrics':{}}
   with patch('cv2.VideoCapture',return_value=cap), patch.object(api,'DATA',root), patch.object(api,'_calibration_path_for',side_effect=lambda v:root/(Path(v).stem+'.json')), patch.object(api,'_calibration_quality',return_value=quality) as check:
    req=api.CourtMarkRequest(video_path=str(a),court_model='hoopai',fixed_camera=True,landmarks=marks,confirm=True,save_profile_name='主场')
    asyncio.run(api.post_calibrate(req))
    profile=asyncio.run(api.camera_profiles())['profiles'][0]
    req=api.CourtMarkRequest(video_path=str(b),court_model='hoopai',fixed_camera=True,profile_id=profile['id'])
    self.assertTrue(asyncio.run(api.post_calibrate(req))['lines'])
    self.assertFalse((root/'b.json').exists())
    req.confirm=True
    with self.assertRaises(HTTPException):asyncio.run(api.post_calibrate(req))
    req.overlay_confirmed=True
    check.return_value={**quality,'degenerate':True,'reason':'bad geometry'}
    with self.assertRaises(HTTPException):asyncio.run(api.post_calibrate(req))
    self.assertFalse((root/'b.json').exists())
    check.return_value=quality
    asyncio.run(api.post_calibrate(req))
    self.assertEqual(check.call_args.args[0],b)
    cal=Calibration.load(str(root/'b.json'))
    self.assertTrue(cal.matches_video(str(b)))
    self.assertFalse(cal.matches_video(str(a)))
    data=json.loads((root/'b.json').read_text(encoding='utf-8'))
    self.assertTrue(data['position_unverified']); self.assertFalse(data['hoop_checked']);
    self.assertTrue(data['overlay_confirmed']); self.assertEqual(data['applied_from'],str(a))
    cap.get.side_effect=lambda k:1280 if k==3 else 720
    with self.assertRaises(HTTPException):asyncio.run(api.post_calibrate(req))

if __name__=='__main__':unittest.main()
