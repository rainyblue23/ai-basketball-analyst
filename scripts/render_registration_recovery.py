"""Export a small registration evidence set and one optional manual-view task.

Review timestamps select diagnostic material only; inference never reads them.
"""
import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from collect_cv_baseline import ROOT,sha256,write_json
from aihoop.frame_reader import FrameReader
from aihoop.court import Calibration
from aihoop.calibcheck import _court_polylines
from aihoop.court_geometry import infer_standard
from aihoop.highlight import ffmpeg_path


def overlay(image,cal,width,height):
    canvas=image.copy();sx=canvas.shape[1]/width;sy=canvas.shape[0]/height
    sign=1 if sum(p[1] for p in cal.dst_m)>0 else -1
    for line in _court_polylines(half=.5,standard=infer_standard(cal.dst_m)).values():
        pts=np.asarray([cal.to_pixel(x,sign*abs(y)) for x,y in line])*[sx,sy]
        if np.isfinite(pts).all():
            cv2.polylines(canvas,[np.clip(pts,-10000,10000).astype(np.int32)],False,(255,255,0),1)
    return canvas


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True);p.add_argument('--experiment',type=Path,required=True)
    p.add_argument('--calibration',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--review-time',type=float,required=True);p.add_argument('--negative-time',type=float,action='append',default=[])
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    raw=json.loads(a.raw.read_text());audit=json.loads((a.experiment/'registration_audit.json').read_text())
    recovered={r['t']:r for r in audit['frames'] if r['matched']}
    old={r['t']:r for r in raw['detections_meta']['marked_projection']['frames']}
    positive=[t for t in sorted(recovered) if abs(t*2-round(t*2))<1e-6 and not old[t]['matched']][:4]
    cases=[dict(t=t,kind='recovery_candidate') for t in positive]
    cases += [dict(t=a.review_time,kind='reference_view_review_required')]
    cases += [dict(t=t,kind='engineering_negative_review') for t in a.negative_time]
    # Frames are decoded from the exact hashed analysis video, not a still
    # generated from the projected diagram.
    cap=cv2.VideoCapture(raw['video_path']);reader=FrameReader(cap);clips=[]
    for index,case in enumerate(cases,1):
        t=case['t'];start=max(0,t-.5);end=min(raw['duration'],t+.5)
        target=a.out/f'case_{index:02d}.mp4'
        writer=subprocess.Popen([ffmpeg_path(),'-v','error','-n','-f','rawvideo','-pix_fmt','bgr24',
            '-s','1280x410','-r','12','-i','-','-an','-c:v','libx264','-preset','veryfast',
            '-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
        try:
            for i in range(math.ceil((end-start)*12)):
                fi=round((start+i/12)*raw['fps']);ok,image=reader.read(fi)
                if not ok:raise RuntimeError(f'Failed to decode F{fi}')
                time_s=fi/raw['fps'];query=round(time_s*4)/4;picture=cv2.resize(image,(640,360))
                canvas=np.zeros((410,1280,3),np.uint8);canvas[50:,0:640]=picture
                row=recovered.get(query)
                if row:
                    cal=Calibration(H=row['H'],dst_m=row['dst_m'],frame='full')
                    picture=overlay(picture,cal,raw['width'],raw['height'])
                canvas[50:,640:]=picture
                cv2.putText(canvas,'Original frame; no artificial player positions',(8,20),0,.48,(245,245,245),1)
                cv2.putText(canvas,'Recovered floor (cyan)' if row else 'No recovered calibration for this frame',(648,20),0,.48,(245,245,245),1)
                cv2.putText(canvas,f't={time_s:.3f}s F{fi} | measured geometry; NOT reviewed accuracy',(8,43),0,.48,(120,220,250),1)
                writer.stdin.write(canvas.tobytes())
        finally:
            writer.stdin.close()
            if writer.wait():raise RuntimeError('FFmpeg diagnostic export failed')
        clips.append(dict(file=target.name,source_start_s=start,source_end_s=end,**case))
        fi=round(t*raw['fps']);ok,image=reader.read(fi)
        if not ok:raise RuntimeError('Still frame decode failed')
        cv2.imwrite(str(a.out/f'case_{index:02d}_original.jpg'),image)
        if t in recovered:
            row=recovered[t];cal=Calibration(H=row['H'],dst_m=row['dst_m'],frame='full')
            cv2.imwrite(str(a.out/f'case_{index:02d}_overlay.jpg'),overlay(image,cal,raw['width'],raw['height']))
    reference=json.loads(a.calibration.read_text())
    for label,frame in zip(('A','B'),reference['source_frames']):
        ok,image=reader.read(round(frame['t']*raw['fps']))
        if not ok:raise RuntimeError('Reference decode failed')
        cv2.imwrite(str(a.out/('reference_'+label+'.jpg')),image)
    fi=round(a.review_time*raw['fps']);ok,image=reader.read(fi)
    if not ok:raise RuntimeError('Review decode failed')
    cv2.imwrite(str(a.out/'new_view.jpg'),image);cap.release()
    task=dict(task_id='additional_court_view_01',source_match_id='yang-retry2',split='Development',
        video_sha256=sha256(raw['video_path']),source_frame=fi,source_timestamp_nominal_s=fi/raw['fps'],
        timestamp_basis='zero-based decoded frame / nominal FPS; original VFR PTS not independently reviewed',
        image='new_view.jpg',image_sha256=sha256(a.out/'new_view.jpg'),width=raw['width'],height=raw['height'],
        calibration_sha256=sha256(a.calibration),reference_side='UNKNOWN',review_status='pending',
        normalized_points={},training_approved=False,inference_reads_this_file=False)
    write_json(a.out/'registration_task.json',task)
    html=(ROOT/'web/registration-review.html').read_text().replace('href="./"','href="../"')
    (a.out/'registration-review.html').write_text(html)
    write_json(a.out/'manifest.json',dict(clips=clips,review_task='registration_task.json',
        raw_sha256=sha256(a.raw),video_sha256=task['video_sha256'],human_ground_truth=False,
        diagnostics_only=True,model_or_training_changes=False))
    print(json.dumps(clips,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
