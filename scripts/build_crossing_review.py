"""Five isolated human-review tasks from stored traces, no new inference."""
from pathlib import Path
import json
import subprocess
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crossing_evidence_audit import ROOT, OUT, read, write, sha

CASES = [
    ("game01_001", "s2_hs_game01", 1, 0, 8, "missed", "结果误报"),
    ("game01_015", "s2_hs_game01", 15, 11, 21, "made", "原版漏判／实验命中"),
    ("game03_056", "s2_hs_game03", 56, 52, 63, "missed", "窗口实验新增误报"),
    ("game03_158", "s2_hs_game03", 158, 154, 165, "missed", "结果误报"),
    ("game01_170_identity", "s2_hs_game01", 170, 164, 178, None, "事件身份待确认"),
]


def build():
    ffmpeg = r"E:\ffmpeg-7.1-essentials_build\bin\ffmpeg.exe"
    truth = {s["id"]: s for s in read(ROOT/"eval/ground_truth/shots_split2_20261011.json")["samples"]}
    target = OUT / "review"
    target.mkdir(parents=True, exist_ok=True)
    tasks = []
    cache = {}
    for ident, sample, at, start, end, outcome, purpose in CASES:
        if sample not in cache:
            raw = read(ROOT/f"out/stage2_audit_20261020/current_baseline/{sample}/raw_track.json")
            a = read(ROOT/f"out/crossing_window_20261020/{sample}_A_states.json")
            b = read(ROOT/f"out/crossing_window_20261020/{sample}_B_states.json")
            cache[sample] = (raw, a, b)
        raw, a, b = cache[sample]
        original = Path(truth[sample]["video"])
        if sha(original) != truth[sample]["source_sha256"]:
            raise ValueError("Source SHA changed")
        folder = target / ident
        folder.mkdir(exist_ok=True)
        # Two distinct clips: original pixels for human review; evaluated pixels for trace overlay.
        for name, video in [("original", original), ("evidence", ROOT/raw["video_path"])]:
            dst = folder / (name + ".mp4")
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(start), "-i", str(video), "-t", str(end-start),
                "-an", "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "fast",
                "-crf", "19", "-movflags", "+faststart", str(dst)], check=True)
        frames = []
        exits = {"A": [], "B": []}
        for fa, fb, detector in zip(a, b, raw["detections_meta"]["legacy_shots"]["frames"]):
            if not start <= fa["t"] <= end:
                continue
            states = {}
            for arm, f in [("A", fa), ("B", fb)]:
                at_state = f["after"] or (f["closed"][-1] if f["closed"] else None)
                before = f["before"]
                ball = f["raw_ball"]
                rim = f["tracked_rim"]
                # Observable geometric exit, NOT engine exit or human evidence.
                smoothed = (at_state or {}).get("last_real_xy")
                observed_exit = bool(ball and not ball.get("predicted") and rim["fresh"] and
                    smoothed and smoothed[1] > rim["bottom"] + .6 * rim["h"] and
                    abs(smoothed[0]-rim["cx"]) <= rim["w"])
                if observed_exit:
                    exits[arm].append(f["t"])
                states[arm] = dict(attempt_start=(at_state or {}).get("start_t"),
                    entered_t=(at_state or {}).get("entered_t"),
                    crossing_t=(at_state or {}).get("crossing_t"),
                    exit_t=None, exit_t_reason="engine has no separately persisted exit_t",
                    geometric_exit_sample=observed_exit,
                    entry_deadline=f.get("entry_deadline"), entry_expired=f.get("entry_expired"),
                    rebound=(at_state or {}).get("rim_rebound_seen"),
                    smoothed_xy=smoothed, previous_real_xy=(before or {}).get("last_real_xy"),
                    previous_real_t=(before or {}).get("last_real_t"),
                    events=f["events"])
            frames.append(dict(t=fa["t"], frame=fa["frame"], cut=fa["cut"],
                ball=fa["raw_ball"], rim=fa["raw_rim"], tracked_rim=detector.get("tracked_rim"),
                ball_candidates=detector.get("ball_candidates", []),
                rim_candidates=detector.get("rim_candidates", []),
                tracker_reason=detector.get("tracker_reason"), states=states))
        task = dict(id=ident, sample=sample, truth_release_s=at, existing_truth_result=outcome,
            purpose=purpose, start_s=start, end_s=end, fps=raw["fps"], width=raw["width"], height=raw["height"],
            source_video=str(original), source_sha256=sha(original),
            trace_sha256=sha(ROOT/f"out/stage2_audit_20261020/current_baseline/{sample}/raw_track.json"),
            full_game_time=None, review_status="PENDING_VALIDATION", human_evidence=None,
            questions=["选中的球是否是真球？", "独立框出篮圈开口（不是篮板或检测大框）",
                       "有无真实穿网后下落？", "是否弹框、打板、前后掠过或被遮挡？",
                       "同一出手还是不同事件？（170秒案例必须先确认身份）"],
            original_clip=f"{ident}/original.mp4", evidence_clip=f"{ident}/evidence.mp4",
            trace=f"{ident}/trace.json",
            time_mapping="clip time + start_s = reviewed source seconds; full-match offset UNKNOWN",
            geometric_exit_samples=exits,
            warning="模型实测=检测器输出，不保证是真球；二维crossing不是真实命中真值。")
        write(folder/"trace.json", frames)
        write(folder/"task.json", task)
        tasks.append(task)
    write(target/"tasks.json", tasks)
    shutil.copyfile(ROOT/"web/crossing-evidence-review.html", target/"index.html")
    write(target/"human_review_template.json", [
        dict(task_id=t["id"], source_sha256=t["source_sha256"], status="pending",
             visual_outcome="unknown", event_identity="unknown", selected_ball_correct="unknown",
             opening_correct="unknown", phenomena=[], marks=[], note="") for t in tasks])
    print(target / "index.html")


if __name__ == "__main__":
    build()
