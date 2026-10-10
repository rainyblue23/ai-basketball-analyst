# -*- coding: utf-8 -*-
"""分时段标定：**时间归属**与按时刻取标定（用户 2026-10-05 的验收重点）。

验收重点逐条对应：
  ① 前段标定不影响后段；② 间隙不给坐标；③ 切镜不沿用旧标定；（异步叠线不串帧在 JS 测试里）
  另外锁住字段表的语义：参考帧就是**矩阵所属那一帧**（不许把两幅画面的时间取平均）、
  时段左闭右开、没写时段一律不可用。
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop import calib_segments as cs   # noqa: E402


def _with_temp_data():
    tmp = tempfile.TemporaryDirectory()
    cs.DATA = Path(tmp.name)
    return tmp


def _seg(H_id, a, b, capture=1.0, ref=None, sources=None):
    return cs.make_segment(
        {"H": [[H_id, 0, 0], [0, 1, 0], [0, 0, 1]], "point_names": ["p1"]},
        capture_time_s=capture, reference_frame=(capture if ref is None else ref),
        source_frames=sources or [{"t": capture, "n": 4, "landmarks": {}}],
        valid_from_s=a, valid_to_s=b,
        verification={"position_unverified": True, "rmse_m": 0.2}, label="段%s" % H_id)


def test_earlier_segment_does_not_affect_later():
    """① 前段标定不影响后段：两个时段各拿各的矩阵。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_A.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 10.0, capture=2.0))
        cs.record_segment(V, _seg(5.0, 10.0, 20.0, capture=12.0))
        at3 = cs.calibration_for_time(V, 3.0)
        at15 = cs.calibration_for_time(V, 15.0)
        assert at3["ok"] and at3["H"][0][0] == 2.0, at3
        assert at15["ok"] and at15["H"][0][0] == 5.0, at15
        assert at3["segment"]["capture_time_s"] == 2.0
        assert at15["segment"]["capture_time_s"] == 12.0
    finally:
        tmp.cleanup()


def test_gap_returns_unavailable():
    """② 间隙不给坐标。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_B.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 5.0, capture=2.0))
        cs.record_segment(V, _seg(5.0, 10.0, 20.0, capture=12.0))
        gap = cs.calibration_for_time(V, 7.5)
        assert gap["ok"] is False and gap["reason"] == "no_coverage", gap
        assert gap["H"] is None
    finally:
        tmp.cleanup()


def test_left_closed_right_open():
    """时段是**左闭右开**：t=valid_to_s 的那一刻不算在这一段里。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_C.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 10.0, capture=2.0))
        assert cs.calibration_for_time(V, 0.0)["ok"] is True
        assert cs.calibration_for_time(V, 9.999)["ok"] is True
        assert cs.calibration_for_time(V, 10.0)["ok"] is False
    finally:
        tmp.cleanup()


def test_overlap_is_rejected_and_conflict_reported():
    """时段重叠：保存直接拒；万一文件里已经重叠，取用时报冲突、不给坐标。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_D.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 10.0, capture=2.0))
        try:
            cs.record_segment(V, _seg(5.0, 5.0, 15.0, capture=6.0))
            raise AssertionError("重叠时段必须被拒")
        except ValueError as e:
            assert "重叠" in str(e), e
        # 手工造一个重叠文档（模拟外部写入/历史数据）
        p = cs.calibration_path(V)
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["segments"].append(_seg(7.0, 4.0, 6.0, capture=5.0))
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        hit = cs.calibration_for_time(V, 5.0)
        assert hit["ok"] is False and hit["reason"] == "segment_conflict", hit
    finally:
        tmp.cleanup()


def test_no_valid_time_is_unavailable():
    """没写适用时段 → 不可用（**不默认整段有效**）。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_E.mp4"
        cs.record_segment(V, _seg(2.0, None, None, capture=3.0))
        d = cs.calibration_for_time(V, 3.0)
        assert d["ok"] is False and d["reason"] == "no_segment_time", d
    finally:
        tmp.cleanup()


def test_cut_in_segment_is_unavailable():
    """③ 切镜不沿用旧标定：时段里探到切镜 → 不可用；**探测失败 → 报"未知"也不是"没切镜"**。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_F.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 30.0, capture=2.0))
        real = cs.probe_cuts
        try:
            cs.probe_cuts = lambda video, t0, t1, probes=6: {"ok": True, "parts": [[0.0, 29.0]],
                                                             "note": "1 段"}
            assert cs.calibration_for_time(V, 12.0, check_cut=True)["ok"] is True
            cs.probe_cuts = lambda video, t0, t1, probes=6: {"ok": True,
                                                             "parts": [[0.0, 5.0], [6.0, 29.0]],
                                                             "note": "2 段"}
            d = cs.calibration_for_time(V, 12.0, check_cut=True)
            assert d["ok"] is False and d["reason"] == "cut_in_segment", d
            cs.probe_cuts = lambda video, t0, t1, probes=6: {"ok": False, "parts": [[0.0, 29.0]],
                                                             "note": "视频不可读"}
            u = cs.calibration_for_time(V, 12.0, check_cut=True)
            assert u["ok"] is False and u["reason"] == "cut_unknown", u
        finally:
            cs.probe_cuts = real
    finally:
        tmp.cleanup()


def test_reference_frame_is_the_matrix_frame_not_average():
    """参考帧 = 矩阵所属的那一帧，**不是**参与解算那几帧时间的平均。"""
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_G.mp4"
        seg = _seg(2.0, 0.0, 20.0, capture=3.0, ref=3.0,
                   sources=[{"t": 1.0, "n": 4, "landmarks": {}}, {"t": 6.0, "n": 4, "landmarks": {}}])
        cs.record_segment(V, seg)
        d = cs.calibration_for_time(V, 5.0)
        assert d["segment"]["reference_frame"] == 3.0, d["segment"]
        assert d["segment"]["capture_time_s"] == 3.0
        assert d["segment"]["reference_frame"] != (1.0 + 6.0) / 2.0
        assert len(d["segment"]["source_frames"]) == 2
        assert d["segment"]["verification"]["rmse_m"] == 0.2
    finally:
        tmp.cleanup()


def test_revision_conflict_is_rejected():
    tmp = _with_temp_data()
    try:
        V = "/tmp/fake_video_H.mp4"
        cs.record_segment(V, _seg(2.0, 0.0, 5.0, capture=2.0))
        try:
            cs.record_segment(V, _seg(5.0, 5.0, 10.0, capture=6.0), revision=0)
            raise AssertionError("旧 revision 必须被拒")
        except ValueError as e:
            assert "revision" in str(e), e
    finally:
        tmp.cleanup()


def test_no_calibration_returns_unavailable():
    tmp = _with_temp_data()
    try:
        d = cs.calibration_for_time("/tmp/fake_video_I.mp4", 1.0)
        assert d["ok"] is False and d["reason"] == "no_calibration", d
    finally:
        tmp.cleanup()
