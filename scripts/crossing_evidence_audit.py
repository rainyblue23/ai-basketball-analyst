"""Read-only diagnostic pack and original-engine Bili development evaluation.

No human labels are passed to VideoSource. Annotation exports are separate drafts.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import threading
import time
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out/crossing_evidence_20261020"
IMPORT = ROOT / "eval/annotation_imports/three_bili_20261020/annotations.normalized.json"
sys.path.insert(0, str(ROOT / "scripts"))
from eval_match_annotations import match_times


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")


def protected():
    paths = list((ROOT / "src").rglob("*.py")) + list((ROOT / "eval/ground_truth").rglob("*"))
    paths += list(IMPORT.parent.glob("*"))
    paths += [ROOT / f"runs/detect/{k}/weights/best.pt" for k in ("ball", "rim")]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths if p.is_file()}


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    original = read(IMPORT)
    samples, audit = [], []
    for s in original["samples"]:
        actual = sha(s["video"])
        if actual != s["source_sha256"]:
            raise ValueError(f"SHA mismatch: {s['id']}")
        start, end = s["reviewed_range_declared"]
        if not s["shots_complete"]:
            raise ValueError(f"No complete shot review: {s['id']}")
        shots = [x for x in s["shots"] if start <= x["release_s"] < end]
        samples.append(dict(id=s["id"], video=s["video"], start_s=start, end_s=end, shots=shots))
        audit.append(dict(id=s["id"], sha256=actual, sha_match=True,
            dataset_split="Development", appearances=len(shots),
            unique_play_ids=len({x["play_id"] for x in shots}),
            source_match_id=s.get("source_match_id"), source_match_status="pending_full_match_identity",
            source_id=s["source_id"], time_basis=s["time_basis"],
            original_full_game_offset_s=s["original_full_game_offset_s"],
            reviewed_range=[start, end], completeness_basis=s["completeness_basis"],
            non_shot_events_complete=s["non_shot_events_complete"],
            pending=[dict(id=x["id"], reasons=x["pending_reasons"]) for x in shots if x["pending_reasons"]],
            types=[dict(id=x["id"], free_throw=x["is_free_throw"], note=x["note"],
                        is_replay=x["is_replay"], play_id=x["play_id"]) for x in shots]))
    write(OUT / "evaluation_input.json", dict(samples=samples))
    write(OUT / "annotation_audit.json", dict(import_sha256=sha(IMPORT), sources=audit,
        missing_known_sources=[], total_appearances=sum(x["appearances"] for x in audit),
        unique_plays=sum(x["unique_play_ids"] for x in audit),
        limits=["Full-game offset and match identity UNKNOWN.", "Non-shot subtype labels incomplete.",
                "31 frozen labels remain separate; no independent-test claim.",
                "Appearance matching uses original ±1.5s; replay grouping is descriptive only."]))
    write(OUT / "protected_before.json", protected())
    write(OUT / "baseline_plan.json", dict(
        algorithm="original", make_window_from_crossing=False, tolerance_s=1.5,
        dataset="Development only", input="CRF18 clip from reviewed range, same evaluator as frozen baseline",
        parameters=dict(players=False, scoreboard=False, auto_sliding=False, imgsz=640,
                        ball_roi_recovery=False, ball_rim_recovery=False),
        labels="passed only to evaluator after inference; no curated sample overrides",
        replay_protocol="All 59 appearances matched one-to-one; 57 unique play groups reported separately; "
                        "no inferred replay interval masking."))


def run_baseline():
    import psutil
    cmd = [sys.executable, "-B", str(ROOT / "scripts/eval_match_annotations.py"),
           "--truth", str(OUT / "evaluation_input.json"), "--out", str(OUT / "baseline"),
           "--device", "0", "--imgsz", "640"]
    t0 = time.time()
    with (OUT / "baseline_run.log").open("w", encoding="utf-8") as log:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        records = []
        while p.poll() is None:
            row = dict(elapsed_s=round(time.time()-t0, 2))
            try:
                process = psutil.Process(p.pid)
                processes = [process] + process.children(recursive=True)
                row["process_tree_rss_bytes"] = sum(q.memory_info().rss for q in processes if q.is_running())
                row["cpu_time_s"] = sum(sum(q.cpu_times()[:2]) for q in processes if q.is_running())
                row["gpu_device_sample"] = subprocess.check_output([
                    "nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu,power.draw",
                    "--format=csv,noheader,nounits"], text=True).strip()
                row["gpu_processes"] = subprocess.check_output([
                    "nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                    "--format=csv,noheader,nounits"], text=True).strip()
            except Exception as e:
                row["monitor_error"] = str(e)
            records.append(row)
            write(OUT / "resources.json", dict(command=cmd, samples=records,
                note="GPU memory/util/power are whole-device samples, not exclusive per-job attribution."))
            time.sleep(5)
    write(OUT / "runtime.json", dict(command=cmd, exit_code=p.returncode,
        elapsed_s=time.time()-t0, started_unix=t0, ended_unix=time.time(),
        includes="decode/reencode/inference/save/evaluation, serial three videos"))
    if p.returncode:
        raise RuntimeError("Baseline failed; see baseline_run.log")


def metric(tp, fp, fn):
    return dict(TP=tp, FP=fp, FN=fn, precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)


def evaluate():
    source = {s["id"]: s for s in read(IMPORT)["samples"]}
    results = read(OUT / "baseline/results.json")
    rows, summaries = [], []
    for s in results["samples"]:
        truth, events = s["truth"], s["events"]
        raw = read(OUT / f"baseline/{s['id']}/raw_track.json")
        legacy = raw["detections_meta"]["legacy_shots"]
        if legacy["config"]["score"]["make_window_from_crossing"]:
            raise ValueError("Unexpected enabled crossing-window experiment")
        pairs = match_times([x["release_s"] for x in truth], [x["release_s"] for x in events], 1.5)
        m = {i: j for i, j, _ in pairs}
        used = set(m.values())
        made_tp = sum(truth[i]["result"] == "made" and events[j]["result"] == "made" for i, j, _ in pairs)
        made_fp = sum(e["result"] == "made" for e in events) - made_tp
        made_fn = sum(t["result"] == "made" for t in truth) - made_tp
        local = []
        for i, t in enumerate(truth):
            j = m.get(i)
            e = events[j] if j is not None else None
            note = t.get("note", "")
            typ = ("free_throw" if t["is_free_throw"] else "blocked" if "盖" in note else
                   "putback" if "补" in note else "layup" if "上篮" in note else
                   "three_point" if t.get("value") == 3 else "other_or_unspecified")
            row = dict(sample=s["id"], truth_id=t["id"], truth_t=t["release_s"],
                truth_result=t["result"], is_replay=t["is_replay"], play_id=t["play_id"], event_type=typ,
                event_index=j, model_t=e["release_s"] if e else None,
                model_result=e["result"] if e else None, shot="TP" if e else "FN",
                made=("TP" if e and e["result"]=="made" else "FN") if t["result"]=="made"
                     else ("FP" if e and e["result"]=="made" else None),
                delta_s=abs(t["release_s"]-e["release_s"]) if e else None,
                non_shot_subtype=None, source_sha256=source[s["id"]]["source_sha256"],
                original_full_game_time=None,
                original_video=source[s["id"]]["video"], model=e,
                frame_index_status="not fabricated; timestamps in reviewed video",
                matching_reason="maximum one-to-one chronological matching at ±1.5s")
            local.append(row)
        for j, e in enumerate(events):
            if j not in used:
                local.append(dict(sample=s["id"], truth_id=None, truth_t=None, truth_result=None,
                    event_index=j, model_t=e["release_s"], model_result=e["result"], shot="FP",
                    made="FP" if e["result"]=="made" else None, non_shot_subtype="PENDING_REVIEW",
                    original_video=source[s["id"]]["video"], source_sha256=source[s["id"]]["source_sha256"],
                    original_full_game_time=None, model=e,
                    matching_reason="unmatched in human-declared fully audited interval; physical subtype unconfirmed"))
        for row in local:
            t = row.get("truth_t") if row.get("truth_t") is not None else row["model_t"]
            window = [f for f in legacy["frames"] if max(0, t-1) <= f["t"] <= t+3]
            row["diagnostic_window_s"] = [max(0, t-1), min(raw["duration"], t+3)]
            row["frame_index_estimate"] = round(t * raw["fps"])
            row["frame_index_status"] = "estimate from current clip fps; full-game frame UNKNOWN"
            row["evidence_coverage"] = dict(sampled=len(window),
                real_selected_ball=sum(bool(f["ball"]) and not f["ball"].get("predicted") for f in window),
                predicted_ball=sum(bool(f["ball"]) and f["ball"].get("predicted") for f in window),
                fresh_rim=sum(bool((f.get("tracked_rim") or {}).get("fresh")) for f in window),
                cuts=sum(bool(f.get("cut")) for f in window))
            idx = row.get("event_index")
            row["full_engine_event"] = legacy["events"][idx] if idx is not None else None
            row["nearby_events_not_rematched"] = [e for e in events if abs(e["release_s"]-t) <= 3]
            row["raw_trace"] = f"baseline/{s['id']}/raw_track.json"
        by_type = {}
        for typ in sorted({r.get("event_type") for r in local if r.get("event_type")}):
            group = [r for r in local if r.get("event_type") == typ]
            by_type[typ] = dict(truth=len(group), shot_FN=sum(r["shot"]=="FN" for r in group),
                made_FN=sum(r["made"]=="FN" for r in group), made_FP=sum(r["made"]=="FP" for r in group))
        unique = {}
        for r in local:
            if r.get("play_id"):
                unique.setdefault(r["play_id"], []).append(r)
        summaries.append(dict(id=s["id"], appearances=len(truth), engine_events=len(events),
            shots=metric(len(pairs), len(events)-len(pairs), len(truth)-len(pairs)),
            made=metric(made_tp, made_fp, made_fn),
            UNKNOWN=sum(e["result"]=="unknown" for e in events), types=by_type,
            non_shot_false_positive_subtypes=dict(pass_count=None, dribble_count=None, contest_count=None,
                pending_count=len(events)-len(pairs), reason="No complete human non-shot subtype annotations"),
            unique_play_descriptive=dict(total=len(unique),
                detected_in_any_appearance=sum(any(r["shot"]=="TP" for r in g) for g in unique.values()),
                replay_appearances=sum(t["is_replay"] for t in truth),
                warning="Not a replay-deduplicated precision metric; no replay interval truth supplied")))
        rows.extend(local)
    write(OUT / "baseline_metrics.json", dict(tolerance_s=1.5, samples=summaries))
    write(OUT / "event_errors.json", rows)
    with (OUT / "event_errors.csv").open("w", newline="", encoding="utf-8-sig") as f:
        keys = ["sample","truth_id","truth_t","truth_result","event_type","is_replay","play_id",
                "event_index","model_t","model_result","shot","made","delta_s","non_shot_subtype","source_sha256"]
        w = csv.DictWriter(f, keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    before = read(OUT / "protected_before.json")
    after = protected()
    write(OUT / "protected_after.json", dict(unchanged=before==after,
        changed=[k for k in before if before[k] != after.get(k)]))
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run", "evaluate"])
    args = p.parse_args()
    {"prepare": prepare, "run": run_baseline, "evaluate": evaluate}[args.action]()
