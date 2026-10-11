# -*- coding: utf-8 -*-
"""一键评测汇总：把人工真值 + 各评测脚本的产物，收成**一张跨模块指标表**。

为什么要有它（用户 2026-10-11 的要求）：
    评测脚本我们有一堆（`eval_annotated_balls.py` / `eval_match_annotations.py` /
    `eval_shots_vs_truth.py` …），但结果散在 `out/` 各处，谁也说不清"现在到底几项能测、
    每项多少、哪些压根没测"。参赛材料要的是一张表，而不是 106 篇文档里的散点。

三条口径（照本仓库一贯的规矩）：
    1. **默认不跑重活**：只汇总 `out/` 里已有的结果，秒级返回；要真跑加 `--run`。
    2. **能测的给数字，测不了的不编**：每一项都写清"缺什么材料才能测、谁来补"。
    3. **样本量小就不下结论**：4 次出手算出来的 F1 没有意义，表里会直接标「样本量不足」。

用法::

    python scripts/bench_report.py                      # 汇总（快）
    python scripts/bench_report.py --run                # 真跑事件评测 + 球定位评测
    python scripts/bench_report.py --ball-json out/xxx/ball_evaluation.json
    python scripts/bench_report.py --events-json out/bench/events/results.json

产物：`out/bench/bench_report.md`（人看）+ `out/bench/bench_report.json`（机器读）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRUTH = ROOT / "eval" / "ground_truth" / "match_testset_20261011.json"
DEFAULT_OUT = ROOT / "out" / "bench"
BALL_WEIGHTS = ROOT / "runs" / "detect" / "ball" / "weights" / "best.pt"

# 低于这个样本量时，比率类指标只作参考、不下结论（评测集目前只有 4 次出手）
SMALL_N = 20

# 口径说明：这些数字**不是**同一件事，不能混着叫"准确率"（照 eval/README.md）
METRIC_NOTES = [
    "IoU≥0.5 / IoU≥0.3 / 中心落框 是三种宽松定位指标，不合并、不叫准确率。",
    "事件匹配容差 ±1.5 s，按时间顺序一对一匹配：先最大化匹配数，再最小化总时间误差。",
    "「看不清」帧排除在定位评测外；「不可见」帧报告有候选的帧数（误检代理，不是漏检率）。",
    "评测片段为精确时段用 CRF18 重编码，检测结果可能与原片有轻微差异。",
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_truth(path: Path) -> dict:
    """读人工真值。**只读不写** —— 真值永远是人工的，程序不许覆盖它。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"真值文件不存在：{path}")
    truth = load_json(path)
    if "samples" not in truth:
        raise ValueError(f"真值文件里没有 samples：{path}")
    return truth


def check_materials(truth: dict, batch_dir: Path | None = None, weights: Path | None = None,
                    verify_hash: bool = False) -> dict:
    """核对素材是否齐：源视频在不在、标注帧图在不在、球检测权重在不在。

    `--verify-hash` 会真算源视频的 SHA-256 与真值里的 `source_sha256` 比对
    （几十 MB/段，默认关掉以保持秒级返回）。
    """
    samples = []
    for s in truth.get("samples") or []:
        vid = Path(str(s.get("video") or ""))
        row = {
            "id": s.get("id"),
            "video": str(vid),
            "video_exists": vid.exists(),
            "video_mb": round(vid.stat().st_size / 1048576, 1) if vid.exists() else None,
            "start_s": s.get("start_s"),
            "end_s": s.get("end_s"),
            "truth_shots": len(s.get("shots") or []),
            "shots_complete": bool(s.get("shots_complete")),
            "frames_complete": bool(s.get("frames_complete")),
            "source": s.get("source"),
        }
        if verify_hash and vid.exists():
            h = hashlib.sha256()
            with vid.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            row["video_sha256_ok"] = (h.hexdigest() == str(s.get("source_sha256") or ""))
        samples.append(row)

    bd = Path(batch_dir) if batch_dir else None
    frames = 0
    if bd and bd.exists():
        frames = len(list(bd.glob("match_*/frame_*.jpg")))
    w = Path(weights) if weights else None
    return {
        "samples": samples,
        "batch_dir": str(bd) if bd else None,
        "batch_exists": bool(bd and bd.exists()),
        "batch_frames": frames,
        "weights": str(w) if w else None,
        "weights_exists": bool(w and w.exists()),
    }


def event_metrics(rows: list) -> dict:
    """事件层（出手/命中）汇总。输入 = `eval_match_annotations.py` 的 rows。"""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    n_truth = sum(int(r.get("truth_shots") or 0) for r in rows)
    n_engine = sum(int(r.get("engine_events") or 0) for r in rows)
    matched = sum(int(r.get("matched") or 0) for r in rows)
    missed = sum(int(r.get("missed") or 0) for r in rows)
    extra = sum(int(r.get("extra") or 0) for r in rows)
    correct = sum(int(r.get("matched_result_correct") or 0) for r in rows)
    deltas = [abs(float(p.get("delta_s"))) for r in rows for p in (r.get("pairs") or [])]

    recall = (matched / n_truth) if n_truth else None
    precision = (matched / n_engine) if n_engine else None
    if recall is None or precision is None or (recall + precision) == 0:
        f1 = None
    else:
        f1 = 2 * recall * precision / (recall + precision)
    return {
        "n_samples": len(rows),
        "truth_shots": n_truth,
        "engine_events": n_engine,
        "matched": matched,
        "missed": missed,
        "extra": extra,
        "matched_result_correct": correct,
        "recall_tol1.5s": recall,
        "precision_tol1.5s": precision,
        "f1_tol1.5s": f1,
        "delta_s_mean": (sum(deltas) / len(deltas)) if deltas else None,
        "delta_s_max": max(deltas) if deltas else None,
        "small_sample": n_truth < SMALL_N,
    }


def ball_metrics(report: dict, scale: str = "union") -> dict:
    """球检测定位汇总。输入 = `eval_annotated_balls.py` 的 report。"""
    report = report or {}
    summ = (report.get("summary") or {})
    s = summ.get(scale) or {}
    tb = int(s.get("truth_boxes") or 0)
    i50 = int(s.get("matched_iou50") or 0)
    i30 = int(s.get("matched_iou30") or 0)
    cen = int(s.get("center_in_annotation") or 0)
    nv = int(s.get("not_visible_frames") or 0)
    nvfp = int(s.get("not_visible_frames_with_detections") or 0)
    return {
        "scale": scale,
        "available_scales": sorted(summ.keys()),
        "truth_boxes": tb,
        "matched_iou50": i50,
        "matched_iou30": i30,
        "center_in_annotation": cen,
        "rate_iou50": (i50 / tb) if tb else None,
        "rate_iou30": (i30 / tb) if tb else None,
        "rate_center": (cen / tb) if tb else None,
        "not_visible_frames": nv,
        "not_visible_frames_with_detections": nvfp,
        "visibility": report.get("visibility") or {},
        "weights": report.get("weights"),
        "weights_sha256_12": str(report.get("weights_sha256") or "")[:12],
        "limits": report.get("limits") or [],
        "small_sample": tb < SMALL_N,
    }


def discover_ball_json(out_dir: Path, batch_dir: Path | None = None) -> Path | None:
    """找球定位结果：只看**本次指定的两个目录**，不跨 out/ 乱抓。

    为什么不 glob 全仓：`out/` 里躺着好几个批次的 `ball_evaluation.json`
    （`match_testset_20261011` / `ball_pilot_20261011`…）。自动抓最新的一份，
    会把**另一个批次**的数字混进这张表里 —— 那正是这张表最不该犯的错。
    要给别的批次，用 `--ball-json` 明确指定，路径会写进报告里。
    """
    cands = [Path(out_dir) / "ball_evaluation.json"]
    if batch_dir:
        cands.append(Path(batch_dir) / "ball_evaluation.json")
    for c in cands:
        if c.exists():
            return c
    return None


def run_events(truth: Path, out_dir: Path, device: str) -> Path:
    """真跑事件评测（调已有的 `scripts/eval_match_annotations.py`，不改它）。"""
    ev = out_dir / "events"
    ev.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "eval_match_annotations.py"),
           "--truth", str(truth), "--out", str(ev), "--device", device]
    print("[bench] 跑事件评测：" + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    return ev / "results.json"


def run_ball(batch_dir: Path, weights: Path, out_json: Path, device: str) -> Path:
    """真跑球定位评测（调已有的 `scripts/eval_annotated_balls.py`，不改它）。"""
    out_json.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "eval_annotated_balls.py"),
           "--batch", str(batch_dir), "--weights", str(weights),
           "--out", str(out_json), "--device", device]
    print("[bench] 跑球定位评测：" + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    return out_json


def gaps(truth: dict, materials: dict) -> list:
    """没测的模块 + 为什么没测 + 缺什么材料才测得了（不许含糊）。"""
    kinds = set()
    for s in truth.get("samples") or []:
        for f in s.get("frames") or []:
            for b in f.get("boxes") or []:
                kinds.add(str(b.get("kind")))
    batch_missing = not materials.get("batch_exists")
    rows = [
        dict(module="标定（RMSE / 弱段）", status="未测",
             why="评测集这 4 段素材没有标定文件，`calibcheck` 的 verification 无从跑起。",
             need="在这 4 段上各标一次地面点（全场 15 点里挑画面里看得见的 4~6 个），"
                  "再用 `scripts/check_video_fit.py` / calibcheck 取 rmse_m 与 worst_readings。",
             who="人点地标（约 20 分钟）+ 脚本自动算"),
        dict(module="球衣号码", status="未测",
             why="`sources.py` 已接 `jersey_numbers.recognize`，但 `eval/ground_truth/` 里没有号码真值。",
             need="按 docs 里那份「需要人工标注的真值清单」标 100+ 条「轨迹 ↔ 真号码」。",
             who="人看画面标（我看不了画面，只能写评测脚本）"),
        dict(module="战术层（控球/传球/阵型）", status="未测",
             why="没有回合级真值，只有合成数据上的自洽检查。",
             need="按回合标控球方与传球对（≥30 个回合）。",
             who="人看画面标"),
        dict(module="比分牌 OCR", status="未测",
             why="评测集没标比分牌读数。",
             need="每帧标比分值（或复用 `eval/ground_truth/scoreboard_vid3.rim_times.json` 那类旧真值）。",
             who="人标 + 脚本算字符准确率"),
        dict(module="队标误检率 / 篮筐定位", status="未测",
             why=f"帧标注里的 box 种类只有 {sorted(kinds) or '无'}，没有 badge/rim 框。",
             need="在帧标注里补 `kind: badge` / `kind: rim` 的框（annotations.json 的 boxes 已支持 kind 字段）。",
             who="人补框 + `eval_annotated_balls.py` 扩展（要改脚本）"),
    ]
    if batch_missing:
        rows.insert(0, dict(module="球定位评测", status="跑不了",
                            why=f"批次目录不存在：{materials.get('batch_dir')}",
                            need="先产出 match_*/frame_*.jpg 的标注批次。", who="已有工具：scripts/serve_match_labeling.py"))
    return rows


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _num(v, nd=2) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def render_md(ctx: dict) -> str:
    """渲染人看的汇总表。"""
    L = []
    A = L.append
    A("# 评测汇总表（自动生成）")
    A("")
    A(f"- 生成时间：{ctx['generated_at']}")
    A(f"- 真值文件：`{ctx['truth_path']}`（SHA-256 `{ctx['truth_sha256_12']}…`，"
      f"{ctx['n_samples']} 段，{ctx['n_truth_shots']} 次人工出手）")
    A(f"- 素材核对：源视频 {ctx['n_video_ok']}/{ctx['n_samples']} 在；"
      f"标注帧图 {ctx['materials'].get('batch_frames')} 张；"
      f"球检测权重 {'在' if ctx['materials'].get('weights_exists') else '**不在**'}")
    A("")
    A("> 规矩：**测不了的写「未测」并说清缺什么，不许拿别的数字顶上**；"
      f"样本量 < {SMALL_N} 时比率类指标只作参考。")
    A("")

    A("## 1. 事件层：出手 / 命中（±1.5 s 一对一匹配）")
    A("")
    ev = ctx.get("events")
    if not ev:
        A("**未测**：没找到 " + f"`{ctx.get('events_path') or 'out/bench/events/results.json'}`"
          "（加 `--run` 可现跑）。")
    else:
        A("| 段 | 人工出手 | 引擎事件 | 匹配上 | 漏检 | 多报 | 结果判对 |")
        A("|---|---|---|---|---|---|---|")
        for r in ev["rows"]:
            A(f"| {r.get('id')} | {r.get('truth_shots')} | {r.get('engine_events')} | "
              f"{r.get('matched')} | {r.get('missed')} | {r.get('extra')} | "
              f"{r.get('matched_result_correct')} |")
        A(f"| **合计** | **{ev['truth_shots']}** | **{ev['engine_events']}** | **{ev['matched']}** | "
          f"**{ev['missed']}** | **{ev['extra']}** | **{ev['matched_result_correct']}** |")
        A("")
        A(f"- 召回（容差内匹配上）= {_pct(ev['recall_tol1.5s'])}；"
          f"精确 = {_pct(ev['precision_tol1.5s'])}；F1 = {_num(ev['f1_tol1.5s'])}"
          + ("　⚠️ **样本量不足，不作结论**" if ev["small_sample"] else ""))
        A(f"- 时间误差：平均 {_num(ev['delta_s_mean'])} s，最大 {_num(ev['delta_s_max'])} s")
        A(f"- 参数（来自结果文件，原样引用）：`{json.dumps(ev.get('parameters') or {}, ensure_ascii=False)}`")
        if ev.get("limits"):
            for x in ev["limits"]:
                A(f"- 限制：{x}")
    A("")

    A("## 2. 球检测定位（IoU≥0.5 / IoU≥0.3 / 中心落框，三种并列，不叫准确率）")
    A("")
    b = ctx.get("ball")
    if not b:
        A("**未测**：没找到球定位结果 json（加 `--run`，或用 `--ball-json` 指定）。")
    else:
        A(f"- 结果文件：`{ctx['ball_path']}`；权重 `{b['weights']}`（SHA `{b['weights_sha256_12']}…`）；"
          f"聚合口径 `{b['scale']}`（可选 {b['available_scales']}）")
        A(f"- 真值框 {b['truth_boxes']} 个：IoU≥0.5 命中 {b['matched_iou50']}（{_pct(b['rate_iou50'])}）、"
          f"IoU≥0.3 命中 {b['matched_iou30']}（{_pct(b['rate_iou30'])}）、"
          f"中心落框 {b['center_in_annotation']}（{_pct(b['rate_center'])}）"
          + ("　⚠️ **样本量不足，不作结论**" if b["small_sample"] else ""))
        A(f"- 帧可见性：{b['visibility']}；不可见帧 {b['not_visible_frames']} 中有候选的 {b['not_visible_frames_with_detections']} 帧"
          "（误检代理，**不是**准确率）")
        if b.get("limits"):
            for x in b["limits"]:
                A(f"- 限制：{x}")
    A("")

    A("## 3. 未评测的模块（缺什么、谁来补）")
    A("")
    A("| 模块 | 状态 | 为什么没测 | 要测需要什么 | 谁来做 |")
    A("|---|---|---|---|---|")
    for g in ctx["gaps"]:
        A(f"| {g['module']} | {g['status']} | {g['why']} | {g['need']} | {g['who']} |")
    A("")

    A("## 4. 指标口径与限制")
    A("")
    for x in METRIC_NOTES:
        A(f"- {x}")
    A("")
    A("---")
    A("")
    A("本表由 `scripts/bench_report.py` 生成；它**只读**已有结果与真值，不改任何人的标注。")
    return "\n".join(L) + "\n"


def build_context(truth_path: Path, out_dir: Path, batch_dir: Path, weights: Path,
                  events_json: Path | None, ball_json: Path | None,
                  verify_hash: bool = False) -> dict:
    truth_path = Path(truth_path)
    truth = load_truth(truth_path)
    raw = truth_path.read_bytes()
    materials = check_materials(truth, batch_dir=batch_dir, weights=weights, verify_hash=verify_hash)

    events_path = Path(events_json) if events_json else (out_dir / "events" / "results.json")
    events = None
    if events_path.exists():
        d = load_json(events_path)
        ev = event_metrics(d.get("samples") or [])
        ev["rows"] = d.get("samples") or []
        ev["parameters"] = d.get("parameters") or {}
        ev["limits"] = d.get("limits") or []
        ev["tolerance_s"] = d.get("tolerance_s")
        events = ev

    ball_path = Path(ball_json) if ball_json else discover_ball_json(out_dir, batch_dir)
    ball = ball_metrics(load_json(ball_path)) if (ball_path and Path(ball_path).exists()) else None

    return {
        "generated_at": _now(),
        "truth_path": str(truth_path),
        "truth_sha256_12": hashlib.sha256(raw).hexdigest()[:12],
        "n_samples": len(truth.get("samples") or []),
        "n_truth_shots": sum(len(s.get("shots") or []) for s in (truth.get("samples") or [])),
        "n_video_ok": sum(1 for s in materials["samples"] if s["video_exists"]),
        "materials": materials,
        "events_path": str(events_path),
        "events": events,
        "ball_path": str(ball_path) if ball_path else None,
        "ball": ball,
        "gaps": gaps(truth, materials),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="跨模块评测汇总（只读真值与他人结果）")
    ap.add_argument("--truth", type=Path, default=DEFAULT_TRUTH, help="人工真值 json")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="产出目录")
    ap.add_argument("--batch", type=Path, default=None, help="标注批次目录（默认按真值文件名推断）")
    ap.add_argument("--weights", type=Path, default=BALL_WEIGHTS, help="球检测权重")
    ap.add_argument("--events-json", type=Path, default=None, help="事件评测结果 results.json")
    ap.add_argument("--ball-json", type=Path, default=None, help="球定位评测结果 json")
    ap.add_argument("--device", default="0", help="评测脚本的 device（cpu / 0）")
    ap.add_argument("--run", action="store_true", help="真跑评测（慢）：事件 + 球定位")
    ap.add_argument("--verify-hash", action="store_true", help="真算源视频 SHA-256 与真值比对")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    batch = Path(args.batch) if args.batch else (ROOT / "out" / Path(args.truth).stem)
    events_json = args.events_json
    ball_json = args.ball_json

    if args.run:
        if not args.truth.exists():
            print(f"[bench] 真值不存在，跳过：{args.truth}", file=sys.stderr)
        else:
            events_json = run_events(args.truth, out_dir, args.device)
        if batch.exists() and Path(args.weights).exists():
            ball_json = run_ball(batch, Path(args.weights), out_dir / "ball_evaluation.json", args.device)
        else:
            print(f"[bench] 球定位跑不了（batch={batch} 权重={args.weights}）—— 表里会标出来",
                  file=sys.stderr)

    ctx = build_context(args.truth, out_dir, batch, args.weights, events_json, ball_json,
                        verify_hash=args.verify_hash)
    md = render_md(ctx)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bench_report.md").write_text(md, encoding="utf-8")
    (out_dir / "bench_report.json").write_text(
        json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    print(f"[bench] 已写出：{out_dir / 'bench_report.md'} 与 bench_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
