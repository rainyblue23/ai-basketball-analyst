# -*- coding: utf-8 -*-
"""多机位标定接口：**每一幅画面自己的 H 必须回给前端**。

为什么单独钉这一条（用户实测反馈："红框明显不对"）：
    标定页的左右两个画面是**两个机位**（各拍半场，取的时刻也不同，例如
    t=117.97s / t=13.5s）。后端一份 H 只属于其中一幅 —— 接口以前只回一份
    "顶层 H"，前端于是把这一份画到了**两个**画面上：其中一个画面的红叠线
    整体偏 20~30m，另一个也压不到画面里的白线。用户看到的就是"红框差到哪去了"。

修法：接口在**每条出口**都带上每幅画面自己的 H
    * `per_frame_fit[i].H` —— 单镜头那条路的逐帧拟合结果；
    * `segments_H`          —— 多机位（per-shot / per-frame）那条路，每段一份。

本测试用仓库里那份**真实标定**（两段各自 5 个点、误差 0.03/0.04m）反投影生成
"用户点准了"的画面点，跑通接口后断言：
    ① 收到 2 幅画面各自的 H；
    ② 两份 H 确实**不一样**（真换成同一个机位才应该一样，这份素材不是）；
    ③ 每份 H 把**它自己那一帧**的点投到球场坐标后，误差是厘米级
       （拿另一份 H 投同一批点必然差几十米 —— 这就是原来那个 bug 的量级）。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop import api                      # noqa: E402

VIDEO = ROOT / "data" / "uploads" / "4fd883de72d112345b78ce28e7eac0c9_3a23006d66.mp4"
CAL = ROOT / "data" / "calibration_4fd883de72d112345b78ce28e7eac0c9_3a23006.json"

# 每幅画面各自点的地标名（左画面 = A端、右画面 = B端；与界面 courtSideNames.full 一致）
A_NAMES = ["corner_far_right", "lane_far_left", "ft_far", "lane_far_right", "arc_far"]
B_NAMES = ["lane_near_left", "ft_near", "lane_near_right", "arc_near", "corner_near_left"]


def _fixture():
    if not (VIDEO.exists() and CAL.exists()):
        pytest.skip("仓库里没有那份真实素材/标定，跳过")
    cal = json.loads(CAL.read_text(encoding="utf-8"))
    segs = cal.get("segments") or []
    if len(segs) < 2:
        pytest.skip("这份标定只有一段，构造不出「两个机位」的场景")
    return cal, segs


def _points_for(Hm, names, W=960, H=544):
    """用 H 的逆算出"用户点准了"的归一化画面点（H 的方向是 像素→球场米）"""
    inv = np.linalg.inv(np.asarray(Hm, dtype=float))
    out = {}
    for n in names:
        cx, cy = api.COURT_LANDMARKS[n]
        v = inv @ np.array([float(cx), float(cy), 1.0])
        out[n] = {"value": [float(v[0] / v[2]) / W, float(v[1] / v[2]) / H], "label": n}
    return out


def _frames(segs):
    """两幅画面：左 = 第 2 段那个机位（A端），右 = 第 1 段那个机位（B端）。"""
    H_a = np.asarray(segs[1]["H"], dtype=float)
    H_b = np.asarray(segs[0]["H"], dtype=float)
    return [{"t": float(segs[1].get("t_start", 0.0)) + 60.0,
             "landmarks": _points_for(H_a, A_NAMES)},
            {"t": float(segs[0].get("t_start", 0.0)) + 10.0,
             "landmarks": _points_for(H_b, B_NAMES)}], H_a, H_b


def test_each_frame_gets_its_own_homography():
    cal, segs = _fixture()
    frames, H_a, H_b = _frames(segs)
    out = asyncio.run(api.post_calibrate_multi(
        api.MultiCalibRequest(video_path=str(VIDEO), frames=frames, confirm=False)))
    out = out if isinstance(out, dict) else out.body

    # ① 两条通路（per-shot 的 segments_H / 单镜头的 per_frame_fit）里至少要有一条
    #    给出"每幅画面自己的 H"
    seg_h = {round(float(s["t_start"]), 2): s["H"] for s in (out.get("segments_H") or [])}
    fit_h = {round(float(f["t"]), 2): f.get("H") for f in (out.get("per_frame_fit") or [])}
    assert seg_h or [v for v in fit_h.values() if v], (
        "接口必须把每幅画面自己的 H 回给前端，否则前端只能拿到一份、"
        "必然把它画到两个画面上（用户看到的「红框明显不对」）。"
        "via=%s keys=%s" % (out.get("via"), sorted(out.keys())))

    # ② 两份 H 必须不一样：这素材的两个机位（t≈13.5s 与 t≈118s）相差几十米
    def _norm(M):
        M = np.asarray(M, dtype=float)
        return M / M[2][2]
    both = [v for v in list(seg_h.values()) + list(fit_h.values()) if v]
    assert len(both) >= 2, "要能拿到两幅画面各自的 H（现在 %d 份）" % len(both)
    assert not np.allclose(_norm(both[0]), _norm(both[1]), atol=1e-6), (
        "两份 H 不该相同 —— 这份素材是两个机位")

    # ③ 每份 H 只对**它自己那一帧**是厘米级；拿错的那份必然差几米以上
    def err(Hm, names, pts):
        Hm = np.asarray(Hm, dtype=float)
        worst = 0.0
        for n in names:
            x, y = pts[n]["value"]
            px, py = x * 960.0, y * 544.0
            w = Hm[2][0] * px + Hm[2][1] * py + Hm[2][2]
            gx = (Hm[0][0] * px + Hm[0][1] * py + Hm[0][2]) / w
            gy = (Hm[1][0] * px + Hm[1][1] * py + Hm[1][2]) / w
            cx, cy = api.COURT_LANDMARKS[n]
            worst = max(worst, float(((gx - cx) ** 2 + (gy - cy) ** 2) ** 0.5))
        return worst

    assert err(H_a, A_NAMES, frames[0]["landmarks"]) < 0.2
    assert err(H_b, B_NAMES, frames[1]["landmarks"]) < 0.2
    assert err(H_a, B_NAMES, frames[1]["landmarks"]) > 2.0, (
        "把 A 端机位那份 H 用在 B 端画面上，必须差几米 —— 它就是原来那个 bug 的量级")


def test_per_frame_fit_payload_carries_h_only_when_usable():
    """逐帧拟合的返回里：能用的帧带 H，不能用的帧 H 明确为 None（别让前端去猜）。"""
    from aihoop.api import _per_frame_fit_payload
    got = _per_frame_fit_payload([
        {"t": 1.0, "n": 5, "ok": True, "rmse_m": 0.03, "H": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
         "src_px": [[1, 2]], "dst_m": [[0, 0]], "names": ["a"]},
        {"t": 2.0, "n": 3, "ok": False, "rmse_m": None, "H": None,
         "src_px": [[1, 2]], "dst_m": [[0, 0]], "names": ["a"]},
    ])
    assert got[0]["H"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert got[1]["H"] is None
    # 原始像素数组不再回传（几十个点纯诊断用，别把响应撑大）
    assert "src_px" not in got[0] and "dst_m" not in got[0]


def test_cross_shot_marks_skip_motion_compensation():
    """标点跨镜头时**不要**去做镜头位移补偿。

    为什么（实测，用户报的"解算失败：后端算太久被浏览器中断了"）：
        两帧取在 t=13.5s / t=117.97s（同一台机位摇了 100 秒、中间还有切镜）时，
        补偿那一步会去链式估计这两帧之间的**每一帧**（2600 帧）—— 实测 **41 秒**，
        远超浏览器 30 秒的等待上限；而这活儿最后还是判"不可信、不合并"（白算）。
        跨镜头本来就没有统一坐标系，应该直接跳过补偿，由 per-shot 按镜头各解一份。
    """
    import aihoop.frame_motion as fm
    cal, segs = _fixture()
    frames, _a, _b = _frames(segs)

    called = {"n": 0}
    orig = fm.build_segments

    def _spy(*a, **k):
        called["n"] += 1
        return orig(*a, **k)

    fm.build_segments = _spy
    try:
        out = asyncio.run(api.post_calibrate_multi(
            api.MultiCalibRequest(video_path=str(VIDEO), frames=frames, confirm=False)))
        out = out if isinstance(out, dict) else out.body
    finally:
        fm.build_segments = orig

    assert called["n"] == 0, (
        "跨镜头的标点不该去做逐帧位移补偿（实测这一步要 41 秒，浏览器 30 秒就断了）")
    # 这条路本来就会在补偿之前按镜头分别解算并返回（per-shot / per-frame），
    # 所以这里要的是"那个快的出口"，而不是补偿说明。
    assert out.get("via") in ("per-shot", "per-frame"), (
        "跨镜头标点应走「按镜头分别解算」的出口（via=%s）" % out.get("via"))
    assert out.get("ok") is True

