"""Human annotations must stay separate from automatic evidence and replay counts."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('review_examples',ROOT/'scripts/review_examples.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ReviewedExamples(unittest.TestCase):
    def test_lillard_replays_are_separate(self):
        truth=module.supplied_truth()['lillard']; c=module.counts(truth['shots'])
        self.assertEqual((c['field_attempts'],c['field_made']),(14,9))
        self.assertEqual((c['free_throw_attempts'],c['free_throw_made']),(1,0))
        self.assertEqual((c['unique_field_attempts'],c['unique_field_made']),(12,7))
        self.assertEqual(c['replay_count'],2)
        repeated=[s for s in truth['shots'] if s.get('play_id')=='lillard_buzzer']
        self.assertEqual([s['release_t'] for s in repeated],[141,159,171])

    def test_harden_putback_is_a_second_attempt(self):
        truth=module.supplied_truth()['harden'];c=module.counts(truth['shots'])
        self.assertEqual((c['field_attempts'],c['field_made']),(34,31))
        near=[s for s in truth['shots'] if 115<=s['release_t']<=116]
        self.assertEqual([s['result'] for s in near],['missed','made'])
        self.assertEqual(c['replay_count'],0)

    def test_unknown_values_are_not_invented(self):
        truth=module.supplied_truth()
        self.assertIsNone(truth['lillard']['shots'][0]['value'])
        self.assertEqual(truth['lillard']['shots'][2]['result'],'missed')
        self.assertTrue(all(t['source']=='human_user' for t in truth.values()))

if __name__=='__main__':unittest.main()
