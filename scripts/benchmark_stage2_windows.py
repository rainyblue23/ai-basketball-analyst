"""Offline single-factor window experiments and bounded high-res budget planning.
Human annotation files are never loaded. Counts are observations, not accuracy.
"""
import argparse,json,time,math
from pathlib import Path
from collections import Counter
import cv2
import torch
from collect_cv_baseline import freeze,sha256,write_json
from experiment_score_recovery import reanalyze
from aihoop.legacy_shots.settings import resolve_detect


def budget_windows(frames, events, fps, *, score_facts=(), max_seconds=6., max_windows=3., pad_s=.7):
    """Propose optional windows from algorithm evidence, with a hard decoded-frame budget.
    No annotations, filename, team, fixed event time or known result is consulted.
    """
    triggers=[]
    for e in events:
        t=e.get('release_t',e.get('t'));t=float(t) if t is not None else None
        if t is not None:triggers.append((t,'forward_candidate'))
    for f in frames:
        rim=f.get('tracked_rim') or {};ball=f.get('ball')
        if rim.get('fresh') and (ball is None or ball.get('predicted')):
            # Only a recent measured near-rim ball makes missing observations
            # actionable; a rim alone would trigger essentially the whole game.
            recent=[r for r in frames[max(0,f['frame']-6):f['frame']] if r.get('ball') and not r['ball'].get('predicted')]
            if any(abs((r['ball']['xyxy'][0]+r['ball']['xyxy'][2])/2-rim.get('cx',-1e9))<4*rim.get('w',0) for r in recent):
                triggers.append((f['t'],'near_rim_observation_gap'))
    for fact in score_facts:
        if fact.get('delta') in (2,3):triggers.append((fact['t']-3.,'stable_display_change_only'))
    chosen=[];used=set();cap=max(0,int(max_seconds*fps))
    for t,reason in sorted(triggers):
        first=max(0,math.floor((t-pad_s)*fps));end=min(len(frames)-1,math.ceil((t+pad_s)*fps));indices=set(range(first,end+1))
        if not indices or indices<=used:continue
        if len(chosen)>=max_windows or len(used|indices)>cap:continue
        chosen.append({'start_frame':first,'end_frame':end,'reason':reason});used|=indices
    return {'enabled':False,'windows':chosen,'selected_frame_count':len(used),'hard_frame_budget':cap,'max_windows':max_windows,'formal_statistics_write':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=False);revision=freeze(a.out);plan=json.loads(a.plan.read_text());model_path=Path('models/BODD_yolov8n_0001.pt')
    from ultralytics import YOLO
    import numpy as np
    model=YOLO(str(model_path));original=model.predict;metrics=[]
    for size in (640,1280):original(np.zeros((1080,1920,3),dtype='uint8'),imgsz=size,conf=.25,device=0,verbose=False)
    def measured(*args,**kwargs):
        torch.cuda.synchronize();start=time.perf_counter();result=original(*args,**kwargs);torch.cuda.synchronize()
        metrics.append({'predict_wall_ms':(time.perf_counter()-start)*1000,'reported_inference_ms':sum(float(r.speed['inference']) for r in result)})
        return result
    model.predict=measured
    runs=[];inputs={}
    for wi,w in enumerate(plan):
        raw_path=Path(w['raw_path']);raw=json.loads(raw_path.read_text());video=Path(raw['video_path']);digest=sha256(video)
        if w['inference_video_sha256']!=digest:raise ValueError('Input SHA mismatch')
        frames=raw['detections_meta']['legacy_shots']['frames'];cache={f['frame']:f for f in frames};fps=raw['fps'];input_key=str(raw_path)
        if input_key not in inputs:
            inputs[input_key]={'video':str(video),'video_sha256':digest,'raw_sha256':sha256(raw_path),'budget_plan':budget_windows(frames,raw['detections_meta']['legacy_shots']['events'],fps)}
        # Alternate order to avoid attributing every warm-state effect to 1280.
        for size in ((640,1280) if wi%2==0 else (1280,640)):
            options={'imgsz':size,'ball_conf':.25,'ball_candidate_conf':.25,'ball_roi_recovery':False,'ball_rim_recovery':False}
            metrics.clear();torch.cuda.reset_peak_memory_stats();cpu_start=time.process_time();start=time.perf_counter()
            result=reanalyze(video,{'start_s':w['start_s'],'end_s':w['end_s']},model,options,cache,{})
            seconds=time.perf_counter()-start;cpu=time.process_time()-cpu_start;folder=a.out/f"{w['id']}_{size}";folder.mkdir();write_json(folder/'window.json',result)
            r={'window_id':w['id'],'window_kind':w['kind'],'size':size,'options':resolve_detect(options),'frames':len(result['frames']),'seconds':seconds,'process_cpu_seconds':cpu,'gpu_reported_inference_seconds':sum(m['reported_inference_ms'] for m in metrics)/1000,'synchronized_predict_wall_seconds':sum(m['predict_wall_ms'] for m in metrics)/1000,'peak_torch_allocated':torch.cuda.max_memory_allocated(),'ball_observations':sum(bool(f.get('ball') and not f['ball']['predicted']) for f in result['frames']),'rejections':dict(Counter(b.get('selection_reason') for f in result['frames'] for b in f.get('ball_candidates',[]) if b.get('selection_reason') not in ('selected','reacquired'))),'events':result['events'],'metrics':{'ball_tp':None,'ball_fp':None,'ball_fn':None,'shot_tp':None,'shot_fp':None,'shot_fn':None},'truth_status':'pending_human_review','measure_scope':'decode + full-frame YOLO + existing stream using cached persons/cuts; excludes first-pass persons/OCR, model load/warmup and output rendering'}
            runs.append(r);write_json(a.out/'comparison.json',{'revision':revision,'gpu':torch.cuda.get_device_name(0),'weights_sha256':sha256(model_path),'inputs':inputs,'runs':runs,'human_labels_used_in_inference':False});print(json.dumps({k:r[k] for k in ('window_id','size','seconds','ball_observations','events')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
