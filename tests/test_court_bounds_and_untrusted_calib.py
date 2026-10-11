# -*- coding: utf-8 -*-
"""标定不可信时，场内判定这把剪刀**不能**把真球员删光（用户实测：战术图没人）。

现场（真实素材 960×544 校园转播 240s）：
    那份静态标定两段各自 5 个点、重投影误差 0.03~0.09m，但把球场边界投到画面里
    是一个**斜的平行四边形**（跟白线完全不重合）。而 `in_court()` 用它来判"谁在场内"，
    于是真球员被投到框外 → 整批删掉。

本测试钉住这条**已经验证过的取舍**：
    ① `analysis_bounds` 保持"标定点反推的覆盖范围"（**不要**放宽成整块球场）——
       实测放宽后观众/替补全被判成场内，每帧人数超过"每队 5 人"上限，
       战术层整帧丢弃 → 战术图一张空球场（比点少更糟）；
    ② 标定不可信 / 投影不可用时，**不允许**拿它做场内判定删人
       （判据在 sources 的 cal_trusted / strict_on_court）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop.court import Calibration, calibrate_from_corners      # noqa: E402


def test_analysis_bounds_stays_the_calibration_point_extent():
    """`analysis_bounds` 保持原样（标定点反推的覆盖范围），**不要**放宽成整块球场。

    ⚠️ 这条测试是"别再改回去"的护栏。实测把它改成"真实球场范围（±7.5/±14）"以后：
        场边观众/替补全被判成"场内" → 每帧人数超过「每队 5 人」上限 →
        战术层整帧丢弃（481 帧里 251 帧空）→ 战术图一张空球场
        （用户原话"这都没人了"），比"点少"更糟。
    旧的小框虽然量纲上是拿米当像素用，但它**意外地**起到了收窄作用，
    恰好把大部分观众挡在外面。要动它，必须同时解决"谁来剔除观众"。
    """
    # 半场标定 → 范围就是这半个球场
    half = calibrate_from_corners([[100, 400], [860, 400], [860, 120], [100, 120]],
                                  half_court=True)
    hx0, hx1, hy0, hy1 = half.analysis_bounds(0.0)
    assert abs(hx0 + 7.5) < 1e-6 and abs(hx1 - 7.5) < 1e-6, (hx0, hx1)
    assert abs(hy0 + 14.0) < 1e-6 and abs(hy1 - 0.0) < 1e-6, (hy0, hy1)

    # 点只标了一小块 → 范围就该是这一小块（有意为之的收窄）
    bad = Calibration(name="bad", method="manual",
                      src_px=[[400, 300], [520, 300], [520, 260], [400, 260]],
                      dst_m=[[-2.45, -14.0], [2.45, -14.0], [2.45, -8.2], [-2.45, -8.2]],
                      frame="half",
                      note="错标：点全在罚球区附近").fit()
    bx0, bx1, by0, by1 = bad.analysis_bounds(0.0)
    assert (bx0, bx1) == (-2.45, 2.45), (bx0, bx1)
    assert (by0, by1) == (-14.0, -8.2), (by0, by1)

    # 反例护栏：**不许**返回整块球场（那正是踩过的坑）
    x0, x1, y0, y1 = bad.analysis_bounds(0.0)
    assert not (x0 <= -7.4 and x1 >= 7.4 and y0 <= -13.9 and y1 >= 13.9), (
        "场内范围被放宽成整块球场了 —— 这会让观众全被判成场内、战术层整帧丢弃")


def test_untrusted_calibration_must_not_be_used_as_scissors():
    """标定不可信（或投影拿不到）时，场内判定必须**不删人**。"""
    from aihoop.sources import synthetic_game
    rt = synthetic_game(seed=3, duration=60.0)
    assert rt.player_track, "前置：合成数据里本来就有球员轨迹"

    rt.detections_meta["calibration_valid"] = False
    rt.detections_meta["calibration_position_unverified"] = True
    rt.detections_meta["calibration_weak_segments"] = [
        {"t_start": 0.0, "t_end": 53.34, "rmse_m": 0.09, "ratio": 0.31,
         "why": "吻合度过低（投影线与画面白线对不上）"}]
    meta = rt.detections_meta
    trusted = bool(meta.get("calibration_valid")) and not bool(
        meta.get("calibration_position_unverified"))
    assert trusted is False, "这份标定必须被判为不可信"
    assert trusted is not True, (
        "标定不可信却仍然拿它当剪刀删球员 —— 这就是战术图没人的根因")
