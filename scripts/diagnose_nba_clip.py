"""Read cached evidence and render every decoded frame for human review.

This does not manufacture truth or run another event detector. Proposed review
tasks remain pending until a person labels and approves the original images.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

from collect_cv_baseline import freeze,write_json
from aihoop.highlight import ffmpeg_path


def blocking_evidence(row, config):
    """Explain the existing attempt prerequisites, not a new shot decision."""
    ball=row.get('ball');rim=row.get('tracked_rim') or {}
    score=config['score'];real=bool(ball and ball.get('measurement',not ball.get('predicted')))
    reasons=[];geometry={}
    if not real:reasons.append('no_selected_model_measurement')
    if not rim.get('fresh'):reasons.append('rim_unavailable')
    if real and rim.get('fresh'):
        box=ball['xyxy'];x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
        radius=max(rim['w']*score.get('approach_radius_ratio',5.),30.)
        top=rim['cy'] if score.get('strict_shot_gate',False) else rim['cy']+rim['h']/2
        geometry=dict(ball_center=[x,y],rim_center=[rim['cx'],rim['cy']],
                      horizontal_distance=abs(x-rim['cx']),approach_radius=radius,
                      ball_y=y,approach_top=top)
        if abs(x-rim['cx'])>=radius:reasons.append('outside_approach_radius')
        if y>=top:reasons.append('ball_not_above_approach_top')
    if not reasons:reasons=['prerequisites_available_check_active_state']
    candidates=[c for c in row.get('ball_candidates',[]) if c.get('cls')!='motion_ball']
    return dict(frame_id=row['frame'],timestamp=row['t'],selected_measurement=real,
        model_ball_candidates=len(candidates),ball_rejections=dict(Counter(c['selection_reason'] for c in candidates)),
        rim_fresh=bool(rim.get('fresh')),rim_tracker_reason=row.get('tracker_reason'),
        blocking_reasons=reasons,geometry=geometry,shot_state=row.get('shot_state','not_recorded'),
        candidates=candidates,rim_candidates=row.get('rim_candidates',[]),
        persons=row.get('persons',[]),head_context=row.get('head_context',[]),
        rim_refinement=row.get('rim_refinement',[]),shot_evidence=row.get('shot_evidence'),
        ball_roi=row.get('ball_recovery'),rim_roi=row.get('rim_recovery'),cut=bool(row.get('cut')))


def draw_box(image,xyxy,color,label=''):
    box=list(map(round,xyxy));cv2.rectangle(image,tuple(box[:2]),tuple(box[2:]),color,1)
    if label:cv2.putText(image,label,(box[0],max(15,box[1]-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--review',action='store_true')
    parser.add_argument('--rim-pixels',action='store_true',help='Recompute contour rejection diagnostics on original pixels')
    args=parser.parse_args()
    if args.out.exists():parser.error('Choose a new output directory.')
    raw=json.loads(args.raw.read_text());trace=raw['detections_meta']['legacy_shots']
    video=Path(raw['video_path']);args.out.mkdir(parents=True)
    revision=freeze(args.out);cap=cv2.VideoCapture(str(video));w,h=raw['width'],raw['height'];fps=raw['fps']
    output=args.out/'diagnostic.mp4'
    command=[ffmpeg_path(),'-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','bgr24',
        '-s',f'{w}x{h+160}','-r',str(fps),'-i','-','-an','-c:v','libx264',
        '-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(output)]
    writer=subprocess.Popen(command,stdin=subprocess.PIPE)
    evidence=[];tasks=[];current=None
    try:
        for row in trace['frames']:
            ok,original=cap.read()
            if not ok:raise RuntimeError(f"Cannot decode expected frame {row['frame']}")
            info=blocking_evidence(row,trace['config']);evidence.append(info);image=original.copy()
            for person in info['persons']:
                draw_box(image,person['xyxy'],(150,160,160),f"P{person.get('track_id','?')}")
            if args.rim_pixels:
                from aihoop.hoop import refine_rim_candidate
                from aihoop.legacy_shots.stream import unpack
                info['pixel_refinement']=[]
                for candidate in row.get('rim_candidates',[]):
                    if candidate['cls']!='hoop':continue
                    options={**trace['config']['detect'].get('rim_refinement_options',{}),
                             'contour_diagnostics':True}
                    _,audit=refine_rim_candidate(original,unpack(candidate),**options)
                    info['pixel_refinement'].append(audit)
            for c in info['candidates']:
                color=(0,220,0) if c['selection_reason']=='selected' else (0,0,255)
                draw_box(image,c['xyxy'],color,f"{c['conf']:.2f} {c['selection_reason']}")
            if row.get('ball') and row['ball'].get('predicted'):draw_box(image,row['ball']['xyxy'],(0,220,255),'PREDICTED')
            for c in info['rim_candidates']:draw_box(image,c['xyxy'],(255,150,0),c['selection_reason'])
            rim=row.get('tracked_rim') or {}
            if rim:
                x,y,rw,rh=[rim[k] for k in ('cx','cy','w','h')]
                draw_box(image,[x-rw/2,y-rh/2,x+rw/2,y+rh/2],(255,0,255),'TRACKED' if rim['fresh'] else 'STALE')
            for audit in (info['ball_roi'],info['rim_roi']):
                if audit and audit.get('region_px'):draw_box(image,audit['region_px'],(200,200,0),'ROI')
            panel=np.zeros((160,w,3),np.uint8)
            lines=[f"Frame {row['frame']}  t={row['t']:.3f}s | model candidates={info['model_ball_candidates']} selected={info['selected_measurement']} rim={info['rim_fresh']}",
                'BLOCK: '+', '.join(info['blocking_reasons']),
                f"RIM: {info['rim_tracker_reason']} | BALL: {info['ball_rejections']}",
                'Green=model selected; Yellow=prediction; Red=rejected; Blue=rim candidate; Magenta=tracked rim. NO HUMAN TRUTH.']
            for i,line in enumerate(lines):cv2.putText(panel,line,(12,30+i*35),cv2.FONT_HERSHEY_SIMPLEX,.55,(235,235,235),1)
            writer.stdin.write(np.vstack((image,panel)).tobytes())
            if args.review:
                group=row['frame']//90;identity=f'lillard30_{group:02d}';folder=args.out/'review'/identity;folder.mkdir(parents=True,exist_ok=True)
                name=f"frame_{row['frame']:06d}.jpg";cv2.imwrite(str(folder/name),original)
                if current is None or current['id']!=identity:
                    current=dict(id=identity,video=str(video),source_match_id='lillard-buzzer-beater',
                        source_sha256=hashlib.file_digest(video.open('rb'),'sha256').hexdigest(),
                        start_s=row['t'],end_s=row['t']+1/fps,status='pending_human_review',
                        split='development',frame_times={},time_basis='decoded_frame_index_over_nominal_fps',
                        note='Suggested review batch, not shot truth. Rim/person extensions require a sidecar.');tasks.append(current)
                current['end_s']=row['t']+1/fps
                current['frame_times'][name]=row['t']
    finally:
        cap.release();writer.stdin.close();code=writer.wait()
    if code:raise RuntimeError(f'Diagnostic ffmpeg failed: {code}')
    with (args.out/'frames.jsonl').open('w') as f:
        for row in evidence:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    with (args.out/'frames.csv').open('w',newline='') as f:
        fields=['frame_id','timestamp','selected_measurement','model_ball_candidates','rim_fresh','rim_tracker_reason','blocking_reasons','ball_rejections'];writer_csv=csv.DictWriter(f,fieldnames=fields);writer_csv.writeheader()
        writer_csv.writerows({k:json.dumps(r[k],ensure_ascii=False) if isinstance(r[k],(list,dict)) else r[k] for k in fields} for r in evidence)
    if args.review:
        duration=len(evidence)/fps
        for task in tasks:
            task['view_start_s']=max(0.,task['start_s']-3.)
            task['view_end_s']=min(duration,task['end_s']+4.)
        write_json(args.out/'review/manifest.json',tasks)
    summary=dict(revision=revision,video=str(video),video_sha256=hashlib.file_digest(video.open('rb'),'sha256').hexdigest(),
        raw=str(args.raw),raw_sha256=hashlib.file_digest(args.raw.open('rb'),'sha256').hexdigest(),
        frames=len(evidence),blocked=dict(Counter(reason for r in evidence for reason in r['blocking_reasons'])),
        ball_rejections=dict(Counter(reason for r in evidence for reason,n in r['ball_rejections'].items() for _ in range(n))),
        events=trace['events'],human_truth_available=False,review_tasks=len(tasks),diagnostic_video=str(output))
    write_json(args.out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
