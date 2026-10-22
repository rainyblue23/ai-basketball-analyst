import unittest
from pydantic import ValidationError
from aihoop.legacy_shots.settings import LegacyDetectOptions, resolve_detect, prediction_options
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.legacy_shots.detector import Det

class NightSettings(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(resolve_detect()['imgsz'],640)
        d=resolve_detect({'profile':'night'});self.assertEqual((d['imgsz'],d['rim_min_conf']),(960,.30))
        self.assertEqual(resolve_detect({'profile':'night','imgsz':1280})['imgsz'],1280)
    def test_validation(self):
        for v in ({'imgsz':961},{'rim_min_conf':-1},{'profile':'oops'},{'ball_conf':1.1}):
            with self.assertRaises(ValidationError):LegacyDetectOptions(**v)
    def test_detector_floor(self):
        d={'ball_conf':.25,**resolve_detect({'rim_min_conf':.2})}
        self.assertEqual(prediction_options(d),dict(imgsz=640,conf=.2,iou=.5))
        self.assertEqual(d['ball_conf'],.25)
    def stream(self,**kw):
        return LegacyShotStream(30,960,config={'detect':resolve_detect({'profile':'night'})},**kw)
    def test_low_conf_confirmation(self):
        s=self.stream();r=Det('rim',.31,(400,100,460,120))
        s.update(1,1/30,[r]);self.assertIsNone(s.frames[-1]['rim'])
        s.update(2,2/30,[r]);self.assertIsNotNone(s.frames[-1]['rim'])
    def test_unrelated_frames_do_not_confirm(self):
        s=self.stream();s.update(1,.03,[Det('rim',.31,(0,100,60,120))])
        s.update(2,.06,[Det('rim',.31,(700,100,760,120))])
        self.assertIsNone(s.frames[-1]['rim'])
    def test_cut_clears_hint_and_history(self):
        s=self.stream(hint=(430,110));r=Det('rim',.31,(400,100,460,120))
        s.update(1,.03,[r]);s.update(2,.06,[r],cut=True)
        self.assertIsNone(s.hint);self.assertIsNone(s.frames[-1]['rim'])
    def test_high_conf_unchanged(self):
        s=self.stream();s.update(1,.03,[Det('rim',.8,(400,100,460,120))])
        self.assertIsNotNone(s.frames[-1]['rim'])
    def test_api_source(self):
        from aihoop.api import JobCreate
        from aihoop.sources import VideoSource
        req=JobCreate(legacy_detect={'profile':'night'})
        v=VideoSource('unused.mp4',None,legacy_detect=req.legacy_detect.model_dump())
        self.assertEqual(v.legacy_detect['imgsz'],960)

if __name__=='__main__':unittest.main()
