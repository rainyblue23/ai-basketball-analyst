"""Render 640/1280 cached evidence with the existing diagnostic drawing helper."""
import argparse,json,subprocess
from pathlib import Path
import cv2,numpy as np
from aihoop.highlight import ffmpeg_path
from diagnose_nba_clip import draw_box
from collect_cv_baseline import sha256,write_json


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--experiment',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--review',type=Path,required=True);a=p.parse_args();plans=json.loads(a.plan.read_text());checks=[]
 for w in plans:
  raw=json.loads(Path(w['raw_path']).read_text());video=raw['video_path']
  if sha256(video)!=w['inference_video_sha256']:raise ValueError('Source identity mismatch')
  traces={size:json.loads((a.experiment/f"{w['id']}_{size}/window.json").read_text()) for size in (640,1280)}
  byid={size:{f['frame']:f for f in d['frames']} for size,d in traces.items()};assert list(byid[640])==list(byid[1280]);folder=a.review/w['id']
  for size,rows in byid.items():write_json(folder/f'evidence{size}.json',{f'frame_{i:06d}.jpg':f for i,f in rows.items()})
  target=a.experiment/f"{w['id']}_640_1280.mp4"
  if target.exists():raise ValueError('Choose new output video')
  cap=cv2.VideoCapture(video);first=next(iter(byid[640]));cap.set(cv2.CAP_PROP_POS_FRAMES,first)
  writer=subprocess.Popen([ffmpeg_path(),'-v','error','-f','rawvideo','-pix_fmt','bgr24','-s','1536x476','-r',str(raw['fps']),'-i','-','-an','-c:v','libx264','-crf','21','-preset','veryfast','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
  try:
   for i in byid[640]:
    ok,im=cap.read()
    if not ok:raise ValueError('Missing original frame')
    sides=[]
    for size in (640,1280):
     row=byid[size][i];canvas=im.copy()
     for b in row.get('ball_candidates',[]):
      if b['cls']=='motion_ball':continue
      draw_box(canvas,b['xyxy'],(0,200,0) if b['selection_reason'] in ('selected','reacquired') else (0,0,255),b['selection_reason'])
     b=row.get('ball')
     if b and b.get('predicted'):draw_box(canvas,b['xyxy'],(0,220,255),'PREDICTED')
     if row.get('rim'):draw_box(canvas,row['rim']['xyxy'],(240,150,0),'RIM')
     canvas=cv2.resize(canvas,(768,432));panel=np.zeros((44,768,3),np.uint8);cv2.putText(panel,f"{size} conf=.25 ROI=off F{i} t={i/raw['fps']:.3f} | ALGORITHM, NOT TRUTH",(8,26),0,.51,(230,230,230),1);sides.append(np.vstack((canvas,panel)))
    writer.stdin.write(np.hstack(sides).tobytes())
  finally:cap.release();writer.stdin.close();rc=writer.wait()
  if rc:raise RuntimeError('ffmpeg failed')
  check=cv2.VideoCapture(str(target));n=int(check.get(cv2.CAP_PROP_FRAME_COUNT));check.release();assert n==len(byid[640]);checks.append({'video':str(target),'frames':n,'sha256':sha256(target),'human_truth':False})
 write_json(a.experiment/'video_checks.json',checks);print(json.dumps(checks))

if __name__=='__main__':main()
