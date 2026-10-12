import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('evaluate',Path(__file__).resolve().parents[1]/'scripts/eval_match_annotations.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class MatchTests(unittest.TestCase):
 def test_one_prediction_cannot_match_two_shots(self):
  self.assertEqual(len(module.match_times([10,11],[10.5])),1)
 def test_maximum_matching_before_nearest(self):
  self.assertEqual(len(module.match_times([0,2],[1.4,3],1.5)),2)
 def test_empty_negative_video(self):
  self.assertEqual(module.match_times([],[1,2]),[])
 def test_outside_tolerance(self):
  self.assertEqual(module.match_times([10],[12]),[])
 def test_unsorted_indices_are_preserved(self):
  self.assertEqual([(i,j) for i,j,_ in module.match_times([20,10],[10,20])],[(1,0),(0,1)])

if __name__=='__main__':unittest.main()
