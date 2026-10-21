"""Guard audit counts: unknown is not a miss, unmatched made is still a false make."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('stage2',Path(__file__).resolve().parents[1]/'scripts/stage2_evidence_audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_unmatched_make_counts_both_event_and_make_fp(self):
        m=audit.metrics([dict(event_class='FP_unmatched',made_class='FP',model_result='made')])
        self.assertEqual(m['event']['fp'],1)
        self.assertEqual(m['made']['fp'],1)

    def test_unknown_matched_make_counts_fn_without_invented_miss(self):
        m=audit.metrics([dict(event_class='TP',made_class='FN',model_result='unknown')])
        self.assertEqual(m['event']['tp'],1)
        self.assertEqual(m['made']['fn'],1)
        self.assertEqual(m['unknown'],1)

    def test_one_event_never_repairs_unmatched_truth(self):
        rows=[dict(event_class='TP',made_class='TP',model_result='made'),
              dict(event_class='FN_unmatched',made_class='FN',model_result=None)]
        self.assertEqual(audit.metrics(rows)['event']['recall'],.5)
        self.assertEqual(audit.metrics(rows)['made']['recall'],.5)

    def test_empty_is_not_perfect_accuracy(self):
        m=audit.metrics([])
        self.assertIsNone(m['event']['precision'])
        self.assertIsNone(m['event']['recall'])

    def test_both_experimental_arms_keep_negative_and_positive_guards(self):
        from aihoop.legacy_shots.stream import LegacyShotStream
        from aihoop.legacy_shots.detector import Det
        rim=Det('rim',.9,(80,95,120,105))
        for strict in (False, True):
            for scenario in ('center','side','predicted','cut'):
                with self.subTest(strict=strict,scenario=scenario):
                    stream=LegacyShotStream(30,640,config={'score':{'strict_shot_gate':strict}})
                    for i in range(2):stream.update(i,i/30,[rim])
                    for i,y in enumerate((60,70,80,90,100,110,120,135,150,180),2):
                        x=150 if scenario=='side' else 100
                        ball=Det('basketball',.9,(x-5,y-5,x+5,y+5),predicted=scenario=='predicted')
                        # Test prediction guard at the scoring boundary: stream would
                        # reinterpret supplied detector candidates as measurements.
                        if scenario=='predicted':
                            stream.events.extend(stream.engine.update(i,i/30,ball,rim,[]))
                        else:
                            stream.update(i,i/30,[rim,ball],cut=scenario=='cut' and i==6)
                    stream.finish(12,.4)
                    self.assertEqual(sum(e['result']=='made' for e in stream.events),int(scenario=='center'))


if __name__=='__main__':unittest.main()
