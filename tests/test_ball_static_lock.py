# -*- coding: utf-8 -*-
"""静止锁 + 重新锚定（第四轮加的跟踪规则）的单元测试。

为什么钉这几条：这条规则是**为了让跟踪器脱离"锁在一个静止物上"**才加的，
但它同样能"把轨迹带偏"。所以两边都要钉：
  * 可疑时（连续够久几乎不动）**必须**能换到更可信的候选——哪怕那一跳会被 jump 门拒；
  * 不可疑时**一个字都不能变**（保持原有行为，不能让老素材回归）；
  * 没有更好的候选时**不许乱丢**（继续用原轨迹）。
"""
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.stream import LegacyShotStream

FPS = 30
W = 1920


def make_stream(lock_s=None):
    s = LegacyShotStream(FPS, W)
    if lock_s is not None:
        s.config['detect']['ball_static_lock_s'] = lock_s
    return s


def ball(conf, x, y, w=30):
    return Det('basketball', conf, (x - w / 2, y - w / 2, x + w / 2, y + w / 2))


# ---------------- 可疑判定 ----------------

def test_action_is_off_by_default_but_diagnostics_still_count():
    """默认关：**动作**不许触发（不改行为），但可疑帧数照样要能报出来。"""
    s = make_stream()
    assert s.config['detect']['ball_static_lock_s'] == 0.0, "默认应当是关（没测出收益就不默认改行为）"
    s.static_run = 600
    assert s.static_lock() is False, "关着的时候不许换锚"
    assert s.static_lock_measured() is True, "诊断计数与动作无关，必须照算"


def test_static_lock_needs_a_full_second_when_enabled():
    s = make_stream(lock_s=1.0)
    need = int(round(FPS * 1.0))
    s.static_run = need - 1
    assert s.static_lock() is False
    s.static_run = need
    assert s.static_lock() is True


def test_static_lock_resets_on_cut():
    s = make_stream()
    s.static_run = 999
    s.reset(100, 3.3)
    assert s.static_run == 0 and s.static_lock() is False


# ---------------- 重新锚定 ----------------

def test_reacquire_picks_higher_confidence_candidate():
    s = make_stream()
    current = ball(0.30, 100, 100)
    far = ball(0.60, 1500, 300)
    lo = s.config['detect']['ball_min_w_ratio'] * min(W, 960)
    alt = s._reacquire([current, far], current, lo)
    assert alt is far, "应当换到置信度更高的那一个"


def test_reacquire_refuses_weaker_candidate():
    s = make_stream()
    current = ball(0.60, 100, 100)
    weak = ball(0.31, 1500, 300)
    lo = s.config['detect']['ball_min_w_ratio'] * min(W, 960)
    assert s._reacquire([current, weak], current, lo) is None, "没有更可信的候选就不许换"


def test_reacquire_respects_size_gate():
    s = make_stream()
    current = ball(0.30, 100, 100)
    huge = ball(0.90, 1500, 300, w=900)          # ball_max_w_ratio=0.24*1920=460 px
    lo = s.config['detect']['ball_min_w_ratio'] * min(W, 960)
    assert s._reacquire([current, huge], current, lo) is None, "尺度不合法的候选不能当锚"


# ---------------- 行为：可疑 vs 不可疑 ----------------

def _preview(s, cands, suspect):
    return s.preview_ball(1, cands, image=None, suspect=suspect)


def test_without_suspicion_the_far_candidate_is_still_rejected():
    """不可疑时保持原行为：远处候选仍是 motion_rejected。"""
    s = make_stream()
    s.last_ball = ball(0.30, 1000, 500)
    s.last_frame = 0
    s.vx = s.vy = 0.0
    far = ball(0.80, 1800, 200)                  # 距离 ~940 px，远超 90 px 门
    picked, audit = _preview(s, [far], suspect=False)
    assert picked is None, "不可疑时不能因为置信度高就接住远处候选"
    assert audit[0]['selection_reason'] == 'motion_rejected'


def test_with_suspicion_the_far_candidate_is_taken_over():
    """可疑时接住远处的真球候选（这正是修复目标）。"""
    s = make_stream(lock_s=1.0)
    s.last_ball = ball(0.30, 1000, 500)
    s.last_frame = 0
    s.vx = s.vy = 0.0
    far = ball(0.80, 1800, 200)
    picked, audit = _preview(s, [far], suspect=True)
    assert picked is not None and picked is far
    assert audit[0]['selection_reason'] == 'reacquired'


def test_with_suspicion_still_prefers_the_strict_selection_when_it_is_better():
    """可疑期也不能把已经跟得好、置信度更高的球换掉。"""
    s = make_stream(lock_s=1.0)
    near = ball(0.70, 1005, 502)
    s.last_ball = ball(0.60, 1000, 500)
    s.last_frame = 0
    s.vx = s.vy = 0.0
    picked, audit = _preview(s, [near, ball(0.55, 1800, 200)], suspect=True)
    assert picked is near, "被跟踪的那条置信度更高时不该被换掉"
    assert audit[0]['selection_reason'] == 'selected'


def test_update_counts_reacquired_frames():
    s = make_stream(lock_s=1.0)
    s.last_ball = ball(0.30, 1000, 500)
    s.last_frame = 0
    s.static_run = 30                            # 已经锁住
    s.update(1, 0.03, [ball(0.80, 1800, 200)], persons=(), image=None)
    assert s.reacquired_frames == 1, "换锚必须记数（否则没法复查）"
    assert s.static_lock_frames == 1
    assert s.static_run == 0, "换锚后重新开始计静止时长"


def test_update_resets_static_run_when_ball_moves():
    s = make_stream()
    s.last_ball = ball(0.50, 1000, 500)
    s.last_frame = 0
    s.static_run = 12
    s.update(1, 0.03, [ball(0.50, 1030, 500)], persons=(), image=None)   # 走了 30 px
    assert s.static_run == 0, "球在动，静止计数要归零"
