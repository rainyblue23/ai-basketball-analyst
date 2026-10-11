# -*- coding: utf-8 -*-
"""人数异常时，战术层必须**明说不可用**，不能给一张空球场。

用户实测（截图）：战术图画布上一个人都没有，只有一句很小的"本时刻人数异常"，
看起来就是"这功能坏了"。根因：球员轨迹里混进观众/替补（球场标定不可信、
无法按场内判定剔除）→ 每帧人数超过"每队 5 人"的硬上限 → 帧级判据整帧丢弃
（实测 481 帧里 251 帧是空的）→ 战术图空场。

本测试钉住三件事：
  ① 滑窗标定的四角如果几何上不像球场，必须被判不可用（`_plausible_quad`）——
     它的"质量分"只反映线压到亮脊上，实测 median_ratio 10.88 却把四角算进看台；
  ② 这种锚点不能被 `corners_at` 拿去做场内判定；
  ③ 空帧占比过高时，战术层降级为 available=False 并给出原因。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop.calibcheck import _plausible_quad, corners_at            # noqa: E402

# 实测那组歪的四角（用户这条素材，960×544）
BAD_QUAD = [[344, 112], [913, 292], [1081, 345], [301, 545]]
# 一组"像球场"的四角
GOOD_QUAD = [[100, 400], [860, 420], [820, 120], [140, 110]]


def test_implausible_quad_is_rejected():
    assert _plausible_quad(BAD_QUAD) is False, (
        "跨了整个画面、还插进看台的四角必须判为「不像球场」 —— "
        "实测就是它让下游只剩 0.41 人/帧、战术图空场")
    assert _plausible_quad(GOOD_QUAD) is True
    # 退化（共线）也必须拒
    assert _plausible_quad([[0, 0], [100, 0], [200, 0], [300, 0]]) is False
    # 自交的四边形（顺序拧了）也必须拒
    assert _plausible_quad([[0, 0], [100, 0], [0, 100], [100, 100]]) is False


def test_geom_ok_anchor_is_not_used_for_on_court_decisions():
    """geom_ok=False 的锚点不能拿来投影（否则就是拿歪标定删球员）。"""
    sliding = {"stride": 5, "total_frames": 30, "half_court": True,
               "anchors": [{"frame": 0, "corners": BAD_QUAD, "ratio": 10.88,
                            "kind": "reuse", "geom_ok": False},
                           {"frame": 10, "corners": BAD_QUAD, "ratio": 10.9,
                            "kind": "reuse", "geom_ok": False}]}
    for t in (0, 5, 10, 20):
        assert corners_at(sliding, t) is None, (
            "歪的四角一律不参与判定（frame=%d）" % t)
    # 老数据/直接构造的结构没有 geom_ok 字段 → 按可用处理（不能一缺字段就全废）
    old = {"stride": 5, "total_frames": 30,
           "anchors": [{"frame": 0, "corners": GOOD_QUAD}]}
    assert corners_at(old, 0) == GOOD_QUAD


def test_pipeline_degrades_instead_of_drawing_an_empty_court(tmp_path=None):
    """空帧占比过高 → available=False + 说明原因（而不是渲染空球场）。

    造一份坐标**物理上说得通**（能过 `_tactics_coords_sane`）但每队人数超上限的轨迹：
    每帧 7 个人、6 个判给同一队 → 帧级判据把这些帧全部丢掉。
    """
    from aihoop.pipeline import PipelineConfig, run_pipeline
    from aihoop.sources import PlayerSample, RawTrack

    rt = RawTrack(fps=25.0, duration=60.0, video_path="x.mp4", width=960, height=544)
    rt.detections_meta.update({"calibration_valid": False,
                               "calibration_position_unverified": True})
    # 坐标铺得开（通过物理合理性检查），但每队人数超上限
    t = 0.0
    while t <= 60.0:
        for i in range(7):
            rt.player_track.append(PlayerSample(
                t=round(t, 3), player_id="T%d" % i,
                team="home" if i < 6 else "away",
                x=-6.5 + 13.0 * (i / 6.0),           # -6.5 ~ +6.5
                y=1.0 + 12.0 * ((i * 3) % 7) / 7.0,  # 1 ~ 13
                conf=1.0))
        t += 0.63
    for i in range(7):
        rt.players["T%d" % i] = type("P", (), {
            "player_id": "T%d" % i,
            "team": "home" if i < 6 else "away",
            "name": "号码待确认", "jersey": None})()
    out = ROOT / "_tmp" / "pytest_tactics_drop"
    out.mkdir(parents=True, exist_ok=True)
    # 前置：坐标必须先过物理合理性闸门，否则测的就不是"人数异常"这条路径了
    from aihoop.pipeline import _tactics_coords_sane
    ok, why = _tactics_coords_sane(rt.player_track)
    assert ok, "夹具本身没通过坐标合理性检查：%s" % why
    res = run_pipeline(rt, PipelineConfig(out_dir=str(out), make_highlights=False))
    tac = (res.game or {}).get("tactics") or {}
    meta = (res.game or {}).get("meta") or {}
    assert tac.get("available") is False, (
        "每帧人数异常时不能照常出战术图（用户看到的就是一张空球场）")
    assert "人数异常" in str(tac.get("reason") or ""), tac.get("reason")
    assert meta.get("tactics_frame_drop"), "要留下「有多少帧被丢」的读数"
    assert not (out / "tactics_frames.jsonl").exists() or \
        (out / "tactics_frames.jsonl").stat().st_size == 0, "不该再写出空帧文件"
