# -*- coding: utf-8 -*-
"""标定落盘验收（2026-10-05 收紧后的口径）—— 只验收这三项，不扩大范围。

验收口径（用户转述的评审意见，已确认）：
  1) **原始点逐点符合"实际发送的归一化值 × 后端宽高"**。
     基准里已经包含请求本身的舍入，所以**允许误差只算保存时的舍入**：
     像素四舍五入到两位小数 → 每个坐标 ≤ 0.005px + 浮点余量。
     不得把"请求精度"再算进允许误差（那是重复放宽）。
     `request_decimals` 可以记录，但**不得假定请求只有六位小数**，核对以实际发送值为准。
  2) **平移、透视两例的补偿点符合实际矩阵计算**（`points_warped_px` ≡ 矩阵作用在原始点上）。
  3) **"未启用"与"执行失败"两条路径都保留原始记录，并准确说明补偿状态**。
     失败帧不得留下上一帧的补偿点 / 变换矩阵 / 成功状态；部分成功要**逐帧**记录。

说明：四阶段快照比较的是"原始记录是否保持不变"，所以第 1 条用的是**原始**字段；
补偿后的派生坐标本来就该变，单独按第 2 条与矩阵计算结果比。

跑法：python tests/test_calibrate_write_acceptance.py
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop import api                      # noqa: E402

WORK = ROOT / "_tmp" / "pytest_calib_write"
# 每个坐标只允许"保存时的两位小数舍入"，再给一点浮点余量。
# **不含**请求精度 —— 请求值就是基准本身。
PIXEL_TOL = 0.005 + 1e-6

# 5 个真实场地特征点（不共线、铺得开），归一化坐标**故意多给小数位**，
# 用来验证"不得假定请求只有六位小数"。
from aihoop.court import find_homography
_fixture_H = np.asarray(find_homography(
    [[80,420],[560,420],[520,80],[120,80]],
    [[-7.5,14],[7.5,14],[7.5,0],[-7.5,0]]))
_fixture_inverse = np.linalg.inv(_fixture_H)
NORM = {}
for name in ['corner_far_left','corner_far_right','paint_base_far_left',
             'paint_base_far_right','lane_far_left','lane_far_right','arc_far']:
    x,y=api.COURT_LANDMARKS[name]
    q=_fixture_inverse @ np.array([x,y,1.])
    NORM[name]=[float(q[0]/q[2]/640),float(q[1]/q[2]/480)]



def _video() -> Path:
    p = WORK / "tiny.mp4"
    if p.exists() and p.stat().st_size > 0:
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    from aihoop.highlight import ffmpeg_path
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("本机没有 ffmpeg")
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=640x480:rate=10", "-t", "1",
                    "-pix_fmt", "yuv420p", "-y", str(p)], check=False)
    return p


def _run(body: dict) -> tuple[dict, dict]:
    """跑一次保存并读回落盘 JSON（落盘路径重定向到测试目录，不碰真实 data/）。"""
    out_box = WORK / "calib"
    if out_box.exists():
        for f in out_box.glob("*.json"):
            f.unlink()
    out_box.mkdir(parents=True, exist_ok=True)
    old = api._calibration_path_for
    api._calibration_path_for = lambda v: out_box / (Path(v).stem + ".json")
    # ⚠️ `post_calibrate_multi` 保存时还会调 `calib_segments.record_segment()`，
    # 那条路用的是**它自己模块的** `calibration_path()`，不看 `api._calibration_path_for`
    # —— 不一起重定向的话，本文件每跑一次都往真实 data/ 追加一条 segment
    # （实测：`data/calibration_tiny.json` 已经被累积到 59 段）。所以两处都要打。
    from aihoop import calib_segments
    old_ov = getattr(calib_segments, "_PATH_OVERRIDE", None)
    calib_segments.set_path_override(lambda v: out_box / (Path(v).stem + ".json"))
    from aihoop import calibcheck
    old_quality = calibcheck.court_fit_score
    old_split = api._split_marks_by_shot
    calibcheck.court_fit_score = lambda *_a, **_k: {'ok':True, 'ratio':2.0}
    api._split_marks_by_shot = lambda _v, times: ([times], [])
    try:
        out = asyncio.run(api.post_calibrate_multi(api.MultiCalibRequest(**body)))
    finally:
        calibcheck.court_fit_score = old_quality
        api._split_marks_by_shot = old_split
        api._calibration_path_for = old
        calib_segments.set_path_override(old_ov)
    saved = json.loads(Path(out["path"]).read_text(encoding="utf-8")) if out.get("path") else {}
    return out, saved


def _frames(ts=(0.30, 0.70)) -> list:
    return [{"t": t, "landmarks": dict(NORM)} for t in ts]


def _body(compensate: bool, ts=(0.30, 0.70)) -> dict:
    return {"video_path": str(_video()), "compensate": compensate, "confirm": True, "snap": False,
            "frames": _frames(ts)}


def _segments(ts, matrices: dict) -> dict:
    """构造 build_segments 的返回值：{segments:[{times, ref_t, to_ref}]}"""
    return {"segments": [{"times": list(ts), "ref_t": ts[0],
                          "to_ref": {t: matrices[t] for t in ts if t in matrices}}]}


class _Patch:
    """临时替换 aihoop.frame_motion.build_segments（端点内部是按调用时导入的）。"""

    def __init__(self, fn):
        self.fn = fn

    def __enter__(self):
        from aihoop import frame_motion
        self.old = frame_motion.build_segments
        frame_motion.build_segments = self.fn
        return self

    def __exit__(self, *a):
        from aihoop import frame_motion
        frame_motion.build_segments = self.old
        return False


def _check_raw(saved: dict, sent: dict, wh) -> float:
    """第 1 条：原始点逐点 == sent_norm × (W,H)，误差 ≤ PIXEL_TOL。返回最大误差。"""
    W, H = wh
    worst = 0.0
    assert saved.get("source_frames"), "没有 source_frames 记录"
    for fr in saved["source_frames"]:
        for name, px in fr["points_px"].items():
            want = [sent[name][0] * W, sent[name][1] * H]
            for got, exp in zip(px, want):
                worst = max(worst, abs(float(got) - exp))
    assert worst <= PIXEL_TOL, (
        "原始点与『请求归一化值×后端宽高』不一致：最大误差 %.6f px > %.6f px" % (worst, PIXEL_TOL))
    return worst


# ---------------------------------------------------------------- 第 1 条
def test_1_raw_points_match_request_times_frame_size():
    """原始点逐点符合请求换算值；误差只允许"保存时的两位小数舍入"。"""
    out, saved = _run(_body(compensate=False))
    assert out.get("saved") is True and saved, "没保存成功"
    W, H = saved["frame_size"]
    worst = _check_raw(saved, NORM, (W, H))
    print("\n[1] 原始点最大误差 = %.6f px（预算 %.6f px，画面 %dx%d）" % (worst, PIXEL_TOL, W, H))
    # 负向对照：把期望值人为挪动 0.02px，就必须判失败 —— 证明这条断言是"锋利"的
    perturbed = {k: [v[0], v[1]] for k, v in NORM.items()}
    fr = saved["source_frames"][0]
    name = next(iter(fr["points_px"]))
    px = fr["points_px"][name]
    assert abs((px[0] + 0.02) - NORM[name][0] * W) > PIXEL_TOL, "断言太松（0.02px 的偏差竟然也能通过）"


def test_1b_budget_has_no_request_precision_term():
    """允许误差只含"保存时的两位小数舍入"，**不含请求精度**。

    做法：基准用**实际发送的**归一化值（16 位小数）× 后端宽高，误差必须 ≤ 0.005px + 浮点余量。
    再把基准换成"把请求值四舍五入到 4 位小数"的版本 —— 那样误差会明显超过预算，
    说明这条断言是锋利的，而且证明预算里没有偷偷加"请求精度"这一项。
    """
    out, saved = _run(_body(compensate=False))
    W, H = saved["frame_size"]
    worst_sent = _check_raw(saved, NORM, (W, H))

    # 若把请求值先四舍五入到 4 位小数当基准（错误做法），误差会超出预算
    coarse = {k: [round(v[0], 4), round(v[1], 4)] for k, v in NORM.items()}
    worst_coarse = 0.0
    for fr in saved["source_frames"]:
        for name, px in fr["points_px"].items():
            for got, exp in zip(px, [coarse[name][0] * W, coarse[name][1] * H]):
                worst_coarse = max(worst_coarse, abs(float(got) - exp))
    print("[1b] 以实际发送值为基准：%.6f px（预算 %.6f）；以 4 位小数的请求值为基准：%.6f px"
          % (worst_sent, PIXEL_TOL, worst_coarse))
    assert worst_sent <= PIXEL_TOL
    assert worst_coarse > PIXEL_TOL, "把请求值粗化到 4 位小数竟然也落进预算 —— 预算太松了"


# ---------------------------------------------------------------- 第 2 条
def _warp_expect(Hm: np.ndarray, wh) -> dict:
    """按**实际发送的**归一化值重建原始像素点，再算矩阵作用后的结果。

    注意两点（都是这次验收的要求）：
      * 基准是「实际发送的归一化值 × 后端宽高」，所以这里用 NORM 的**完整精度**，
        不用落盘里那份已四舍五入到两位小数的 points_px（那样会把输入舍入再放大一次）；
      * 允许误差只含**保存时的输出舍入**（0.005px）。
    """
    W, H = wh
    out = {}
    for name, (nx, ny) in NORM.items():
        v = Hm @ np.array([nx * W, ny * H, 1.0])
        out[name] = (v[0] / v[2], v[1] / v[2])
    return out


def _check_warp(saved: dict, Hm: np.ndarray, label: str) -> tuple[int, float]:
    W, H = saved["frame_size"]
    want = _warp_expect(Hm, (W, H))
    worst, checked = 0.0, 0
    for fr in saved["source_frames"]:
        for name, wpx in (fr.get("points_warped_px") or {}).items():
            assert name in want, "冒出了没发过的点名：%s" % name
            for got, exp in zip(wpx, want[name]):
                worst = max(worst, abs(float(got) - float(exp)))
            checked += 1
    assert checked, "%s：没有任何补偿点被记录" % label
    print("[%s] %d 个补偿点，最大误差 %.6f px（预算 %.6f）" % (label, checked, worst, PIXEL_TOL))
    assert worst <= PIXEL_TOL, "%s：补偿点与矩阵计算不一致，最大 %.6f px" % (label, worst)
    return checked, worst


def test_2_translation_compensation_matches_matrix():
    """平移例：补偿点 == 矩阵作用在原始点上。"""
    ts = (0.30, 0.70)
    Htrans = np.array([[1.0, 0.0, 12.5], [0.0, 1.0, -7.25], [0.0, 0.0, 1.0]])
    with _Patch(lambda vp, times: _segments(ts, {ts[0]: Htrans.tolist(), ts[1]: Htrans.tolist()})):
        out, saved = _run(_body(compensate=True, ts=ts))
    assert out.get("saved") is True
    _check_warp(saved, Htrans, "2a 平移")


def test_2b_perspective_compensation_matches_matrix():
    """透视例：补偿点 == 透视矩阵作用在原始点上。"""
    ts = (0.30, 0.70)
    Hpersp = np.array([[1.06, 0.21, -18.0], [-0.13, 0.94, 9.5], [0.00042, -0.00031, 1.0]])
    with _Patch(lambda vp, times: _segments(ts, {ts[0]: Hpersp.tolist(), ts[1]: Hpersp.tolist()})):
        out, saved = _run(_body(compensate=True, ts=ts))
    assert out.get("saved") is True
    _check_warp(saved, Hpersp, "2b 透视")


# ---------------------------------------------------------------- 第 3 条
def test_3a_compensation_not_enabled_keeps_raw_and_says_so():
    out, saved = _run(_body(compensate=False))
    W, H = saved["frame_size"]
    worst = _check_raw(saved, NORM, (W, H))          # 原始记录一字不变
    assert saved.get("compensate_status") == "not_enabled", \
        "整批状态没写成 not_enabled：%r" % saved.get("compensate_status")
    for fr in saved["source_frames"]:
        assert not fr["points_warped_px"], "未启用补偿却出现了补偿点"
        assert fr["warped_to"] is None
        assert fr["warp_status"] == "not_enabled", "逐帧状态不对：%r" % fr["warp_status"]
        assert "未启用" in (fr["warp_reason"] or ""), "说明里没讲清是未启用：%r" % fr["warp_reason"]
    print("[3a] 未启用：原始点最大误差 %.6f px；状态 %s / %r"
          % (worst, saved["source_frames"][0]["warp_status"],
             saved["source_frames"][0]["warp_reason"]))


def test_3b_compensation_failure_keeps_raw_and_states_failure():
    ts = (0.30, 0.70)

    def boom(vp, times):
        raise RuntimeError("合成失败：模拟镜头位移补偿异常")

    with _Patch(boom):
        out, saved = _run(_body(compensate=True, ts=ts))
    W, H = saved["frame_size"]
    worst = _check_raw(saved, NORM, (W, H))          # 原始记录一字不变
    assert saved.get("compensate_status") == "failed", \
        "整批状态没写成 failed：%r" % saved.get("compensate_status")
    for fr in saved["source_frames"]:
        assert not fr["points_warped_px"], "补偿失败却留下了补偿点"
        assert fr["warped_to"] is None, "补偿失败却留下了参考帧（等价于成功状态）"
        assert fr["warp_status"] == "failed", "逐帧状态不对：%r" % fr["warp_status"]
        assert "失败" in (fr["warp_reason"] or ""), \
            "补偿失败被写成了『未做补偿』，两条路径分不开：%r" % fr["warp_reason"]
        assert "RuntimeError" in fr["warp_reason"], "失败原因没写进逐帧说明"
    # 顶层的整体说明里也要带上失败原因
    assert "RuntimeError" in (saved.get("compensate_note") or ""), "compensate_note 没带失败原因"
    print("[3b] 失败：原始点最大误差 %.6f px；状态 %s / %r"
          % (worst, saved["source_frames"][0]["warp_status"],
             saved["source_frames"][0]["warp_reason"][:60]))


def test_3c_partial_success_is_recorded_per_frame():
    """只做成一帧（两帧分属不同镜头）：成功帧记补偿点，另一帧保留原始点 + 自己的状态。

    这是真实存在的路径：`build_segments` 会按镜头切段，只有点数最多的那一段参与解算，
    另一段的两帧**不该从记录里消失**，也不该继承前者的补偿点/参考帧。
    """
    ts = (0.30, 0.70)
    Hpersp = np.array([[1.02, 0.05, 4.0], [-0.02, 0.99, -3.0], [0.0001, -0.0002, 1.0]])
    segs = {"segments": [
        {"times": [ts[0]], "ref_t": ts[0], "to_ref": {ts[0]: Hpersp.tolist()}},
        {"times": [ts[1]], "ref_t": ts[1], "to_ref": {ts[1]: Hpersp.tolist()}},
    ]}
    with _Patch(lambda vp, times: segs):
        out, saved = _run(_body(compensate=True, ts=ts))
    W, H = saved["frame_size"]
    _check_raw(saved, NORM, (W, H))                  # 两帧的原始点都还在
    fr = {round(float(f["t"]), 2): f for f in saved["source_frames"]}
    assert set(fr) == {0.30, 0.70}, "收到的两帧都必须在记录里，实际：%s" % sorted(fr)
    ok, bad = fr[0.30], fr[0.70]
    print("[3c] 部分成功：t=0.30 状态 %s（补偿点 %d 个）；t=0.70 状态 %s（补偿点 %d 个）"
          % (ok["warp_status"], len(ok.get("points_warped_px") or {}),
             bad["warp_status"], len(bad.get("points_warped_px") or {})))
    # 成功的那一帧：补偿点必须等于矩阵计算结果
    _check_warp({"frame_size": [W, H], "source_frames": [ok]}, Hpersp, "3c 成功帧")
    assert ok["warp_status"] == "done" and ok["warped_to"] is not None
    assert ok["used_for_solve"] is True
    # 没做成的那一帧：不许继承任何东西，且要有自己的说明
    assert not (bad.get("points_warped_px") or {}), "失败帧继承了上一帧的补偿点"
    assert bad["warped_to"] is None, "失败帧继承了参考帧（等价于成功状态）"
    assert bad["warp_status"] == "other_segment", "逐帧状态不对：%r" % bad["warp_status"]
    assert bad["warp_reason"], "失败帧没有各自的说明"
    assert bad["used_for_solve"] is False
    assert (bad["points_px"]), "失败帧的原始点被抹掉了"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for t in tests:
        try:
            t()
            print("PASS %s" % t.__name__)
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print("FAIL %s → %s" % (t.__name__, e))
        except Exception as e:  # noqa: BLE001
            failed.append((t.__name__, "%s: %s" % (type(e).__name__, e)))
            print("ERROR %s → %s: %s" % (t.__name__, type(e).__name__, e))
    print("\n=== 验收：%d 项，PASS %d / FAIL %d ===" % (len(tests), len(tests) - len(failed), len(failed)))
    for n, m in failed:
        print("  - %s: %s" % (n, m))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
