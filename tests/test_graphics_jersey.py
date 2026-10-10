import unittest
import numpy as np
import cv2
from aihoop.screen_graphics import learn,matches
from aihoop.jersey_numbers import consensus,number_from_words,recognize
from unittest.mock import patch,MagicMock
from types import SimpleNamespace
import json
from pathlib import Path
from aihoop.model import Player
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.legacy_shots.detector import Det
from aihoop.replay_overlay import detection_overlay

class GraphicsAndJerseyTest(unittest.TestCase):
 def samples(self,changing=True):
  rng=np.random.default_rng(8);logo=rng.integers(0,255,(12,12,3),dtype=np.uint8);out=[]
  for i in range(4):
   image=np.full((100,200,3),i*50 if changing else 30,dtype=np.uint8);image[84:96,164:176]=logo
   out.append((i*4,image,[[164,84,176,96]]))
  return out
 def test_fixed_appearance_across_scene_changes(self):
  samples=self.samples();g=learn(samples,200,100);self.assertEqual(len(g),1)
  self.assertTrue(matches(samples[0][1],[164,84,176,96],g))
  altered=samples[0][1].copy();altered[84:96,164:176]=0
  self.assertFalse(matches(altered,[164,84,176,96],g))
  self.assertFalse(matches(None,[164,84,176,96],g))
 def test_transparent_graphic_surroundings_change_without_blanket_mask(self):
  rng=np.random.default_rng(19);core=rng.integers(0,255,(8,8,3),dtype=np.uint8);samples=[]
  for i in range(6):
   img=np.full((100,200,3),i*40,dtype=np.uint8);img[86:94,166:174]=core
   samples.append((i*4,img,[[164,84,176,96]]))
  g=learn(samples,200,100);self.assertEqual(len(g),1)
  test=np.full((100,200,3),113,dtype=np.uint8);test[86:94,166:174]=core
  self.assertTrue(matches(test,[164,84,176,96],g))
  faded=(test.astype(float)*.55+35).astype(np.uint8)
  self.assertTrue(matches(faded,[164,84,176,96],g))
  test[84:96,164:176]=rng.integers(0,255,(12,12,3),dtype=np.uint8)
  self.assertFalse(matches(test,[164,84,176,96],g))
 def test_local_ocr_respects_cpu_and_never_downloads_or_forces_digits(self):
  import sys,tempfile
  from aihoop.jersey_numbers import model_read
  reader=MagicMock();reader.readtext.return_value=[([[10,20],[40,20],[40,60],[10,60]],'22',.99),([[0,0],[5,0],[5,5],[0,5]],'8',.4)]
  module=SimpleNamespace(Reader=MagicMock(return_value=reader))
  with patch.dict(sys.modules,{'easyocr':module}):
   rows=model_read(Path('.'),{'one.png':{}},Path('local'),'cpu')
  self.assertFalse(module.Reader.call_args.kwargs['gpu'])
  self.assertFalse(module.Reader.call_args.kwargs['download_enabled'])
  self.assertNotIn('allowlist',reader.readtext.call_args.kwargs)
  self.assertEqual([w['text'] for w in rows[0]['words']],['22'])
 def test_static_scene_is_not_graphics_evidence(self):
  self.assertEqual(learn(self.samples(False),200,100),[])
 def test_logo_removed_live_ball_retained_and_audited(self):
  samples=self.samples();g=learn(samples,200,100);s=LegacyShotStream(30,200,{'detect':{'screen_graphics':g}})
  ball=s.update(0,0,[Det('basketball',.99,(164,84,176,96)),Det('basketball',.6,(40,40,52,52))],image=samples[0][1])
  self.assertEqual(ball.xyxy,(40,40,52,52))
  self.assertEqual(s.frames[0]['ball_candidates'][0]['selection_reason'],'screen_graphic')
 def test_hd_minimum_and_reference_resolution(self):
  for width in (852,960,1920):
   s=LegacyShotStream(30,width);b=s.update(0,0,[Det('basketball',.8,(40,40,52,52))]);self.assertIsNotNone(b)
  s=LegacyShotStream(30,1920);self.assertIsNone(s.update(0,0,[Det('basketball',.8,(40,40,45,45))]))
 def test_jersey_votes_need_independent_times(self):
  self.assertIsNone(consensus([{'t':0,'number':'13'}]*5))
  self.assertEqual(consensus([{'t':t,'number':'00'} for t in (0,.3,.6)])['number'],'00')
  self.assertIsNone(consensus([{'t':i*.3,'number':n} for i,n in enumerate(['13','13','13','12'])]))
 def test_digit_geometry_and_ambiguity(self):
  word={'text':'0','x':30,'y':20,'w':20,'h':40}
  self.assertEqual(number_from_words([word],100,100),'0')
  self.assertIsNone(number_from_words([word,dict(word,text='13')],100,100))
  self.assertIsNone(number_from_words([dict(word,text='NBA')],100,100))
 def test_ocr_crop_to_confirmed_player(self):
  observations=[{'t':t,'player_id':'T1','box':[0,0,100,200]} for t in (0,.3,.6)]
  image=np.full((240,120,3),180,np.uint8);cv2.putText(image,'13',(25,110),0,1.5,(0,0,0),3)
  cap=MagicMock();cap.get.return_value=30;cap.read.return_value=(True,image)
  def ocr(args,**kwargs):
   folder=Path(args[args.index('-ImageDir')+1]);out=Path(args[args.index('-OutJson')+1])
   out.write_text(json.dumps([{'file':p.name,'words':[{'text':'13','x':30,'y':40,'w':35,'h':50}]} for p in folder.glob('jersey_*.png')]),encoding='utf-8')
   return SimpleNamespace(returncode=0)
  players={'T1':Player('T1','号码待确认','home')}
  with patch('aihoop.jersey_numbers.model_path',return_value=None),patch('aihoop.jersey_numbers.shutil.which',return_value='powershell'),patch('aihoop.jersey_numbers.cv2.VideoCapture',return_value=cap),patch('aihoop.jersey_numbers.subprocess.run',side_effect=ocr):
   result=recognize('unused',observations,players)
  self.assertEqual(result['confirmed_tracks'],1);self.assertEqual(players['T1'].jersey,13);self.assertEqual(players['T1'].name,'13号')
 def test_cross_cut_track_does_not_get_number(self):
  observations=[{'t':t,'player_id':'T1','box':[0,0,100,200]} for t in (0,.3,.6)]
  with patch('aihoop.jersey_numbers.model_path',return_value=None),patch('aihoop.jersey_numbers.shutil.which',return_value='powershell'),patch('aihoop.jersey_numbers.cv2.VideoCapture',return_value=MagicMock()),patch('aihoop.jersey_numbers.subprocess.run') as run:
   result=recognize('unused',observations,{},cuts=[.4])
  self.assertEqual(result['sampled_crops'],0);run.assert_not_called()
 def test_report_player_labels_preserve_jersey_zero_and_hide_track_ids(self):
  from aihoop.model import player_label
  self.assertEqual(player_label({'player_id':'T1','name':'T1','jersey':0}),'0号')
  self.assertEqual(player_label({'player_id':'T1','name':'T1','jersey':'00'}),'00号')
  self.assertEqual(player_label({'player_id':'T1','name':'T1'}),'号码待确认')
  self.assertEqual(player_label({'player_id':'T1','name':'张三'}),'张三')
 def test_head_overlap_is_described_without_deleting_observation(self):
  raw={'width':200,'height':100,'detections_meta':{'legacy_shots':{'frames':[{'t':0,'ball':{'xyxy':[44,10,56,22]},'persons':[{'xyxy':[35,5,70,95],'track_id':'T1'}]}]}}}
  frame=detection_overlay(raw)['frames'][0]
  self.assertTrue(frame['ball_suspect']);self.assertEqual(frame['ball'],[44.,10.,56.,22.])
 def test_overlay_jersey_zero_preserved(self):
  out=detection_overlay({'players':{'T1':{'jersey':0,'name':'0号'}},'player_obs':[{'t':0,'player_id':'T1','box':[0,0,30,90]}]})
  self.assertEqual(out['frames'][0]['players'][0]['jersey'],0)

if __name__=='__main__':unittest.main()
