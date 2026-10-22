"""Render before/experimental population windows from measured evidence.

Windows are derived from abnormal samples, not video-specific timestamps.
The experimental panel uses exactly the same source boxes; no ground truth.
"""
import argparse
import bisect
import json
import math
import subprocess
from pathlib import Path

from aihoop.highlight import ffmpeg_path


def main():
    import cv2
    import numpy as np
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--experiment',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--max-windows',type=int,default=4)
    p.add_argument('--identity-audit',type=Path,help='Optional tracklet audit; show original versus aliased IDs')
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False)
    raw=json.loads(a.raw.read_text())
    e=json.loads((a.experiment/'evidence.json').read_text())
    identity=json.loads(a.identity_audit.read_text()) if a.identity_audit else None
    if identity:
        windows=[[max(0,r['end_t']-.7),min(raw['duration'],r['start_t']+.7)]
                 for r in identity.get('accepted_links',[])[:a.max_windows]]
    else:
        before=json.loads((a.experiment/'observed.json').read_text())
        bad=[f['t'] for f in before if f.get('population_quality',{}).get('valid') is False]
        windows=[]
        for t in bad:
            if windows and t-windows[-1][1]<=1.5: windows[-1][1]=t
            else: windows.append([t,t])
        windows=sorted(windows,key=lambda w:-(w[1]-w[0]))[:a.max_windows]
        windows=sorted([[max(0,s-1),min(raw['duration'],end+1)] for s,end in windows])
    assignments=e['teams'].get('assignments',{})
    groups={pid:r.get('team','unknown') for pid,r in assignments.items()}
    for source,target in (identity or {}).get('aliases',{}).items():
        if groups.get(target,'unknown')=='unknown' and groups.get(source) in ('home','away'):
            groups[target]=groups[source]
    evidence=e['frames'];stamps=[r['t'] for r in evidence]
    cap=cv2.VideoCapture(raw['video_path'])
    clips=[]
    for index,(start,end) in enumerate(windows):
        target=a.out/f'population_{index+1:02d}.mp4'
        writer=subprocess.Popen([ffmpeg_path(),'-v','error','-n','-f','rawvideo','-pix_fmt','bgr24',
            '-s','1280x430','-r','12','-i','-','-an','-c:v','libx264','-preset','veryfast',
            '-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
        try:
            for output_frame in range(math.ceil((end-start)*12)):
                fi=round((start+output_frame/12)*raw['fps'])
                cap.set(cv2.CAP_PROP_POS_FRAMES,fi)
                ok,img=cap.read()
                if not ok: raise RuntimeError(f'Frame {fi} decode failed')
                t=fi/raw['fps']
                k=bisect.bisect_left(stamps,t)
                candidates=[j for j in (k-1,k) if 0<=j<len(evidence)]
                row=min((evidence[j] for j in candidates),key=lambda r:abs(r['t']-t)) if candidates else None
                # Never carry pixel boxes through a gap or a cut.
                cuts=[r['t'] for r in raw['detections_meta']['legacy_shots']['frames'] if r.get('cut')]
                if row and (abs(row['t']-t)>.12 or any(min(t,row['t'])<c<=max(t,row['t']) for c in cuts)): row=None
                canvas=np.zeros((430,1280,3),np.uint8)
                for panel in (0,1):
                    picture=cv2.resize(img,(640,360))
                    for person in (row or {}).get('persons',[]):
                        pid=person['player_id'];old=raw['players'].get(pid,{}).get('team','unknown')
                        canonical=(identity or {}).get('aliases',{}).get(pid,pid) if panel else pid
                        team=(groups.get(canonical,'unknown') if identity else assignments.get(pid,{}).get('team','unknown')) if panel else (assignments.get(pid,{}).get('team','unknown') if identity else old)
                        is_ref=panel and person['role']=='REFEREE' and person['role_confidence']>=.8
                        color=(70,70,235) if is_ref else {'home':(235,110,47),'away':(46,118,242)}.get(team,(150,150,150))
                        label=canonical+(' ['+pid+']' if canonical!=pid else '')+(' REF (model)' if is_ref else ' '+({'home':'A','away':'B'}.get(team,'?') if panel or identity else team))
                        box=person['box'];x1,y1,x2,y2=[int(v*s) for v,s in zip(box,(640/raw['width'],360/raw['height'])*2)]
                        cv2.rectangle(picture,(x1,y1),(x2,y2),color,1)
                        cv2.putText(picture,label,(x1,max(10,y1-3)),0,.36,color,1)
                    canvas[50:410,panel*640:(panel+1)*640]=picture
                    title=('Before tracklet association' if panel==0 else 'Experimental alias; same-person identity NOT human verified') if identity else ('Original team labels' if panel==0 else 'Experimental A/B groups; grey=UNKNOWN; red=referee evidence')
                    cv2.putText(canvas,title,(panel*640+8,22),0,.43,(240,240,240),1)
                cv2.putText(canvas,f'Original video t={t:.3f}s F{fi} | measured boxes only | NOT reviewed ground truth',(8,44),0,.43,(180,210,240),1)
                writer.stdin.write(canvas.tobytes())
        finally:
            writer.stdin.close()
            if writer.wait(): raise RuntimeError('Diagnostic video export failed')
        clips.append({'path':str(target),'source_start':start,'source_end':end})
    cap.release()
    (a.out/'manifest.json').write_text(json.dumps({'clips':clips,'human_truth':False,
        'evidence_video_sha256':e['video_sha256'],'raw_sha256':e['raw_sha256']},indent=2))
    print(json.dumps(clips))


if __name__=='__main__':main()
