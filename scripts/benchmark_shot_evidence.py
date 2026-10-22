"""Replay the same selected detections through existing ScoreEngine variants.

No model inference, new candidates, scoreboard processing or online job writes.
This isolates event logic, not detector accuracy or end-to-end recovery.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import time

from collect_cv_baseline import freeze, write_json
from aihoop.legacy_shots.stream import replay_trace

VARIANTS={
    'legacy':dict(release_binding_mode='legacy_nearest_feet',ball_geometry_mode='median3'),
    'binding':dict(release_binding_mode='contact_sequence',ball_geometry_mode='median3'),
    'measured':dict(release_binding_mode='legacy_nearest_feet',ball_geometry_mode='measured'),
    'combined':dict(release_binding_mode='contact_sequence',ball_geometry_mode='measured')}


def run_variant(trace, options, detect_options=None):
    trace=dict(trace,config=copy.deepcopy(trace['config']))
    trace['config']['score'].update(options)
    trace['config']['detect'].update(detect_options or {})
    return replay_trace(trace)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raws',type=Path,nargs='+',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--rim-current',action='store_true',
        help='Also isolate current measured rim geometry; cached replay has no camera compensation')
    args=parser.parse_args()
    if args.out.exists():parser.error('Choose a new output directory.')
    if any(not p.is_file() for p in args.raws):parser.error('A raw file is missing.')
    args.out.mkdir(parents=True)
    report=dict(scope='fixed measured/predicted detections; development diagnostic, not accuracy',
        revision=freeze(args.out),limits=['No new YOLO/ROI inference; no independent event truth.',
            'All variants enforce uncalibrated points as unverified; legacy is not an unsafe old score policy.',
            'Candidate timeout uses candidate age in all variants; release binding and geometry are isolated.'],runs=[])
    for i,path in enumerate(args.raws):
        data=path.read_bytes();raw=json.loads(data);trace=raw['detections_meta']['legacy_shots']
        identity=dict(raw=str(path),sha256=hashlib.sha256(data).hexdigest(),video=raw['video_path'])
        variants=[(name,options,{}) for name,options in VARIANTS.items()]
        if args.rim_current:
            from aihoop.legacy_shots.settings import GeneralVisionOptions
            general=GeneralVisionOptions(**trace['config']['detect'].get('general',{})).model_dump()
            variants.extend([('cached_original',{},{}),('rim_current',{},dict(general={**general,'dynamic_rim':True}))])
        for name,options,detect_options in variants:
            start=time.perf_counter();events=run_variant(trace,options,detect_options)
            row=dict(**identity,variant=name,options=options,detect_options=detect_options,
                camera_compensation=False,seconds=time.perf_counter()-start,
                frames=len(trace['frames']),event_results=dict(Counter(e['result'] for e in events)),
                events=events,cached_original_events=trace['events'],
                assigned_events=sum(e.get('player_id') is not None for e in events),
                known_releases=sum(e.get('release_known',False) for e in events))
            write_json(args.out/f'{i:02d}_{name}.json',row);report['runs'].append(row)
            write_json(args.out/'comparison.json',report)
            print(json.dumps({k:v for k,v in row.items() if k not in ('events','cached_original_events')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
