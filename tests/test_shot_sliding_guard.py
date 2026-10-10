import unittest
from aihoop.calibcheck import corners_at, sliding_coverage
class SlidingGuard(unittest.TestCase):
 def test_invalid_relock_and_end(self):
  c=[[0,0],[1,0],[1,1],[0,1]]
  a=lambda f,v,s:{'frame':f,'corners':c,'valid':v,'segment':s}
  d={'guarded_interpolation':True,'stride':5,'total_frames':20,'anchors':[a(0,True,0),a(5,False,0),a(10,True,1),a(15,True,1)]}
  coverage=sliding_coverage(d)
  actual=[i for i in range(20) if corners_at(d,i) is None]
  expanded=[i for a,b in coverage['frame_ranges'] for i in range(a,b)]
  self.assertEqual(actual,expanded);self.assertEqual(coverage['paused_frames'],len(actual))
  self.assertIsNone(sliding_coverage({}))
  for t in [-1,2,5,7,20,100]:self.assertIsNone(corners_at(d,t),t)
  for t in [0,10,12,15,19]:self.assertEqual(corners_at(d,t),c)
  d['anchors'][1]=a(5,True,1)
  self.assertIsNone(corners_at(d,2))
 def test_backend_payload_reaches_actual_frontend(self):
  import json, subprocess
  from pathlib import Path
  from aihoop.sources import RawTrack
  from aihoop.pipeline import _evidence_meta
  c=[[0,0],[1,0],[1,1],[0,1]]
  sliding={'guarded_interpolation':True,'fps':30,'stride':5,'total_frames':40,
    'anchors':[{'frame':f,'corners':c,'valid':True,'segment':s} for f,s in [(0,0),(15,0),(20,1),(30,1),(35,2)]]}
  sliding['coverage']=sliding_coverage(sliding)
  rt=RawTrack()
  rt.detections_meta['sliding_calibration']={k:v for k,v in sliding.items() if k!='anchors'}
  game={'meta':_evidence_meta(rt)}
  script="""
const fs=require('fs'),assert=require('assert/strict');global.window={};
require('./web/components.js');
const game=JSON.parse(fs.readFileSync(0,'utf8'));
const c=window.COMPONENTS['calibration-gaps'].computed.coverage.call({game});
assert.equal(c.paused_frames,8);assert.equal(c.analyzed_frames,40);
assert.deepEqual(c.frame_ranges,[[16,20],[31,35]]);
assert.deepEqual(c.ranges_s,[[16/30,20/30],[31/30,35/30]]);
"""
  subprocess.run(['node','-e',script],input=json.dumps(game),text=True,check=True,
                 cwd=Path(__file__).resolve().parents[1],capture_output=True)
 def test_legacy_unchanged(self):
  d={'anchors':[{'frame':0,'corners':[[0,0]]*4},{'frame':5,'corners':[[2,2]]*4}]}
  self.assertEqual(corners_at(d,100),[[2,2]]*4)
if __name__=='__main__':unittest.main()
