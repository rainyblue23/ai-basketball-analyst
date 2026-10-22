"""Render existing traces, with measured/predicted/unknown evidence separate."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import cv2
import numpy as np
from aihoop.highlight import ffmpeg_path
from diagnose_nba_clip import draw_box


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--review-out',type=Path)
    p.add_argument('--source-match-id');p.add_argument('--shadow',type=Path);a=p.parse_args()
    if a.out.exists():p.error('Choose a new video path')
    if a.review_out and (a.review_out.exists() or not a.source_match_id):p.error('New review folder and source-match-id required')
    raw=json.loads(a.raw.read_text());trace=raw['detections_meta']['legacy_shots'];cap=cv2.VideoCapture(raw['video_path'])
    w,h=raw['width'],raw['height'];width=1280;height=round(h*width/w)//2*2
    a.out.parent.mkdir(parents=True,exist_ok=True)
    writer=subprocess.Popen([ffmpeg_path(),'-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height+180}',
        '-r',str(raw['fps']),'-i','-','-an','-c:v','libx264','-crf','23','-preset','veryfast','-pix_fmt','yuv420p','-movflags','+faststart',str(a.out)],stdin=subprocess.PIPE)
    candidates=(trace.get('release_shadow') or {}).get('candidates',[]);tasks=[]
    if a.shadow:
        from collect_cv_baseline import sha256
        scored=json.loads(a.shadow.read_text())
        if scored['input_raw_sha256']!=sha256(a.raw):raise ValueError('Rescoring trace SHA mismatch')
        candidates=scored['candidates']
    try:
        for row in trace['frames']:
            ok,original=cap.read()
            if not ok:raise RuntimeError(f"Missing original frame {row['frame']}")
            image=original.copy()
            roles={str(r['track_id']):r for r in row.get('player_roles',[])}
            for person in row.get('head_context') or row.get('persons',[]):
                role=roles.get(str(person.get('track_id'))) or {}
                draw_box(image,person['xyxy'],(160,160,160),f"{person.get('track_id')} {role.get('role','UNKNOWN')} {role.get('confidence',0):.2f}")
            for c in row.get('ball_candidates',[]):
                if c['cls']=='motion_ball':continue
                draw_box(image,c['xyxy'],(0,220,0) if c['selection_reason']=='selected' else (0,0,255),c['selection_reason'])
            ball=row.get('ball') or {}
            if ball.get('predicted'):draw_box(image,ball['xyxy'],(0,220,255),'PREDICTED not a measurement')
            rim=row.get('tracked_rim') or {};status=rim.get('status','LOST')
            if rim and status!='LOST':
                x,y,rw,rh=[rim[k] for k in ('cx','cy','w','h')]
                draw_box(image,[x-rw/2,y-rh/2,x+rw/2,y+rh/2],(0,220,255) if status=='PREDICTED' else (255,140,0) if rim.get('measured_at_t') else (140,140,140),status)
            image=cv2.resize(image,(width,height));panel=np.zeros((180,width,3),np.uint8)
            recent=[c for c in candidates if c['created_t']<=row['t']<=c['created_t']+1.2]
            line=[f"F{row['frame']} t={row['t']:.3f}s BALL={row.get('ball_state','legacy')} RIM={status} accepted_now={rim.get('measured_at_t',False)}",
                f"Formal engine={row.get('shot_state')} | last observed release phase={row.get('release_phase','disabled')} | camera verified={(row.get('camera_motion') or {}).get('ok',False)}",
                'Offline candidate review: '+ '; '.join(f"{c['candidate_id']} {c['shot_type']} {c['candidate_state']}" for c in recent[-2:]),
                'Green=model measurement; Red=rejected model candidate; Yellow=prediction. NO PRECISION CLAIM / NO HUMAN TRUTH.',
                'Ball rejection reasons: '+str(dict(Counter(c['selection_reason'] for c in row.get('ball_candidates',[]) if c['cls']!='motion_ball')))]
            for i,text in enumerate(line):cv2.putText(panel,text[:180],(10,26+i*33),0,.53,(230,230,230),1)
            writer.stdin.write(np.vstack((image,panel)).tobytes())
            if a.review_out:
                group=row['frame']//90;key=f'review_{group:02d}';folder=a.review_out/key;folder.mkdir(parents=True,exist_ok=True)
                name=f"frame_{row['frame']:06d}.jpg";cv2.imwrite(str(folder/name),original)
                if not tasks or tasks[-1]['id']!=key:
                    tasks.append(dict(id=key,video=raw['video_path'],source_match_id=a.source_match_id,
                        start_s=row['t'],end_s=row['t'],frame_times={},split='Development',review_status='pending',
                        title=f'{a.source_match_id} review'))
                tasks[-1]['end_s']=row['t']+1/raw['fps'];tasks[-1]['frame_times'][name]=row['t']
    finally:cap.release();writer.stdin.close();code=writer.wait()
    if code:raise RuntimeError(f'ffmpeg exit {code}')
    if a.review_out:
        for task in tasks:task.update(view_start_s=max(0,task['start_s']-3),view_end_s=min(raw['duration'],task['end_s']+4))
        (a.review_out/'manifest.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2))
    print(json.dumps({'video':str(a.out),'frames':len(trace['frames']),'review_tasks':len(tasks)}))


if __name__=='__main__':main()
