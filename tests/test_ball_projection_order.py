# -*- coding: utf-8 -*-
"""滑动标定必须在**球/球员投影之前**算出来（否则球轨迹恒为空）。

实测（NBA 转播 1920×1080 / 91s / 地面站）：
    球检测出 **97.5 万个候选**、排到 12 条轨迹，最后 `kept_points = 0`、
    `coverage 0.0` —— 界面上显示"没有球轨迹"，看起来像球没检到，
    于是控球、传球网络、出手判定全都跟着没了。

根因是**顺序**：球的投影循环要拿逐帧滑窗标定的 H（没有静态标定时唯一的坐标来源），
而那段"静态标定不可用 → 启用逐帧滑动标定"的代码原来写在球投影**之后**：
    for c in kept:                     # 球投影
        if self.sliding and ...:       # self.sliding 还是 None → 走不到
        elif calibration_valid: ...    # 也没有静态标定 → 走不到
        else: continue                 # → 每个球候选都被丢掉
    ...
    if self.sliding is None and ...:    # ← 滑窗标定在这之后才算出来
        self.sliding = sliding_calibration(...)

这类"顺序错了、不报错、只是结果永远为空"的问题，只有结构性断言能钉住 ——
跑真实视频太贵（1080p 一趟 53 分钟）。
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aihoop.sources import VideoSource                      # noqa: E402


def test_sliding_calibration_runs_before_ball_projection():
    src = inspect.getsource(VideoSource.run)
    i_sliding = src.find("sliding_calibration(")
    i_ball = src.find("for c in kept:")
    assert i_sliding != -1, "run() 里没找到滑动标定的调用"
    assert i_ball != -1, "run() 里没找到球的投影循环"
    assert i_sliding < i_ball, (
        "滑动标定必须早于球的投影循环 —— 否则 self.sliding 还是 None，"
        "每个球候选都会 continue，球轨迹恒为空（实测 kept_points=0 / coverage 0.0）")


def test_ball_projection_uses_sliding_when_static_calibration_missing():
    """球投影那一段必须**优先**用滑窗标定（和球员同一套坐标）。"""
    src = inspect.getsource(VideoSource.run)
    i_loop = src.find("for c in kept:")
    seg = src[i_loop:i_loop + 1200]
    assert "self.sliding" in seg, "球投影没有用滑窗标定"
    assert seg.find("self.sliding") < seg.find("calibration_valid"), (
        "球投影里滑窗标定要优先于静态标定（球员走的是滑窗，混用会逐渐错开，"
        "表现是控球恒为 0）")
