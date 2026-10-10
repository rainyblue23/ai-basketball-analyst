import unittest
from types import SimpleNamespace

from aihoop.legacy_shots.adapter import to_attempts
from aihoop.model import Player, player_label
from aihoop.replay_overlay import detection_overlay
from aihoop.rules import build_shots, compute_player_stats, is_free_throw_position
from aihoop.sources import (
    RawTrack, assign_player_short_labels, calibrated_person_on_court,
)


class ShotSemanticsTest(unittest.TestCase):
    def test_free_throw_geometry_is_conservative(self):
        self.assertTrue(is_free_throw_position(0.2, 5.8))
        self.assertTrue(is_free_throw_position(-0.3, -5.7))
        self.assertFalse(is_free_throw_position(2.0, 5.8))
        self.assertFalse(is_free_throw_position(0.1, 3.0))

    def test_calibrated_legacy_release_becomes_free_throw(self):
        rt = RawTrack(fps=30, duration=10,
                      detections_meta={"calibration_valid": True})
        rt.players["T1"] = Player("T1", "号码待确认", "home")
        cal = SimpleNamespace(to_court=lambda x, y: (0.2, 5.8))
        event = {"t": 2.5, "type": "make", "player_id": "T1",
                 "release_source": "player_feet", "release_xy": [10, 20]}
        attempt = to_attempts([event], rt, calibration=cal)[0]
        self.assertTrue(attempt.is_free_throw)
        self.assertEqual(attempt.forced_value, 1)
        shot = build_shots([attempt.to_dict()])[0]
        self.assertEqual(shot.value, 1)
        self.assertEqual(shot.to_dict()["shot_type"], "free_throw")
        self.assertIn("free_throw", shot.tags)

    def test_short_labels_are_per_team_and_hide_track_ids(self):
        players = {
            "T20": Player("T20", "号码待确认", "home"),
            "T3": Player("T3", "号码待确认", "home", jersey=8),
            "T9": Player("T9", "号码待确认", "away"),
        }
        assign_player_short_labels(players)
        self.assertEqual(player_label(players["T20"].to_dict()), "A1")
        self.assertEqual(player_label(players["T3"].to_dict()), "8号")
        self.assertEqual(player_label(players["T9"].to_dict()), "B1")
        rows = compute_player_stats([
            build_shots([{"t": 1.0, "team": "home", "player_id": "T20",
                          "x": 1.0, "y": 4.0, "made": False}])[0],
            build_shots([{"t": 2.0, "team": "home", "player_id": "T3",
                          "x": 1.0, "y": 4.0, "made": True}])[0],
            build_shots([{"t": 3.0, "team": "away", "player_id": "T9",
                          "x": 1.0, "y": 4.0, "made": False}])[0],
        ], players)
        # 球员统计载荷也必须带短标签，前端不能退回显示 T20/T9。
        self.assertEqual({r["player_id"]: r["short_label"] for r in rows},
                         {"T20": "A1", "T3": "A2", "T9": "B1"})

    def test_off_court_people_do_not_receive_green_boxes(self):
        raw = {"width": 960, "height": 540,
               "detections_meta": {"legacy_shots": {"frames": [{
                   "t": 1.0, "persons": [
                       {"xyxy": [10, 10, 30, 80], "track_id": "T1", "on_court": True},
                       {"xyxy": [50, 10, 70, 80], "track_id": "T2", "on_court": False},
                   ]}]}}}
        players = detection_overlay(raw)["frames"][0]["players"]
        self.assertEqual([p["id"] for p in players], ["T1"])

    def test_calibrated_person_filter_uses_box_foot_point(self):
        class FakeCal:
            H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]

            @staticmethod
            def to_court(x, y):
                return x, y

            @staticmethod
            def in_court(x, y, tol=0.12):
                return 0 <= x <= 28 and 0 <= y <= 15

        cal = FakeCal()
        self.assertTrue(calibrated_person_on_court(cal, [5, -10, 7, 8]))
        self.assertFalse(calibrated_person_on_court(cal, [30, 0, 34, 8]))
        self.assertIsNone(calibrated_person_on_court(None, [30, 0, 34, 8]))


if __name__ == "__main__":
    unittest.main()
