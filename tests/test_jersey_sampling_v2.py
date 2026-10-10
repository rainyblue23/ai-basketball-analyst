import unittest
import numpy as np
import cv2
from aihoop.jersey_numbers import select_observations,torso_bounds,crop_quality,consensus,recognize
from unittest.mock import patch,MagicMock
from pathlib import Path
from types import SimpleNamespace

class JerseySamplingTest(unittest.TestCase):
    def test_covers_track_and_retains_old_samples(self):
        obs=[{'t':i*.3,'box':[0,0,100,200-i]} for i in range(40)]
        picked=select_observations(obs)
        self.assertEqual(len(picked),12)
        self.assertEqual([o['t'] for o in picked[:5]],[o['t'] for o in obs[:5]])
        self.assertIn(obs[-1],picked)
        self.assertTrue(all(abs(a['t']-b['t'])>=.25 for i,a in enumerate(picked) for b in picked[i+1:]))
    def test_uniform_and_tiny_are_not_readability(self):
        self.assertFalse(crop_quality(np.zeros((100,100,3),np.uint8))['usable'])
        self.assertFalse(crop_quality(np.zeros((5,100,3),np.uint8))['usable'])
        img=np.full((100,100,3),120,np.uint8);cv2.putText(img,'13',(10,65),0,1.5,(0,0,0),3)
        self.assertTrue(crop_quality(img)['usable'])
    def test_native_sharpness_ranks_before_upscale(self):
        rng=np.random.default_rng(10);sharp=rng.integers(0,255,(80,80,3),dtype=np.uint8)
        self.assertGreater(crop_quality(sharp)['score'],crop_quality(cv2.GaussianBlur(sharp,(11,11),3))['score'])
    def test_pose_and_invalid_pose_fallback(self):
        o={'box':[0,0,100,200]};base=torso_bounds(o,100,200)
        kp=[[0,0,0] for _ in range(17)]
        for i,xy in zip((5,6,11,12),((25,40),(75,40),(30,130),(70,130))):kp[i]=[*xy,.9]
        o['keypoints']=kp
        bounds,source=torso_bounds(o,100,200);self.assertEqual(source,'pose_torso');self.assertNotEqual(bounds,base[0])
        kp[5][2]=.1;self.assertEqual(torso_bounds(o,100,200),base)
        kp[5]=[float('nan'),40,.9];self.assertEqual(torso_bounds(o,100,200),base)
    def test_conflicting_same_frame_does_not_cast_vote(self):
        rs=[{'t':0,'number':'13'},{'t':0,'number':'12'},{'t':.3,'number':'13'},{'t':.6,'number':'13'}]
        self.assertIsNone(consensus(rs))
        self.assertEqual(consensus([{'t':t,'number':'00'} for t in (0,.3,.6)])['number'],'00')
    def test_flat_frames_do_not_call_ocr_or_assign_number(self):
        obs=[{'t':t,'player_id':'T1','box':[0,0,100,200]} for t in (0,.3,.6)]
        cap=MagicMock();cap.get.return_value=30;cap.read.return_value=(True,np.zeros((240,120,3),np.uint8))
        with patch('aihoop.jersey_numbers.model_path',return_value='local'),patch('aihoop.jersey_numbers.cv2.VideoCapture',return_value=cap),patch('aihoop.jersey_numbers.model_read') as read:
            result=recognize('unused',obs,{})
        read.assert_not_called();self.assertEqual(result['sampled_crops'],0)
        self.assertEqual(result['quality_rejections']['uniform_crop'],3)
    def test_budget_gives_multiple_tracks_independent_evidence(self):
        obs=[{'t':i*.3,'player_id':pid,'box':[0,0,100,200]} for pid in ('T1','T2') for i in range(30)]
        image=np.full((240,120,3),180,np.uint8);cv2.putText(image,'13',(25,110),0,1.5,(0,0,0),3)
        cap=MagicMock();cap.get.return_value=30;cap.read.return_value=(True,image)
        def read(folder,records,path,device):
            return [{'file':name,'words':[{'text':'13','x':30,'y':40,'w':35,'h':50}]} for name in records]
        players={pid:SimpleNamespace(player_id=pid,name='号码待确认',jersey=None) for pid in ('T1','T2')}
        with patch('aihoop.jersey_numbers.model_path',return_value=Path('local')),patch('aihoop.jersey_numbers.cv2.VideoCapture',return_value=cap),patch('aihoop.jersey_numbers.model_read',side_effect=read),patch.object(Path,'read_bytes',return_value=b'weights'):
            result=recognize('unused',obs,players,max_crops=12)
        self.assertEqual(result['sampled_crops'],12)
        self.assertEqual(result['confirmed_tracks'],2)
        for v in result['per_player'].values():
            self.assertEqual(v['observed_crops'],6)
            self.assertEqual(len({r['t'] for r in v['readings']}),6)
            self.assertTrue(all(r['crop_source']=='box_torso' for r in v['readings']))

if __name__=='__main__':unittest.main()
