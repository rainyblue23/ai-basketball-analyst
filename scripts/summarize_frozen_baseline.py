"""Summarize a frozen event baseline without rerunning video inference."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    truth_bytes = args.truth.read_bytes()
    truth_sha = hashlib.sha256(truth_bytes).hexdigest()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if baseline.get("truth_sha256") != truth_sha:
        raise SystemExit(
            f"truth hash mismatch: baseline={baseline.get('truth_sha256')} current={truth_sha}"
        )

    totals = Counter()
    confusion: Counter[tuple[str, str]] = Counter()
    made_tp = made_fp = made_fn = 0
    per_sample = []
    for sample in baseline.get("samples", []):
        truth = sample.get("truth", [])
        events = sample.get("events", [])
        pairs = sample.get("pairs", [])
        paired_truth = set()
        paired_events = set()
        for pair in pairs:
            ti, ei = int(pair["truth_index"]), int(pair["event_index"])
            paired_truth.add(ti)
            paired_events.add(ei)
            tr = str(truth[ti].get("result", "unknown"))
            pr = str(events[ei].get("result", "unknown"))
            confusion[(tr, pr)] += 1
            if pr == "made":
                made_tp += int(tr == "made")
                made_fp += int(tr != "made")
            elif tr == "made":
                made_fn += 1
        for i, event in enumerate(events):
            if i not in paired_events and event.get("result") == "made":
                made_fp += 1
        for i, shot in enumerate(truth):
            if i not in paired_truth and shot.get("result") == "made":
                made_fn += 1

        row = {
            "id": sample.get("id"),
            "truth_shots": len(truth),
            "engine_events": len(events),
            "matched": len(pairs),
            "missed": len(truth) - len(pairs),
            "extra": len(events) - len(pairs),
            "unknown_matched": sum(
                1 for pair in pairs
                if events[int(pair["event_index"])].get("result") == "unknown"
            ),
        }
        per_sample.append(row)
        totals.update(row)

    tp, fp, fn = totals["matched"], totals["extra"], totals["missed"]
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else None
    made_precision, made_recall = ratio(made_tp, made_tp + made_fp), ratio(made_tp, made_tp + made_fn)
    made_f1 = (
        round(2 * made_precision * made_recall / (made_precision + made_recall), 4)
        if made_precision and made_recall else None
    )
    result = {
        "truth_sha256": truth_sha,
        "baseline": str(args.baseline),
        "parameters": baseline.get("parameters", {}),
        "event_detection": {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
        },
        "made_end_to_end": {
            "tp": made_tp, "fp": made_fp, "fn": made_fn,
            "precision": made_precision, "recall": made_recall, "f1": made_f1,
        },
        "matched_outcome_confusion": {
            f"{truth_result}->{pred_result}": count
            for (truth_result, pred_result), count in sorted(confusion.items())
        },
        "per_sample": per_sample,
        "limits": baseline.get("limits", []),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
