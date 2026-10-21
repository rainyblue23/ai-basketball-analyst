import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from crossing_evidence_audit import OUT, IMPORT, read, sha, metric
from eval_match_annotations import match_times


class AuditTests(unittest.TestCase):
    def test_tolerance_and_one_to_one(self):
        self.assertEqual(len(match_times([1], [2.5], 1.5)), 1)
        self.assertEqual(match_times([1], [2.500001], 1.5), [])
        self.assertEqual(len(match_times([1, 1.1], [1.05], 1.5)), 1)

    def test_no_made_predictions_precision_undefined(self):
        self.assertIsNone(metric(0, 0, 8)["precision"])
        self.assertEqual(metric(0, 0, 8)["recall"], 0)

    def test_import_identity_and_scope(self):
        samples = read(IMPORT)["samples"]
        self.assertEqual(sum(len(s["shots"]) for s in samples), 59)
        self.assertEqual(sum(len({t["play_id"] for t in s["shots"]}) for s in samples), 57)
        for s in samples:
            self.assertEqual(sha(s["video"]), s["source_sha256"])
            self.assertTrue(s["shots_complete"])
            self.assertEqual(s["dataset_split"], "Development")
            self.assertTrue(all(s["reviewed_range_declared"][0] <= t["release_s"] <
                                s["reviewed_range_declared"][1] for t in s["shots"]))

    def test_independent_metric_recount(self):
        source = {s["id"]: s for s in read(OUT/"baseline/results.json")["samples"]}
        for s in read(OUT/"baseline_metrics.json")["samples"]:
            raw = source[s["id"]]
            pairs = match_times([t["release_s"] for t in raw["truth"]],
                                [e["release_s"] for e in raw["events"]], 1.5)
            tp = sum(raw["truth"][i]["result"] == raw["events"][j]["result"] == "made" for i,j,_ in pairs)
            self.assertEqual(s["made"]["TP"], tp)
            self.assertEqual(s["made"]["FP"], sum(e["result"]=="made" for e in raw["events"])-tp)
            self.assertEqual(s["made"]["FN"], sum(t["result"]=="made" for t in raw["truth"])-tp)
            self.assertEqual(s["UNKNOWN"], sum(e["result"]=="unknown" for e in raw["events"]))

    def test_review_not_truth_and_exit_not_fabricated(self):
        tasks = read(OUT/"review/tasks.json")
        self.assertEqual(len(tasks), 5)
        for task in tasks:
            self.assertEqual(task["review_status"], "PENDING_VALIDATION")
            self.assertIsNone(task["human_evidence"])
            for frame in read(OUT/"review"/task["trace"]):
                for s in frame["states"].values():
                    self.assertIsNone(s["exit_t"])
                    if frame["ball"] and frame["ball"].get("predicted"):
                        self.assertFalse(s["geometric_exit_sample"])
        identity = next(t for t in tasks if "identity" in t["id"])
        self.assertIsNone(identity["existing_truth_result"])

    def test_production_defaults_and_integrity(self):
        for name in ("yang", "lillard", "harden"):
            raw = read(OUT/f"baseline/{name}/raw_track.json")
            self.assertFalse(raw["detections_meta"]["legacy_shots"]["config"]["score"]["make_window_from_crossing"])
        self.assertTrue(read(OUT/"protected_after.json")["unchanged"])

    def test_each_error_has_diagnostic_evidence(self):
        rows = read(OUT/"event_errors.json")
        self.assertEqual(len(rows), 70)  # 59 appearances plus 11 unmatched events.
        for r in rows:
            self.assertIn("evidence_coverage", r)
            self.assertIn("full_engine_event", r)
            self.assertTrue((OUT/r["raw_trace"]).is_file())
            self.assertIsNone(r["original_full_game_time"])
            if r.get("event_index") is not None:
                self.assertIsNotNone(r["full_engine_event"])


if __name__ == "__main__":
    unittest.main()
