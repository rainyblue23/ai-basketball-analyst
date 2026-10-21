"""Safety negatives for the isolated entry/crossing clock comparison."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('geometry', ROOT/'tests/test_shot_legacy_geometry.py')
geometry=importlib.util.module_from_spec(spec);spec.loader.exec_module(geometry)
from aihoop.legacy_shots.scorer import ScoreEngine
from aihoop.legacy_shots.detector import Det

class WindowSafety(unittest.TestCase):
    def test_both_clocks_on_synthetic_shapes(self):
        bounce=[(100,y) for y in (80,88,94,95,95,90,84,80)]+[(100,80)]*30+[(100,y) for y in (90,98,104,112,125,140)]
        cases={
          'side': ([(130,y) for y in (60,70,80,90,100,110,120,135,150,180)],False),
          'lateral_rim_graze': ([(100,90),(100,105),(150,105),(200,110),(240,115)],False),
          'upward_rebound': (bounce,False),
          'upward_departure': ([(100,90),(100,105),(100,90),(100,70),(100,50)],False),
          'stale_crossing': ([(100,94)]*3+[(100,102)]*35+[(100,120)]*3,False),
          'all_predicted': ([(100,y) for y in (60,70,80,90,100,110,120,135,150,180)],True),
        }
        for enabled in (False,True):
            for name,(points,predicted) in cases.items():
                with self.subTest(enabled=enabled,case=name):
                    ev=geometry.run_path(points,predicted=predicted,crossing_window=enabled)
                    self.assertFalse(any(x['result']=='made' for x in ev))

    def test_predicted_exit_and_cut_do_not_complete_measured_approach(self):
        rim=Det('rim',1,(80,95,120,105))
        for enabled in (False,True):
            for mode in ('predicted_exit','cut','long_gap','stale_rim'):
                with self.subTest(enabled=enabled,mode=mode):
                    cfg={'score':{'make_window_from_crossing':enabled}}
                    e=ScoreEngine(cfg,30);events=[]
                    for i in range(2):e.update(i,i/30,None,rim,[])
                    for i,y in enumerate((60,70,80,90,98,102,110,120,135,150,180),2):
                        if mode=='cut' and i==7:
                            events+=e.finalize(i,i/30);e=ScoreEngine(cfg,30)
                        predicted=mode=='predicted_exit' and i>=7
                        t=i/30+(1.6 if mode in ('long_gap','stale_rim') and i>=7 else 0)
                        b=Det('basketball',1,(97,y-3,103,y+3),predicted=predicted)
                        events+=e.update(i,t,b,None if mode=='stale_rim' and i>=7 else rim,[])
                    events+=e.finalize(20,3)
                    self.assertFalse(any(x['result']=='made' for x in events))

    def test_center_positive_and_delayed_approach(self):
        for enabled in (False,True):
            center=geometry.run_path([(100,y) for y in (60,70,80,90,100,110,120,135,150,180)],crossing_window=enabled)
            self.assertEqual(sum(x['result']=='made' for x in center),1)
            delayed=geometry.run_path([(100,94)]*35+[(100,y) for y in (98,102,106,112,120,135)],crossing_window=enabled)
            self.assertEqual(sum(x['result']=='made' for x in delayed),int(enabled))

if __name__=='__main__':unittest.main(verbosity=2)
