# -*- coding: utf-8 -*-
"""`scripts/check_truth_files.py` 的测试。

为什么钉它（用户 2026-10-11：「我来按清单标」）：
    标注人花在标注上的时间最贵，校验器**不能漏掉真错误、也不能乱报假错误** ——
    漏了就白标，假报就让人改半天正确的数据。所以两边都要有断言：
      * 真错误（号码与 readable 打架、时间出界、track_id 重复、传给自己）必须报；
      * 合法写法（号码给整数、team 留空、比分单调、evidence_s 空）**不许**报错。
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_truth", ROOT / "scripts" / "check_truth_files.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

BASE = {"match_01": {"id": "match_01", "start_s": 30.0, "end_s": 90.0},
        "match_02": {"id": "match_02", "start_s": 90.0, "end_s": 150.0}}


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------- 类型判定 ----------------

def test_detect_kind():
    assert check.detect_kind({"samples": [{"tracks": []}]}) == "jersey"
    assert check.detect_kind({"samples": [{"possessions": []}]}) == "tactics"
    assert check.detect_kind({"samples": [{"readings": []}]}) == "scoreboard"
    assert check.detect_kind({"samples": [{"shots": []}]}) == "shots"
    assert check.detect_kind({"samples": [{"nope": 1}]}) == "unknown"
    assert check.detect_kind({}) == "unknown"


def test_unknown_kind_is_a_hard_error(tmp_path):
    rep = check.check_file(write(tmp_path, "x.json", {"samples": [{"nope": 1}]}), BASE)
    assert not rep.ok and any("认不出" in e for e in rep.errors)


def test_broken_json_is_a_hard_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not json", encoding="utf-8")
    rep = check.check_file(p, BASE)
    assert not rep.ok and any("不是合法 JSON" in e for e in rep.errors)


# ---------------- 球衣号码 ----------------

def _jersey_samples(tracks):
    return {"annotator": "me", "time_basis": "original_video_seconds",
            "samples": [{"id": "match_01", "video": "v.mp4", "start_s": 30.0, "end_s": 90.0,
                         "tracks": tracks}]}


def test_jersey_accepts_valid_rows(tmp_path):
    data = _jersey_samples([
        {"track_id": 12, "team": "home", "jersey": "23", "readable": True, "evidence_s": [40.0]},
        {"track_id": 13, "team": "away", "jersey": 7, "readable": True, "evidence_s": []},   # 整数号码也接受
        {"track_id": 14, "team": "", "jersey": None, "readable": False, "evidence_s": [45.0]},
    ])
    rep = check.check_file(write(tmp_path, "jersey.json", data), BASE)
    assert rep.ok, rep.errors
    assert any("3 条" in n for n in rep.notes)
    assert any("还差 97 条" in n for n in rep.notes), "建议量进度要报出来"


def test_jersey_catches_readable_and_jersey_conflict(tmp_path):
    bad = [
        {"track_id": 1, "readable": True, "jersey": None},        # 说可读却没号码
        {"track_id": 2, "readable": False, "jersey": "9"},        # 说不可读却给了号码
    ]
    rep = check.check_file(write(tmp_path, "jersey.json", _jersey_samples(bad)), BASE)
    assert not rep.ok
    assert sum("只能有一个" in e or "没给号码" in e for e in rep.errors) == 2


def test_jersey_catches_bad_number_and_duplicate_track(tmp_path):
    bad = [
        {"track_id": 1, "readable": True, "jersey": "123"},
        {"track_id": 1, "readable": True, "jersey": "5"},
        {"track_id": "x", "readable": True, "jersey": "5"},
    ]
    rep = check.check_file(write(tmp_path, "jersey.json", _jersey_samples(bad)), BASE)
    joined = " ".join(rep.errors)
    assert "0~99" in joined, "三位数号码必须报错"
    assert "重复" in joined, "同一条轨迹标两次必须报错"
    assert "必须是整数" in joined


def test_jersey_catches_time_outside_clip(tmp_path):
    data = _jersey_samples([{"track_id": 1, "readable": True, "jersey": "5", "evidence_s": [500.0]}])
    rep = check.check_file(write(tmp_path, "jersey.json", data), BASE)
    assert any("不在片段" in e for e in rep.errors)


def test_new_truth_file_ids_do_not_need_the_old_testset(tmp_path):
    """新一批素材（id 与老测试集不同）**不能**被报成「不在测试集里」—— 那是假错误。"""
    data = {"annotator": "me", "time_basis": "original_video_seconds", "samples": [
        {"id": "s2_x", "video": "v.mp4", "start_s": 0.0, "end_s": 20.0, "shots_complete": True,
         "shots": [{"release_s": 5.0, "result": "made", "value": 2, "is_replay": False}]}]}
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert rep.ok, rep.errors
    # 但时间仍要落在**它自己写的**片段范围内
    data["samples"][0]["shots"][0]["release_s"] = 99.0
    rep2 = check.check_file(write(tmp_path, "shots2.json", data), BASE)
    assert any("不在片段" in e for e in rep2.errors)


def test_shots_requires_span(tmp_path):
    data = {"samples": [{"id": "s2_y", "shots": [{"release_s": 1.0, "result": "made", "value": 2}]}]}
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert any("start_s/end_s" in e for e in rep.errors)


def test_jersey_warns_when_no_evidence_time(tmp_path):
    data = _jersey_samples([{"track_id": 1, "readable": True, "jersey": "5", "evidence_s": []}])
    rep = check.check_file(write(tmp_path, "jersey.json", data), BASE)
    assert rep.ok and any("evidence_s" in w for w in rep.warns), "没写依据时间只该是警告"


def test_jersey_missing_annotator_is_warning_not_error(tmp_path):
    data = {"samples": [{"id": "match_01", "tracks": []}]}
    rep = check.check_file(write(tmp_path, "jersey.json", data), BASE)
    assert rep.ok and any("annotator" in w for w in rep.warns)


# ---------------- 战术层 ----------------

def test_tactics_valid_and_counts(tmp_path):
    data = {"annotator": "me", "time_basis": "original_video_seconds", "samples": [{
        "id": "match_01", "possessions": [
            {"start_s": 31.0, "end_s": 45.2, "team": "home",
             "passes": [{"t": 33.4, "from_track": 12, "to_track": 18}]}]}]}
    rep = check.check_file(write(tmp_path, "tactics.json", data), BASE)
    assert rep.ok, rep.errors
    assert any("1 个回合、1 次传球" in n for n in rep.notes)


def test_tactics_catches_reversed_span_self_pass_and_bad_team(tmp_path):
    data = {"samples": [{"id": "match_01", "possessions": [
        {"start_s": 50.0, "end_s": 40.0, "team": "ours",
         "passes": [{"t": 45.0, "from_track": 12, "to_track": 12}]}]}]}
    rep = check.check_file(write(tmp_path, "tactics.json", data), BASE)
    joined = " ".join(rep.errors)
    assert "必须小于" in joined and "home/away" in joined and "传给自己" in joined


def test_tactics_pass_outside_its_possession(tmp_path):
    data = {"samples": [{"id": "match_01", "possessions": [
        {"start_s": 31.0, "end_s": 35.0, "team": "home",
         "passes": [{"t": 60.0, "from_track": 12, "to_track": 18}]}]}]}
    rep = check.check_file(write(tmp_path, "tactics.json", data), BASE)
    assert any("不在这个回合" in e for e in rep.errors)


def test_tactics_overlap_is_warning(tmp_path):
    data = {"samples": [{"id": "match_01", "possessions": [
        {"start_s": 31.0, "end_s": 40.0, "team": "home", "passes": []},
        {"start_s": 39.0, "end_s": 45.0, "team": "away", "passes": []}]}]}
    rep = check.check_file(write(tmp_path, "tactics.json", data), BASE)
    assert rep.ok and any("重叠" in w for w in rep.warns)


# ---------------- 比分牌 ----------------

def test_scoreboard_valid_and_monotonic_warning(tmp_path):
    good = {"annotator": "me", "time_basis": "original_video_seconds",
            "samples": [{"id": "match_01", "readings": [
                {"t": 30.0, "home": 12, "away": 9}, {"t": 60.0, "home": 14, "away": 11}]}]}
    rep = check.check_file(write(tmp_path, "sb.json", good), BASE)
    assert rep.ok and rep.warns == [], rep.warns

    bad = {"annotator": "me", "time_basis": "original_video_seconds",
           "samples": [{"id": "match_01", "readings": [
               {"t": 30.0, "home": 12, "away": 9}, {"t": 60.0, "home": 11, "away": 9}]}]}
    rep2 = check.check_file(write(tmp_path, "sb2.json", bad), BASE)
    assert rep2.ok and any("比分比上一条小" in w for w in rep2.warns), "比分回退只该是警告（可能确实如此）"


def test_scoreboard_rejects_negative_and_non_int(tmp_path):
    bad = {"samples": [{"id": "match_01", "readings": [{"t": 30.0, "home": -1, "away": "9"}]}]}
    rep = check.check_file(write(tmp_path, "sb.json", bad), BASE)
    assert len(rep.errors) >= 2


# ---------------- 出手真值（用户要标的那一类）----------------

def _shots_samples(shots, **extra):
    s = {"id": "match_01", "video": "v.mp4", "start_s": 30.0, "end_s": 90.0,
         "source_sha256": "x", "shots_complete": True, "shots": shots}
    s.update(extra)
    return {"annotator": "me", "time_basis": "original_video_seconds", "samples": [s]}


def test_shots_valid_counts_toward_target(tmp_path):
    data = _shots_samples([
        {"release_s": 40.87, "result": "missed", "value": 2, "is_replay": False, "note": ""},
        {"release_s": 62.42, "result": "made", "value": 1, "is_replay": False, "note": ""},
    ])
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert rep.ok, rep.errors
    assert any("2 次出手" in n and "还差 18 次" in n for n in rep.notes)


def test_shots_rejects_bad_result_value_and_time(tmp_path):
    data = _shots_samples([
        {"release_s": 500.0, "result": "maybe", "value": 4, "is_replay": "no"},
    ])
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    joined = " ".join(rep.errors)
    assert "不在片段" in joined
    assert "made/missed" in joined
    assert "1/2/3" in joined
    assert "is_replay" in joined


def test_shots_missing_release_is_error(tmp_path):
    rep = check.check_file(write(tmp_path, "shots.json", _shots_samples([{"result": "made", "value": 2}])), BASE)
    assert any("release_s" in e for e in rep.errors)


def test_shots_incomplete_and_missing_replay_are_warnings(tmp_path):
    data = _shots_samples([{"release_s": 40.0, "result": "made", "value": 3}], shots_complete=False)
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert rep.ok
    assert any("shots_complete" in w for w in rep.warns)
    assert any("is_replay" in w for w in rep.warns)
    assert any("未标完" in n for n in rep.notes)


def test_shots_too_close_is_warning_not_error(tmp_path):
    data = _shots_samples([
        {"release_s": 40.0, "result": "made", "value": 2, "is_replay": False},
        {"release_s": 40.8, "result": "missed", "value": 2, "is_replay": False},
    ])
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert rep.ok and any("小于匹配容差" in w for w in rep.warns)


def test_shots_missing_video_file_is_warning(tmp_path):
    data = _shots_samples([{"release_s": 40.0, "result": "made", "value": 2, "is_replay": False}],
                          video="Z:/nope.mp4")
    rep = check.check_file(write(tmp_path, "shots.json", data), BASE)
    assert rep.ok and any("不存在" in w for w in rep.warns)


# ---------------- 默认扫描与退出码 ----------------

def test_default_files_skips_templates_and_testset(tmp_path):
    (tmp_path / "jersey_split1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "match_testset_x.json").write_text("{}", encoding="utf-8")
    (tmp_path / "jersey_split1.template.json").write_text("{}", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    names = [p.name for p in check.default_files(tmp_path)]
    assert names == ["jersey_split1.json"], names


def test_main_returns_nonzero_when_errors(tmp_path):
    p = write(tmp_path, "jersey_split1.json",
              {"samples": [{"id": "match_01", "tracks": [{"track_id": 1, "readable": True, "jersey": None}]}]})
    assert check.main([str(p)]) == 1
    ok = write(tmp_path, "jersey_ok.json",
              {"annotator": "me", "time_basis": "original_video_seconds",
               "samples": [{"id": "match_01", "tracks": [
                   {"track_id": 1, "readable": True, "jersey": "5", "evidence_s": [31.0]}]}]})
    assert check.main([str(ok)]) == 0
