import unittest
from aihoop.legacy_shots.ball_selection import select_ball
from aihoop.legacy_shots.detector import Det

def ball(x,conf=.7,w=12):return Det('basketball',conf,(x,40,x+w,52))

class SelectionTest(unittest.TestCase):
 def test_motion_beats_high_confidence_stationary_decoy(self):
  old=ball(100);moving=ball(180,.65);decoy=ball(100,.75)
  selected,a=select_ball([decoy,moving],old,1,(80,0),5,90)
  self.assertIs(selected,moving);self.assertEqual(a[1]['selection_reason'],'selected')
 def test_jump_is_rejected_not_promoted(self):
  selected,a=select_ball([ball(800)],ball(10),10,(0,0),5,90)
  self.assertIsNone(selected);self.assertEqual(a[0]['selection_reason'],'motion_rejected')
 def test_scale_is_soft_not_a_filter(self):
  candidate=ball(20,w=60)
  selected,_=select_ball([candidate],ball(20),1,(0,0),5,90)
  self.assertIs(selected,candidate);self.assertFalse(selected.predicted)
 def test_no_history_does_not_invent_identity(self):
  high=ball(40,.9);selected,_=select_ball([ball(10),high],None,1,(0,0),5,90)
  self.assertIs(selected,high)
 def test_no_candidates(self):
  self.assertEqual(select_ball([],None,1,(0,0),5,90),(None,[]))

if __name__=='__main__':unittest.main()
