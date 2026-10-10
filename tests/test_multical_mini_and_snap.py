"""「4 点自动定向」(mini) 与「点吸附到球场线」(snap) 两条新通道的端到端验收。

为什么用 FastAPI TestClient 打真实 HTTP，而不是直接调函数：
  mini 块有一条**硬性约束** —— 它必须放在 `len(src) < 4` 那个检查**之前**
  （mini 模式下用户根本不发命名地标，那时 src 是空的，先检查就会误报
  "至少要点 4 个场地特征点"）。直接调函数当然也能测出 ok=False，
  但走 HTTP 才能把"约束写错 = 直接 400"这件事一起钉死 —— 这正是不走
  HTTP 就看不出来的差别。

mini 用 **4 个未命名点**（只有 mini_frames，没有 landmarks）；
snap 用 **5 个有名字的点**，并额外验证"护栏拒绝时点集一个字都不许动"。
"""
from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop import api, calibcheck          # noqa: E402

TOKEN = "test-internal-token"


# ----------------------------------------------------------------- 夹具
def _work_dir() -> Path:
    """在**仓库内**建临时目录：pytest 的 tmp_path 落在 %TEMP%，
    本机受限环境连创建/清理都报 WinError 5（相邻测试已踩过）。"""
    d = ROOT / "_tmp" / "pytest_mini_snap"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_video(path: Path) -> bool:
    """便携版 ffmpeg 合成 1 秒 640x480 小视频；没有 ffmpeg 就跳过。"""
    if path.exists() and path.stat().st_size > 0:
        return True
    from aihoop.highlight import ffmpeg_path
    ff = ffmpeg_path()
    if not ff:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", "testsrc=size=640x480:rate=10", "-t", "1",
           "-pix_fmt", "yuv420p", "-y", str(path)]
    subprocess.run(cmd, check=False)
    return path.exists() and path.stat().st_size > 0


def _video() -> Path:
    v = _work_dir() / "mini_snap.mp4"
    if not _make_video(v):
        pytest.skip("本机没有 ffmpeg，跳过（跑 python tools_fetch_ffmpeg.py 可装）")
    return v


def _client(monkeypatch):
    """回环地址 + 内部令牌 = 本机豁免登录（与真实本机部署同一口径）。

    ⚠️ 令牌走 monkeypatch.setenv：runner 在**同一个进程**里跑完全部测试文件，
    直接改 os.environ 会把豁免留给后面的鉴权测试，那是污染，不是省事。
    """
    from fastapi.testclient import TestClient
    monkeypatch.setenv("AIHOOP_INTERNAL_TOKEN", TOKEN)
    c = TestClient(api.app, client=("127.0.0.1", 51234),
                   headers={"X-Internal-Token": TOKEN})
    assert c.get("/api/me").status_code == 200, "本机豁免没生效，后面的请求会全被 401 挡掉"
    return c


def _quad_px() -> list:
    """画面上的 4 个点（像素）。由一份单应矩阵**投影**出来，
    所以在几何上确实是某个球场四边形的像，不是随手写的四个点。"""
    return [[128.0, 345.6], [800.0, 340.0], [900.0, 120.0], [60.0, 150.0]]


def _quarter_px() -> list:
    """全场地四角（球场坐标）—— 上面那份投影用的就是它。"""
    return [[-7.5, 14.0], [7.5, 14.0], [7.5, -14.0], [-7.5, -14.0]]


def _mini_body(video: Path) -> dict:
    """mini 请求：**没有 landmarks**，只有一帧 4 个有序点（归一化）。"""
    pts = [[p[0] / 1280.0, p[1] / 720.0] for p in _quad_px()]
    return {"video_path": str(video), "compensate": True, "confirm": False,
            "mini": True, "mini_frames": [{"t": 0.5, "points": pts}]}


def _named_landmarks() -> dict:
    """5 个**有名字**的场地特征点（归一化），由上面那份 H 反投影生成。

    ⚠️ 不放篮筐：篮圈离地 3.05m，单应矩阵只映射地面，放进去会把标定拉偏。
    """
    import numpy as np
    from aihoop.court import find_homography
    names = ["corner_far_left", "corner_far_right",
             "lane_far_left", "lane_far_right", "arc_far"]
    Hm = np.asarray(find_homography([list(p) for p in _quad_px()],
                                    _quarter_px()), dtype=float)
    Hinv = np.linalg.inv(Hm)
    out = {}
    for n in names:
        x, y = api.COURT_LANDMARKS[n]
        q = Hinv @ np.array([float(x), float(y), 1.0])
        out[n] = [float(q[0] / q[2]) / 1280.0, float(q[1] / q[2]) / 720.0]
    return out


def _snap_body(video: Path) -> dict:
    return {"video_path": str(video), "compensate": True, "confirm": False,
            "snap": True, "frames": [{"t": 0.5, "landmarks": _named_landmarks()}]}


def _px_of(out: dict) -> dict:
    """返回回来的"实际参与解算的点"：点名 → 像素坐标。

    ⚠️ 接口里 `px` 是 `round(x, 1)` 之后的值，所以比对容差必须留够 0.05：
    拿 0.01 去卡会把"没动"误判成"动了"（实测踩到）。这里留 0.06 —— 判定依然很锋利：
    本测试里"真的动了"的位移是 6.4px、"不该动却动了"的位移是 32px，都远在容差之外。
    """
    return {p["name"]: list(p["px"]) for p in out["per_point"]}


PX_TOL = 0.06


def _is_mat3(v) -> bool:
    return (isinstance(v, list) and len(v) == 3
            and all(isinstance(r, list) and len(r) == 3
                    and all(isinstance(x, (int, float)) for x in r) for r in v))


# ----------------------------------------------------------------- mini
def test_mini_four_points_returns_homography(monkeypatch):
    """只点 4 个点、不给名字 → 后端自动定向，并给出可直接叠加的单应矩阵。"""
    video = _video()
    body = _mini_body(video)
    assert "frames" not in body, "mini 模式本来就不发命名地标（这条是前提）"
    r = _client(monkeypatch).post("/api/calibrate_multi", json=body)

    # ① 关键约束：mini 块必须在 `len(src) < 4` 之前。
    #    src 是空的，若顺序写错这里会是 400「至少要点 4 个场地特征点」。
    assert r.status_code == 200, r.text
    out = r.json()

    # ② 返回体里有 mini，而且真的解出来了
    assert "mini" in out, "返回体必须带 mini 键"
    mini = out["mini"]
    assert mini is not None, "mini 模式不许返回 mini=null"
    assert mini["ok"] is True, mini
    assert mini.get("which"), "要说清选中了哪套球场地物组合"
    assert len(mini["dst"]) == 4, "自动定向的结果 = 4 个球场坐标点"
    assert mini["ranked"], "候选排名要一起回，界面据此说明可信度"

    # ③ 单应矩阵真的拿到了（两条路都要有：mini 自己的、以及实际用的那份）
    assert _is_mat3(mini["H"]), "mini 里要带它解出来的 H"
    assert _is_mat3(out["H"]), "顶层 H 是实际用的那份，叠加球场线靠它"
    assert out["n_points"] == 4 and out["n_points_received"] == 4

    # ④ mini 模式没发命名点 → 精修无从下手，如实是 null（键必须在）
    assert "snap" in out and out["snap"] is None


def test_mini_confirm_is_refused(monkeypatch):
    """4 点自动猜测**只能预览**：它无法校验对应的是哪四条线，不许存成位置标定。"""
    video = _video()
    body = dict(_mini_body(video), confirm=True)
    r = _client(monkeypatch).post("/api/calibrate_multi", json=body)
    assert r.status_code == 400, r.text
    assert "只能预览" in r.json()["detail"]


# ----------------------------------------------------------------- snap
def test_snap_field_present_and_accepted_is_bool(monkeypatch):
    """精修（点吸附）必须如实汇报：采纳了没有、吻合度前后、各点移了几像素。"""
    video = _video()
    r = _client(monkeypatch).post("/api/calibrate_multi", json=_snap_body(video))
    assert r.status_code == 200, r.text
    out = r.json()

    assert "snap" in out, "返回体必须带 snap 键"
    snap = out["snap"]
    assert snap is not None, "给了画面和 5 个命名点，精修就该真跑过一遍"
    assert isinstance(snap.get("accepted"), bool), snap
    for k in ("before", "after", "moved_px", "note"):
        assert k in snap, "缺 %s 的裁决结果没法在界面上如实说" % k
    # 5 个点都参与了解算（篮筐点在这份夹具里本来就没有）
    assert out["n_points"] == 5


def test_snap_keeps_points_when_guard_rejects(monkeypatch):
    """护栏拒绝（accepted=False）时**点集一个字都不许动**。

    为什么单独钉：精修带护栏是因为这一机位太正对时，单应矩阵病态，
    精修能把吻合度刷到 74 那种退化解。拒绝之后若还去替换点集，
    等于拿一个坏目标自动改用户的点 —— 那是在骗分数。
    这里把 refine_keypoints 换成"胡乱平移"的假实现，看后端认不认它的结果。
    """
    video = _video()
    orig_lm = _named_landmarks()
    orig_px = {k: [v[0] * 640.0, v[1] * 480.0] for k, v in orig_lm.items()}
    shifted = {k: [v[0] + 0.05, v[1] + 0.05] for k, v in orig_lm.items()}

    client = _client(monkeypatch)
    # ① 护栏拒绝 → 点必须原样保留
    monkeypatch.setattr(calibcheck, "refine_keypoints",
                        lambda *a, **kw: {"accepted": False, "note": "假拒绝",
                                          "landmarks": shifted, "before": 1.0,
                                          "after": 2.0, "moved_px": {}, "passes": 1})
    out = client.post("/api/calibrate_multi", json=_snap_body(video)).json()
    assert out["snap"]["accepted"] is False
    px = _px_of(out)
    assert out["n_points"] == 5
    for name, want in orig_px.items():
        assert abs(px[name][0] - want[0]) < PX_TOL and \
               abs(px[name][1] - want[1]) < PX_TOL, \
            "护栏拒绝了却还是动了点：%s → %s（应为 %s）" % (name, px[name], want)

    # ② 采纳 → 点**必须**跟着动（否则就是"假精修"：报告说采纳了，实际没用）
    moved = dict(orig_lm)
    moved["corner_far_left"] = [orig_lm["corner_far_left"][0] + 0.01,
                                orig_lm["corner_far_left"][1]]
    monkeypatch.setattr(calibcheck, "refine_keypoints",
                        lambda *a, **kw: {"accepted": True, "note": "假采纳",
                                          "landmarks": moved, "before": 1.0,
                                          "after": 1.6, "moved_px": {}, "passes": 1})
    out2 = client.post("/api/calibrate_multi", json=_snap_body(video)).json()
    assert out2["snap"]["accepted"] is True
    px2 = _px_of(out2)
    dx = px2["corner_far_left"][0] - orig_px["corner_far_left"][0]
    assert abs(dx - 0.01 * 640.0) < 0.5, \
        "被采纳了却没替换点集（位移 %.2f px，应为 %.2f）" % (dx, 0.01 * 640.0)
    # 没被改的点不许跟着漂
    assert abs(px2["arc_far"][0] - orig_px["arc_far"][0]) < PX_TOL


# ----------------------------------------------------------------- 出口
def test_soft_failure_exit_carries_both_keys(monkeypatch):
    """软失败出口（每幅画面都不够 4 个点）同样要带 snap / mini 两把键。"""
    video = _video()
    lm = _named_landmarks()
    names = list(lm)
    body = {"video_path": str(video), "compensate": False, "confirm": False,
            "frames": [{"t": 0.3, "landmarks": {k: lm[k] for k in names[:3]}},
                       {"t": 0.7, "landmarks": {k: lm[k] for k in names[3:]}}]}
    r = _client(monkeypatch).post("/api/calibrate_multi", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is False and "4 个点" in out["note"]
    assert "snap" in out and "mini" in out, "软失败出口漏键了"


def test_every_return_of_the_endpoint_carries_both_keys():
    """**每一条** return 都要带 snap / mini —— 包括端到端很难造出来的 per-shot 那条。

    这条用 AST 数，不靠跑请求：per-shot 出口需要真视频里出现两个镜头，
    构造成本高且脆；而"漏键"这件事本身就是结构问题，AST 检查是直接判据。
    """
    tree = ast.parse(inspect.getsource(api.post_calibrate_multi))
    returns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    # 顶层 5 条字典出口（per-shot / 逐帧不足 / per-frame / blocked 软失败 / 成功）。
    # 内层 _warp_status 返回的是元组（不是 Dict），不会被数进来。
    assert len(returns) >= 5, "出口比预想的少，检查是不是被改动了"
    for node in returns:
        keys = {k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        assert {"snap", "mini"} <= keys, \
            "第 %d 行的 return 缺 snap/mini 键：%s" % (node.lineno, sorted(keys))
