"""Freeze the current checkout and collect a reproducible, isolated CV baseline.

Reuses VideoSource/run_pipeline and the reviewed-feedback evaluator. It never
trains, changes defaults, writes human labels, updates jobs or restarts services.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def feedback_metrics(report):
    """Only the evaluator's reviewed, complete-frame subset has a denominator."""
    t = report['totals']
    truth, predictions, tp = (t.get(k, 0) for k in
                             ('ground_truth_boxes', 'predictions', 'matched_iou_50'))
    return {'scope': 'raw_detector_reviewed_development_frames_only',
            'iou_threshold': .5, 'frames': t['frames'], 'truth_boxes': truth,
            'predictions': predictions, 'tp': tp, 'fp': predictions-tp, 'fn': truth-tp,
            'precision': tp/predictions if predictions else None,
            'recall': tp/truth if truth else None,
            'f1': 2*tp/(truth+predictions) if truth+predictions else None,
            'independent_test': False}


def environment_model_paths():
    # Read only path settings, never copy .env or expose credentials.
    keys = {'AIHOOP_MODELS', 'AIHOOP_PLAYER_WEIGHTS', 'AIHOOP_JERSEY_MODEL',
            'AIHOOP_SCOREBOARD_OCR_MODELS'}
    settings = {}
    env_file = ROOT/'.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, sep, value = line.partition('=')
            if sep and name.strip() in keys:
                settings[name.strip()] = value.strip().strip('\"\'')
    for name in keys:
        if name in os.environ:
            settings[name] = os.environ[name]
    return settings


def freeze(out):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT)
    paths = []
    for folder in ('src', 'scripts', 'tests', 'web', 'eval'):
        paths += [p for p in (ROOT/folder).rglob('*') if p.is_file()
                  and p.suffix in ('.py', '.js', '.html', '.css', '.yaml', '.yml', '.json', '.csv', '.md')
                  and '__pycache__' not in p.parts and 'vendor' not in p.parts]
    paths += [ROOT/'data/botsort_reid.yaml']
    paths = sorted({p for p in paths if p.is_file()})
    manifest = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
    with tarfile.open(out/'source_snapshot.tar.gz', 'w:gz') as archive:
        for p in paths:
            archive.add(p, arcname=str(p.relative_to(ROOT)))
    (out/'worktree.patch').write_bytes(git('diff', '--binary', 'HEAD'))
    (out/'git_status.txt').write_bytes(git('status', '--short'))
    write_json(out/'source_manifest.json', manifest)
    return {'head': git('rev-parse', 'HEAD').decode().strip(),
            'dirty': bool(git('status', '--porcelain')), 'source_files': len(manifest),
            'source_manifest_sha256': sha256(out/'source_manifest.json'),
            'snapshot_sha256': sha256(out/'source_snapshot.tar.gz'),
            'note': 'Current dirty worktree; includes the paused scoreboard task, not a pristine Git baseline.'}


def snapshot_feedback(out):
    """Keep exact reviewed labels and images separate from source snapshots."""
    rows = []
    with tarfile.open(out/'feedback_snapshot.tar.gz', 'w:gz') as archive:
        for path in sorted((ROOT/'data/ball_feedback').glob('*/record.json')):
            row = json.loads(path.read_text())
            if not (row.get('training_approved') and row.get('frame_complete')
                    and row.get('review_status') == 'approved'):
                continue
            image = path.parent/row['image']
            for item in (path, image):
                archive.add(item, arcname=str(item.relative_to(ROOT/'data/ball_feedback')))
            rows.append({'id': path.parent.name, 'record_sha256': sha256(path),
                         'image_sha256': sha256(image), 'source_match_id': row['source_match_id']})
    write_json(out/'feedback_snapshot_manifest.json', rows)


def inventory(out, settings):
    import cv2
    import torch
    from ultralytics import YOLO
    from ultralytics.utils import ROOT as ULTRA_ROOT
    from aihoop.api import _pick_ball_weights, _pick_hoop_weights
    from aihoop.legacy_shots.settings import resolve_detect
    from aihoop.legacy_shots.stream import DEFAULT_CONFIG
    for key, value in settings.items():
        os.environ[key] = value
    models = []
    for path in sorted((ROOT/'models').glob('*.pt')):
        model = YOLO(str(path))
        models.append({'path': str(path), 'sha256': sha256(path), 'bytes': path.stat().st_size,
                       'classes': model.names, 'parameters': sum(p.numel() for p in model.model.parameters()),
                       'train_args': {k: model.ckpt.get('train_args', {}).get(k)
                                      for k in ('model', 'data', 'imgsz', 'epochs')}})
    tracker = ULTRA_ROOT/'cfg/trackers/botsort.yaml'
    (out/'installed_botsort.yaml').write_text(tracker.read_text())
    truth = json.loads((ROOT/'eval/ground_truth/match_testset_20261011.json').read_text())
    feedback = [json.loads(p.read_text()) for p in (ROOT/'data/ball_feedback').glob('*/record.json')]
    approved = [r for r in feedback if r.get('training_approved') and r.get('frame_complete')
                and r.get('review_status') == 'approved']
    return {'created_at': datetime.now(timezone.utc).isoformat(), 'python': sys.version,
            'packages': {k: importlib.metadata.version(k) for k in
                         ('ultralytics', 'torch', 'torchvision', 'easyocr', 'numpy', 'scipy')},
            'opencv': cv2.__version__, 'cuda_runtime': torch.version.cuda,
            'cuda_available': torch.cuda.is_available(),
            'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            'models': models, 'selected_ball_weights': _pick_ball_weights(),
            'selected_hoop_weights': _pick_hoop_weights(),
            'selected_player_weights': settings.get('AIHOOP_PLAYER_WEIGHTS', 'yolov8n.pt'),
            'legacy_detect_profile': resolve_detect(), 'legacy_defaults': DEFAULT_CONFIG,
            'old_match_materials': [{'id': s['id'], 'video': s['video'],
                                    'exists': Path(s['video']).is_file(),
                                    'expected_sha256': s.get('source_sha256'),
                                    'truth_shots': len(s.get('shots', []))} for s in truth['samples']],
            'reviewed_feedback': {'all_records': len(feedback), 'approved_complete': len(approved),
                                  'source_ids': sorted({r.get('source_match_id', '') for r in approved}),
                                  'conditions': dict(Counter(c for r in approved for c in r.get('conditions', [])))}}


def probe_video(path):
    from aihoop.highlight import ffprobe_path
    command = [ffprobe_path(), '-v', 'error', '-count_frames', '-show_entries',
               'format=duration:stream=codec_type,codec_name,r_frame_rate,avg_frame_rate,duration,nb_frames,nb_read_frames,time_base',
               '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def smoke(out, args, inv):
    from aihoop.court import Calibration
    from aihoop.sources import VideoSource
    from aihoop.pipeline import PipelineConfig, run_pipeline
    import torch
    probe = probe_video(args.smoke_video)
    write_json(out/'video_probe.json', probe)
    config = {'weights': inv['selected_player_weights'], 'ball_weights': inv['selected_ball_weights'],
              'hoop_weights': inv['selected_hoop_weights'], 'device': args.device,
              'detect_players': True, 'player_stride': 2, 'scoreboard': not args.no_scoreboard,
              'score_policy': 'court', 'auto_sliding': False, 'shot_engine': 'legacy',
              'legacy_detect': {'ball_roi_recovery': False, 'ball_rim_recovery': False}}
    write_json(out/'smoke_config.json', {'video': str(args.smoke_video.resolve()),
               'video_sha256': sha256(args.smoke_video), 'source_options': config,
               'calibration': 'unavailable', 'highlights': False,
               'scope': 'uncalibrated isolated smoke; not calibrated production timing or event accuracy'})
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    begin = time.perf_counter()
    previous = None
    def progress(p, message):
        nonlocal previous
        if message != previous:
            print(f'{time.perf_counter()-begin:.1f}s {message}', flush=True)
            previous = message
    raw = VideoSource(str(args.smoke_video), Calibration(method='unavailable'), **config).run(progress)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    source_seconds = time.perf_counter()-begin
    raw.save(str(out/'raw_track.json'))
    pipeline_begin = time.perf_counter()
    result = run_pipeline(raw, PipelineConfig(out_dir=str(out/'analysis'), make_highlights=False))
    pipeline_seconds = time.perf_counter()-pipeline_begin
    trace = raw.detections_meta.get('legacy_shots', {})
    frames = trace.get('frames', [])
    observations = sum(bool(r.get('ball')) and not r['ball'].get('predicted') for r in frames)
    predicted = sum(bool((r.get('ball') or {}).get('predicted')) for r in frames)
    report = {'source_metadata_duration_s': raw.duration,
              'container_duration_s': float(probe.get('format', {}).get('duration') or 0),
              'decoded_duration_at_nominal_fps_s': len(frames)/raw.fps,
              'input_fps': raw.fps, 'decoded_frames': len(frames),
              'source_seconds': source_seconds, 'pipeline_seconds': pipeline_seconds,
              'total_seconds': source_seconds+pipeline_seconds,
              'source_processing_fps': len(frames)/source_seconds,
              'processing_fps': len(frames)/(source_seconds+pipeline_seconds),
              'measured_ball_frames': observations, 'predicted_ball_frames': predicted,
              'events': len(raw.attempts), 'result_counts': dict(Counter(e.get('result') for e in trace.get('events', []))),
              'peak_allocated_gpu_mb': torch.cuda.max_memory_allocated()/1048576 if torch.cuda.is_available() else None,
              'diagnostics': {k: raw.detections_meta.get(k) for k in
                              ('performance', 'device', 'screen_graphics', 'teams', 'jersey_numbers',
                               'ball_roi_recovery_frames', 'ball_rim_recovery_frames', 'ball_cascade_frames')},
              'limits': ['No complete timed event truth tied to this exact video hash.',
                         'Observation coverage is not detection recall.',
                         'No court calibration; projected tracks/heatmap/tactics may be unavailable.',
                         'Includes source model startup and OCR; excludes inventory, highlights and overlay rendering.',
                         'Feedback GPU inference ran earlier in a separate process; cold/warm startup was not controlled.',
                         'Container frame counts may differ from decoded counts; compare video_probe.json.']}
    write_json(out/'smoke_metrics.json', report)
    print(json.dumps({k: report[k] for k in ('total_seconds', 'processing_fps', 'events', 'result_counts')}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--device', default='0')
    parser.add_argument('--run-feedback', action='store_true')
    parser.add_argument('--smoke-video', type=Path)
    parser.add_argument('--no-scoreboard', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new output directory; previous baselines are immutable.')
    if args.smoke_video and not args.smoke_video.is_file():
        parser.error('Smoke video does not exist.')
    args.out.mkdir(parents=True)
    revision = freeze(args.out)
    settings = environment_model_paths()
    inv = inventory(args.out, settings)
    inv['revision'] = revision
    write_json(args.out/'inventory.json', inv)
    if args.run_feedback:
        snapshot_feedback(args.out)
        destination = args.out/'feedback_detector.json'
        command = [sys.executable, str(ROOT/'scripts/eval_ball_feedback.py'),
                   '--feedback-dir', str(ROOT/'data/ball_feedback'), '--weights', inv['selected_ball_weights'],
                   '--out', str(destination), '--device', args.device, '--imgsz', '640', '--conf', '.25']
        with (args.out/'feedback_evaluator.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        metrics = feedback_metrics(json.loads(destination.read_text()))
        write_json(args.out/'feedback_metrics.json', metrics)
        print(json.dumps(metrics), flush=True)
    if args.smoke_video:
        smoke(args.out, args, inv)
    print('Baseline: '+str(args.out), flush=True)


if __name__ == '__main__':
    main()
