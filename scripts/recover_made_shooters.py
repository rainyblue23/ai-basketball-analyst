"""Offline made-event -> measured ball chain -> release feet -> court value.

Reuses dense detector/ROI reanalysis and existing scene/person context. Writes
only a new output folder. Never imports API, writes jobs, or enables a policy.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time

from aihoop.made_shooter_recovery import MadeAttributionOptions, recover_made_shooter


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--enable',action='store_true')
    p.add_argument('--redetect',action='store_true')
    p.add_argument('--reverse-redetect',action='store_true')
    p.add_argument('--clips',action='store_true')
    p.add_argument('--calibration',type=Path)
    p.add_argument('--weights',type=Path,default=Path('models/BODD_yolov8n_0001.pt'))
    p.add_argument('--imgsz',type=int,choices=[640,1280],default=1280)
    p.add_argument('--max-events',type=int,default=6)
    a=p.parse_args()
    if not 1<=a.max_events<=12:
        p.error('max-events must be 1..12')
    if (a.redetect or a.clips or a.calibration) and not a.enable:
        p.error('Additional offline processing requires --enable')
    if a.reverse_redetect and not a.redetect:
        p.error('Reverse redetection requires --redetect and its shared inference cache')
    a.out.mkdir(parents=True,exist_ok=False)
    raw_sha=sha(a.raw);raw=json.loads(a.raw.read_text());trace=raw['detections_meta']['legacy_shots']
    options=MadeAttributionOptions(enabled=a.enable)
    made=[(i,e) for i,e in enumerate(trace['events']) if e.get('result')=='made'
          and e.get('type')=='make' and e.get('suggested_made') is None][:a.max_events]
    report=dict(enabled=a.enable,raw=str(a.raw.resolve()),raw_sha256=raw_sha,
        options=asdict(options),selected_events=len(made),runs=[],
        formal_result_changed=False,formal_statistics_changed=False,
        production_policy_enabled=False,human_truth_available=False)
    model=None;projector=None;cache={};video=Path(raw['video_path'])
    if a.enable:
        report['video_sha256']=sha(video)
    if a.redetect:
        if not a.weights.is_file():
            p.error('An already-provisioned model file is required; no automatic download')
        from ultralytics import YOLO
        model=YOLO(str(a.weights));report['model_sha256']=sha(a.weights)
    if a.calibration:
        from aihoop.marked_projection import MarkedProjector
        projector=MarkedProjector(video,a.calibration,raw['width'],raw['height'])
        report['calibration_sha256']=sha(a.calibration)
    # Cache validated ground registration per release timestamp. No stale matrix
    # is carried to another frame when the existing projector cannot match it.
    ground={}
    def at(t):
        if t not in ground:
            ground[t]=projector.at(t)
        return ground[t]
    try:
        for index,event in made:
            begin=time.perf_counter();frames=trace['frames'];dense=None
            if a.redetect:
                from experiment_score_recovery import reanalyze
                anchor=event.get('crossing_t') or event['t']
                window=dict(start_s=max(0,anchor-options.lookback_s),
                            end_s=min(raw['duration'],anchor+.15))
                dense=reanalyze(video,window,model,dict(imgsz=a.imgsz,
                    ball_roi_recovery=True,ball_rim_recovery=True,ball_roi_retry_hz=5),
                    {f['frame']:f for f in trace['frames']},cache)
                # Redetected outcomes are diagnostic only. Attribution anchors
                # remain the original events; new makes never enter statistics.
                frames=dense['frames'];write(a.out/f'event_{index:02d}_dense.json',dense)
                if a.reverse_redetect:
                    from experiment_score_recovery import reanalyze_reverse
                    reverse=reanalyze_reverse(video,window,event,model,
                        dict(imgsz=a.imgsz,ball_roi_recovery=True,ball_rim_recovery=True,ball_roi_retry_hz=5),
                        {f['frame']:f for f in trace['frames']},cache)
                    write(a.out/f'event_{index:02d}_reverse.json',reverse)
                    reverse_by_id={r['frame']:r for r in reverse['frames']}
                    # Same-timestamp detections are alternative observations,
                    # never additional temporal votes or averaged fake boxes.
                    frames=[dict(f,ball_candidates=[*f.get('ball_candidates',[]),
                        *reverse_by_id.get(f['frame'],{}).get('ball_candidates',[])]) for f in frames]
            result=recover_made_shooter(event,frames,raw['width'],options=options,
                players=raw.get('players'),calibration_at=at if projector else None)
            record=dict(original_event_index=index,original_event=event,attribution=result,
                        elapsed_s=time.perf_counter()-begin,
                        new_visual_events=dense['events'] if dense else None)
            if a.clips:
                from aihoop.highlight import ffmpeg_path
                anchor=event.get('crossing_t') or event['t'];start=max(0,anchor-options.lookback_s)
                end=min(raw['duration'],float(event['t'])+.5)
                clip=a.out/f'event_{index:02d}_original.mp4'
                subprocess.run([ffmpeg_path(),'-nostdin','-v','error','-ss',str(start),
                    '-i',str(video),'-t',str(end-start),'-an','-vf','scale=1280:-2',
                    '-c:v','libx264','-preset','fast','-crf','19','-movflags','+faststart',str(clip)],check=True)
                record.update(clip=clip.name,clip_time_mapping=dict(source_start_s=start,original_video_sha256=report['video_sha256']))
            write(a.out/f'event_{index:02d}_attribution.json',record)
            report['runs'].append(record);write(a.out/'report.json',report)
            print(json.dumps(dict(event=index,status=result['status'],reason=result.get('reason'),
                                 player=result.get('player_track_id'),value=result.get('value'))),flush=True)
    finally:
        if projector:
            report['ground_registration_audit']=projector.audit
            projector.close()
    assert sha(a.raw)==raw_sha,'Original raw result changed during offline analysis'
    report['original_raw_unchanged']=True
    write(a.out/'report.json',report)


if __name__=='__main__':
    main()
