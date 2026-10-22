"""Run the existing ball/rim ROI switches on isolated, identical video inputs.

No training, online job writes, manual shot imports or scoreboard fusion. Counts
are observation diagnostics, never accuracy estimates without event truth.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

from collect_cv_baseline import environment_model_paths, freeze, inventory, write_json
from aihoop.court import Calibration
from aihoop.sources import VideoSource

MODES={'none':(False,False),'ball':(True,False),'rim':(False,True),'both':(True,True)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--videos',type=Path,nargs='+',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--modes',nargs='+',choices=list(MODES),default=list(MODES))
    parser.add_argument('--device',default='0')
    parser.add_argument('--detect-options',type=Path)
    parser.add_argument('--ball-weights',type=Path)
    args=parser.parse_args()
    if args.out.exists():parser.error('Choose a new output directory.')
    if any(not video.is_file() for video in args.videos):parser.error('An input video is missing.')
    if args.ball_weights and not args.ball_weights.is_file():parser.error('Explicit weights do not exist.')
    from aihoop.legacy_shots.settings import LegacyDetectOptions
    base_detect=LegacyDetectOptions(**(json.loads(args.detect_options.read_text()) if args.detect_options else {})).model_dump()
    args.out.mkdir(parents=True)
    revision=freeze(args.out);settings=environment_model_paths();inv=inventory(args.out,settings)
    active_weights=str(args.ball_weights.resolve()) if args.ball_weights else inv['selected_ball_weights']
    write_json(args.out/'inventory.json',dict(inv,revision=revision,active_ball_weights=active_weights,
        active_ball_sha256=hashlib.file_digest(Path(active_weights).open('rb'),'sha256').hexdigest()))
    report={'scope':'development diagnostic, no accuracy claim', 'settings':{
        'device':args.device,'scoreboard':False,'auto_sliding':False,'calibration':'unavailable',
        'detect_players':True,'player_stride':2,'shot_engine':'legacy'},'runs':[]}
    for vi,video in enumerate(args.videos):
        digest=hashlib.file_digest(video.open('rb'),'sha256').hexdigest()
        for mode in args.modes:
            folder=args.out/f'{vi:02d}_{video.stem}_{mode}';folder.mkdir()
            ball,rim=MODES[mode]
            config={**base_detect,'ball_roi_recovery':ball,'ball_rim_recovery':rim}
            source=VideoSource(str(video.resolve()),Calibration(method='unavailable'),
                weights=inv['selected_player_weights'],ball_weights=active_weights,
                hoop_weights=inv['selected_hoop_weights'],device=args.device,
                scoreboard=False,auto_sliding=False,detect_players=True,player_stride=2,
                legacy_detect=config,score_policy='court')
            started=time.perf_counter();last=None
            def progress(p,message):
                nonlocal last
                if message!=last:
                    print(f'{video.name} {mode} {time.perf_counter()-started:.1f}s {message}',flush=True)
                    last=message
            raw=source.run(progress=progress);seconds=time.perf_counter()-started
            raw.save(str(folder/'raw_track.json'))
            meta=raw.detections_meta;trace=meta['legacy_shots'];frames=trace['frames']
            row={'video':str(video),'video_sha256':digest,'mode':mode,'legacy_detect':config,
                 'source_options':report['settings'],'seconds':seconds,'frames':len(frames),
                 'processing_fps':len(frames)/seconds,'duration':raw.duration,
                 'ball_frames':trace['real_ball_frames'],
                 'rim_usable_frames':trace['rim_tracking']['availability']['usable_frames'],
                 'ball_roi_calls':meta.get('ball_roi_recovery_frames',0),
                 'rim_roi_calls':meta.get('ball_rim_recovery_frames',0),
                 'cascade_calls':meta.get('ball_cascade_frames',0),
                 'events':trace['events'],'event_results':dict(Counter(e['result'] for e in trace['events'])),
                 'ball_rejections':dict(Counter(c['selection_reason'] for f in frames for c in f.get('ball_candidates',[]))),
                 'cut_frames':sum(bool(f.get('cut')) for f in frames),
                 'prevented_cuts':sum(not f['is_cut'] for f in meta.get('scene_motion_checks',[])),
                 'ball_weights':active_weights,'raw_path':str(folder/'raw_track.json')}
            write_json(folder/'metrics.json',row);report['runs'].append(row)
            write_json(args.out/'comparison.json',report)
            print(json.dumps({k:v for k,v in row.items() if k not in ('events','ball_rejections','source_options')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
