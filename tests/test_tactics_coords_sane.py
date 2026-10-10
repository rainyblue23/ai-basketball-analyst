"""战术图出图前的最后一道闸：球员坐标在**物理上**说不通就不出图。

用户实测（原话："你看这个战术图，为什么人都在底线哪里，而且还是只有半场？"）：
那份 job 的静态标定是 `valid=False / rmse=23.5m`，但自动逐帧标定自称
`median_ratio=14.48、达标率 0.999`，于是战术层走了兜底路，**照样出了一张战术图**。
图上：90% 的点挤在 x≈7.5（边线）、y 只铺开 8.4m。

分数（ratio / 达标率）看不出来这种错 —— **坐标自己的分布**能看出来。
"""
from __future__ import annotations

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aihoop.pipeline import _tactics_coords_sane       # noqa: E402
from aihoop.tactics import PlayerSample                # noqa: E402


def _pts(pairs):
    # 采样时刻间距 0.1s（原来 0.03s 时 333 个点只覆盖 10 秒，
    # 过不了判据新加的"时间跨度 ≥15s"守卫；用户 2026-10-05）
    return [PlayerSample(t=i * 0.1, player_id="T%d" % (i % 10), team="home",
                         x=float(x), y=float(y))
            for i, (x, y) in enumerate(pairs)]


def test_catches_points_piled_on_sideline():
    """90% 的点贴在边线上 —— 必须判为不可用（用户那份数据的特征）。"""
    rng = random.Random(7)
    pairs = [(7.47 + rng.uniform(0, 0.12), -rng.uniform(0, 8.3)) for _ in range(300)]
    pairs += [(rng.uniform(-2.5, 6.0), -rng.uniform(0, 8.3)) for _ in range(33)]
    ok, why = _tactics_coords_sane(_pts(pairs))
    assert ok is False, "贴在边线上的点必须被拦下"
    assert "边界" in why or "铺开" in why, why
    assert "重新标" in why, "拒绝时要说清怎么修"


def test_catches_collapsed_spread():
    """坐标只铺开不到 1.5m —— 球员不可能挤成一条线。"""
    rng = random.Random(3)
    pairs = [(rng.uniform(-0.6, 0.6), -rng.uniform(0, 13)) for _ in range(200)]
    ok, why = _tactics_coords_sane(_pts(pairs))
    assert ok is False, "展布过窄必须被拦下：%s" % why


def test_normal_half_court_positions_pass():
    """正常铺开的半场坐标必须通过（别把好数据也拦了）。"""
    rng = random.Random(11)
    pairs = [(rng.uniform(-7.0, 7.0), -rng.uniform(0.3, 13.5)) for _ in range(400)]
    ok, why = _tactics_coords_sane(_pts(pairs))
    assert ok is True and why == "", "正常分布被误判：%s" % why


def test_players_legitimately_near_baseline_pass():
    """球员合法地聚在篮下（真实比赛常见）不该被误杀。"""
    rng = random.Random(5)
    pairs = [(rng.uniform(-2.0, 2.0), -rng.uniform(0.5, 4.0)) for _ in range(250)]
    ok, why = _tactics_coords_sane(_pts(pairs))
    assert ok is True, "篮下聚集被误判：%s" % why


def test_small_sample_is_not_judged():
    """样本太少时不判定 —— 短片段没有统计意义。"""
    ok, why = _tactics_coords_sane(_pts([(7.5, -1.0)] * 50))
    assert ok is True and why == ""


def test_empty_track_is_not_judged():
    ok, why = _tactics_coords_sane([])
    assert ok is True and why == ""


# ===================== 反例（用户 2026-10-05 要求补） =====================
# 这几组都是**合法但不具代表性**的轨道，判据必须放行；否则一份好标定会因为
# "这段时间只有一个球员在边线站着"而被拒绝出战术图。

def test_single_player_standing_long_is_not_judged():
    """单人长时间停留：一个人的坐标分布说明不了标定好坏（先看不同球员数）。"""
    rng = random.Random(21)
    pairs = [(7.47 + rng.uniform(0, 0.1), -rng.uniform(0, 8.0)) for _ in range(400)]
    rows = [PlayerSample(t=i * 0.1, player_id="ONLY", team="home", x=x, y=y)
            for i, (x, y) in enumerate(pairs)]
    ok, why = _tactics_coords_sane(rows)
    assert ok is True and why == "", "单人轨道不该被判据拦住：%s" % why


def test_short_sideline_inbound_is_not_judged():
    """边线发球：5 个人贴着边线站了 8 秒 —— 片段太短，不足以做物理判定。"""
    rng = random.Random(22)
    rows = []
    for i in range(200):
        pid = "P%d" % (i % 5)
        rows.append(PlayerSample(t=i * 0.04, player_id=pid, team="home",
                                 x=7.35 + rng.uniform(0, 0.15),
                                 y=-rng.uniform(0, 6.0)))
    ok, why = _tactics_coords_sane(rows)
    assert ok is True and why == "", "短片段边线发球不该被拦：%s" % why


def test_inbound_inside_normal_play_passes():
    """边线发球混在正常进攻里：贴边只占一小部分时间，整体分布是正常的。"""
    rng = random.Random(23)
    rows = []
    for i in range(60):                      # 前 6 秒：发球，全员贴边线
        rows.append(PlayerSample(t=i * 0.1, player_id="P%d" % (i % 5), team="home",
                                 x=7.4 + rng.uniform(0, 0.1), y=-rng.uniform(0, 5.0)))
    for i in range(60, 260):                 # 之后 20 秒：正常进攻，铺开
        rows.append(PlayerSample(t=i * 0.1, player_id="P%d" % (i % 6), team="home",
                                 x=rng.uniform(-6.5, 6.5), y=-rng.uniform(0.5, 13.0)))
    ok, why = _tactics_coords_sane(rows)
    assert ok is True and why == "", "发球+正常进攻不该被拦：%s" % why


def test_local_framing_cluster_passes():
    """局部取景：球员合法地聚在 3m×3m 的一小块（不是塌成一条线）。"""
    rng = random.Random(24)
    rows = [PlayerSample(t=i * 0.1, player_id="P%d" % (i % 6), team="home",
                         x=-2.0 + rng.uniform(0, 3.0), y=-6.0 + rng.uniform(0, 3.0))
            for i in range(300)]
    ok, why = _tactics_coords_sane(rows)
    assert ok is True and why == "", "局部取景的小范围聚集不该被拦：%s" % why
