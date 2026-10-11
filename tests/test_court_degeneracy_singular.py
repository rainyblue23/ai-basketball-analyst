# -*- coding: utf-8 -*-
"""数值奇异的标定必须被判退化（用户实测：一份这样的标定让 694 个观测删掉 688 个）。

现场（固定机位户外半场 960×540）：
    用户标的 4 个点里 **3 个都落在同一条线 y=-8.2 上**，只铺开近端一小块：
        [(-7.5,-14), (0,-8.2), (-2.45,-8.2), (2.45,-8.2)]
    解出来的 H：**行列式 1.2e-20、条件数 3.5e17（等于不可逆）**，
    把整块球场压成**一个像素**（四角全投到 (463,408)）。
    而那 4 个标定点自己重投影误差是 0 —— 所以"误差小"完全没暴露它。

`calibration_degeneracy` 原来只看**最大**三角形面积（14.2m² > 阈值）→ 放行。
现在补一条与点位无关的直接判据：**把球场四角投回画面看它还在不在**
（条件数过大 / 四角挤成一点 / 投出的四边形面积过小 → 判退化）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop.court import (Calibration, calibrate_from_corners,      # noqa: E402
                          calibration_degeneracy, find_homography)

# 现场那份坏标定（点与 H 都照抄实测）
BAD_SRC = [[462.7, 407.8], [246.4, 505.9], [194.7, 462.1], [950.6, 470.8]]
BAD_DST = [[-7.5, -14.0], [0.0, -8.2], [-2.45, -8.2], [2.45, -8.2]]
BAD_H = [[-0.000971493567396415, -0.0021424902780973493, 1.3231557668668397],
         [0.0018504292216788942, 0.018009851148248875, -8.2],
         [-0.0002256621002047428, -0.0021963233107620468, 1.0]]


def test_numerically_singular_calibration_is_rejected():
    """球场被压成一个点的标定，必须判退化并说清原因。"""
    cal = Calibration(name="bad", method="web-keypoints-multi",
                      src_px=BAD_SRC, dst_m=BAD_DST, H=BAD_H,
                      frame="full", frame_size=[960, 540])
    r = calibration_degeneracy(cal)
    assert r["degenerate"] is True, (
        "这份标定把整块球场压成一个像素，必须拦下来（实测它让 694 个观测删掉 688 个）")
    # 读数要留着，方便界面/报告说清"为什么不能用"
    assert r.get("H_cond") and r["H_cond"] > 1e8, r
    assert "奇异" in r["reason"] or "同一条线" in r["reason"], r["reason"]

    # 反证：这份 H 连自己那 4 个点都投不准（文件里 `reproj_error_m = 3.971` 就是这个），
    # 而且第一个点的齐次分母只有 7e-5 量级 —— 数值上完全不可用。
    # 所以"看误差数字"这条路在这里没有用，才需要上面那条几何/条件数判据。
    ws, errs = [], []
    for (x, y), (mx, my) in zip(BAD_SRC, BAD_DST):
        w = BAD_H[2][0] * x + BAD_H[2][1] * y + BAD_H[2][2]
        ws.append(abs(w))
        if abs(w) > 1e-12:
            gx = (BAD_H[0][0] * x + BAD_H[0][1] * y + BAD_H[0][2]) / w
            gy = (BAD_H[1][0] * x + BAD_H[1][1] * y + BAD_H[1][2]) / w
            errs.append(((gx - mx) ** 2 + (gy - my) ** 2) ** 0.5)
    assert min(ws) < 1e-3, "至少有一个点的齐次分母应该小到不可用：%s" % ws
    assert max(errs) > 1.0, "这份 H 对自己的标定点就投不准：%s" % errs


def test_good_calibrations_are_not_flagged():
    """正常标定不能被这条新判据误伤（全场 / 半场都要过）。"""
    for half in (False, True):
        cal = calibrate_from_corners([[120, 430], [860, 470], [880, 140], [90, 120]],
                                     half_court=half)
        r = calibration_degeneracy(cal)
        assert r["degenerate"] is False, (half, r)
        assert r.get("H_cond") is None or r["H_cond"] < 1e8, r
        assert (r.get("quad_area_px2") or 0) > 0


def test_collinear_court_points_are_rejected_even_if_images_are_spread():
    """球场侧 3 点共线 + 画面侧铺得开 → 解出的 H 条件数爆炸，必须被拦。

    这条是上面那份坏标定的"最小复现"：不依赖实测数据。
    """
    src = [[100, 400], [860, 400], [300, 200], [700, 200]]     # 画面侧铺得很开
    dst = [[-7.5, -8.2], [7.5, -8.2], [-2.45, -8.2], [2.45, -8.2]]  # 球场侧全在一条线
    try:
        Hm = find_homography(src, dst)
    except Exception:                                            # noqa: BLE001
        return                      # 求解阶段就拒绝，也算通过
    cal = Calibration(name="collinear", method="x", src_px=src, dst_m=dst,
                      H=Hm, frame="half", frame_size=[960, 540])
    r = calibration_degeneracy(cal)
    assert r["degenerate"] is True, (
        "球场侧的点全在同一条线上，必须判退化：%s" % r)
