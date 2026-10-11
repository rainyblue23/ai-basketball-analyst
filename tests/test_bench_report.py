# -*- coding: utf-8 -*-
"""`scripts/bench_report.py` 的纯函数测试（不跑重活、不碰真值文件）。

为什么单独钉这几条（用户 2026-10-11 的要求 + 本仓库的规矩）：
  * 汇总表最容易犯的错是**把测不了的写成数字**，所以这里钉死「没有结果时必须是未测」；
  * 第二个错是**拿小样本算比率当结论**，所以钉死 small_sample 标记；
  * 第三个错是**比率算法本身写反**（召回/精确倒置），所以用已知答案的构造数据钉死。
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bench_report", ROOT / "scripts" / "bench_report.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


# ---------------- 事件层 ----------------

def test_event_metrics_math():
    rows = [
        # 8 次真值、10 个引擎事件、匹配上 6 个 → 召回 0.75、精确 0.6、F1 ≈ 0.6667
        dict(truth_shots=8, engine_events=10, matched=6, missed=2, extra=4,
             matched_result_correct=4, pairs=[dict(delta_s=0.5), dict(delta_s=-1.0)]),
        dict(truth_shots=2, engine_events=0, matched=0, missed=2, extra=0,
             matched_result_correct=0, pairs=[]),
    ]
    m = bench.event_metrics(rows)
    assert m["truth_shots"] == 10 and m["engine_events"] == 10
    assert m["matched"] == 6 and m["missed"] == 4 and m["extra"] == 4
    assert abs(m["recall_tol1.5s"] - 0.6) < 1e-9
    assert abs(m["precision_tol1.5s"] - 0.6) < 1e-9
    assert abs(m["f1_tol1.5s"] - 0.6) < 1e-9
    assert abs(m["delta_s_mean"] - 0.75) < 1e-9 and abs(m["delta_s_max"] - 1.0) < 1e-9
    assert m["small_sample"] is True, "10 次出手的样本量必须被标成「不足」"


def test_event_metrics_empty_is_none_not_zero():
    m = bench.event_metrics([])
    assert m["truth_shots"] == 0 and m["engine_events"] == 0
    assert m["recall_tol1.5s"] is None and m["precision_tol1.5s"] is None and m["f1_tol1.5s"] is None
    assert m["delta_s_mean"] is None and m["delta_s_max"] is None


def test_event_metrics_zero_engine_events_does_not_divide_by_zero():
    m = bench.event_metrics([dict(truth_shots=3, engine_events=0, matched=0, missed=3, extra=0)])
    assert m["recall_tol1.5s"] == 0.0 and m["precision_tol1.5s"] is None and m["f1_tol1.5s"] is None


def test_event_metrics_enough_sample_is_not_flagged():
    rows = [dict(truth_shots=25, engine_events=25, matched=25, missed=0, extra=0,
                 matched_result_correct=25, pairs=[dict(delta_s=0.1)])]
    m = bench.event_metrics(rows)
    assert m["small_sample"] is False
    assert m["recall_tol1.5s"] == 1.0 and m["f1_tol1.5s"] == 1.0


# ---------------- 球定位 ----------------

def test_ball_metrics_uses_named_scale_and_reports_rates():
    rep = dict(weights="w.pt", weights_sha256="a" * 64, visibility=dict(visible=7, not_visible=19, unclear=6),
               summary=dict(**{"640": dict(truth_boxes=7, matched_iou50=2, matched_iou30=2,
                                           center_in_annotation=2, not_visible_frames=19,
                                           not_visible_frames_with_detections=6),
                               "union": dict(truth_boxes=7, matched_iou50=2, matched_iou30=2,
                                             center_in_annotation=2, not_visible_frames=19,
                                             not_visible_frames_with_detections=11)}),
               limits=["x"])
    b = bench.ball_metrics(rep)                       # 默认 union
    assert b["scale"] == "union" and b["available_scales"] == ["640", "union"]
    assert b["truth_boxes"] == 7 and b["matched_iou50"] == 2
    assert abs(b["rate_iou50"] - 2 / 7) < 1e-9
    assert b["not_visible_frames_with_detections"] == 11
    assert b["small_sample"] is True and b["weights_sha256_12"] == "a" * 12


def test_ball_metrics_unknown_scale_is_zero_not_crash():
    b = bench.ball_metrics({"summary": {}}, scale="does-not-exist")
    assert b["truth_boxes"] == 0 and b["rate_iou50"] is None


# ---------------- 缺口与渲染 ----------------

def test_missing_results_render_as_untested_not_as_numbers(tmp_path):
    truth = {"samples": [dict(id="m1", video=str(tmp_path / "nope.mp4"), start_s=0, end_s=60,
                              shots=[dict(release_s=1.0, result="made")], shots_complete=True,
                              frames_complete=True, frames=[dict(boxes=[dict(kind="ball")])])]}
    tp = tmp_path / "truth.json"
    tp.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

    ctx = bench.build_context(tp, tmp_path / "bench", tmp_path / "batch",
                              tmp_path / "w.pt", None, None)
    md = bench.render_md(ctx)

    assert "**未测**" in md, "没有结果文件时必须写「未测」，不许拿别的数字顶上"
    assert "未评测的模块" in md
    assert "球衣号码" in md and "战术层" in md
    assert ctx["events"] is None and ctx["ball"] is None
    assert ctx["n_truth_shots"] == 1 and ctx["n_video_ok"] == 0
    # 视频不存在 + 批次不存在 → 缺口清单里必须多出「球定位评测 跑不了」
    assert any(g["status"] == "跑不了" for g in ctx["gaps"])
    assert "只读" in md or "只**读**" in md


def test_render_md_quotes_protocol_notes():
    ctx = dict(generated_at="t", truth_path="p", truth_sha256_12="0" * 12, n_samples=0,
               n_truth_shots=0, n_video_ok=0,
               materials=dict(batch_frames=0, weights_exists=False),
               events_path=None, events=None, ball_path=None, ball=None, gaps=[])
    md = bench.render_md(ctx)
    assert "±1.5 s" in md, "事件匹配容差必须写进表里"
    assert "不叫准确率" in md, "定位指标不能被叫成准确率"


# ---------------- 真值读取 ----------------

def test_load_truth_rejects_missing_and_malformed(tmp_path):
    import pytest as _pytest
    try:
        bench.load_truth(tmp_path / "nope.json")
        raise AssertionError("缺文件时应当抛错")
    except FileNotFoundError:
        pass
    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": 1}', encoding="utf-8")
    try:
        bench.load_truth(bad)
        raise AssertionError("没有 samples 时应当抛错")
    except ValueError:
        pass
