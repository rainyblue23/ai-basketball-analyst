"""Single-factor BoT-SORT native ReID trial on an isolated development window.

No downloads, no model replacement, no production writes. Tracklet counts are
diagnostics, not IDF1 or identity accuracy; no identity labels are consumed.
"""
import argparse
import copy
import json
import time
from collections import defaultdict
from pathlib import Path
import statistics

from collect_cv_baseline import freeze,write_json,sha256


def main():
    import cv2
    import torch
    import yaml
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.nn.modules.head import Detect
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--start',type=float,default=0.)
    p.add_argument('--duration',type=float,default=16.)
    p.add_argument('--imgsz',type=int,default=960)
    p.add_argument('--stride',type=int,default=2)
    p.add_argument('--device',default='0')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False);revision=freeze(a.out)
    raw_sha=sha256(a.raw)
    raw=json.loads(a.raw.read_text());weights=Path(raw['detections_meta']['weights'])
    if not weights.is_file():raise ValueError('Local player model missing; downloads prohibited')
    default=Path(ultralytics.__file__).parent/'cfg/trackers/botsort.yaml'
    config=yaml.safe_load(default.read_text())
    models=[YOLO(str(weights)),YOLO(str(weights))]
    head=models[1].model.model[-1]
    if not isinstance(head,Detect) or getattr(head,'end2end',False):
        raise RuntimeError('Native features unavailable; refuse an external ReID model fallback')
    configs=[copy.deepcopy(config),copy.deepcopy(config)]
    configs[1]['with_reid']=True
    changed=[k for k in configs[0] if configs[0][k]!=configs[1][k]]
    assert changed==['with_reid'] and config['model']=='auto' and not config['with_reid']
    paths=[]
    for name,c in zip(('baseline','native_reid'),configs):
        file=a.out/(name+'.yaml');file.write_text(yaml.safe_dump(c,sort_keys=False));paths.append(file)
    # Warm both complete paths before timing; discard synthetic blank-frame
    # state. The alternating call order reduces first-caller timing bias.
    import numpy as np
    blank=np.zeros((raw['height'],raw['width'],3),np.uint8)
    for i,model in enumerate(models):
        model.track(blank,persist=True,conf=.25,imgsz=a.imgsz,device=a.device,
                    tracker=str(paths[i]),verbose=False)
        for tracker in model.predictor.trackers:tracker.reset()
    cap=cv2.VideoCapture(raw['video_path']);fps=raw['fps'];first=round(a.start*fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES,first)
    count=min(round(a.duration*fps),round(raw['duration']*fps)-first)
    frames=[[],[]];times=[0.,0.];model_speed=[defaultdict(float),defaultdict(float)]
    start=time.perf_counter()
    cuts={round(f['t']*fps) for f in raw['detections_meta']['legacy_shots']['frames'] if f.get('cut')}
    pending_cut=False
    for fi in range(first,first+count):
        ok,image=cap.read()
        if not ok:raise RuntimeError(f'Cannot decode F{fi}')
        pending_cut|=fi in cuts
        if (fi-first)%a.stride:continue
        order=(0,1) if ((fi-first)//a.stride)%2==0 else (1,0)
        for variant in order:
            model=models[variant]
            if pending_cut:
                for tracker in getattr(model.predictor,'trackers',[]) if model.predictor else []:tracker.reset()
            if torch.cuda.is_available():torch.cuda.synchronize()
            begin=time.perf_counter()
            result=model.track(image,persist=True,conf=.25,imgsz=a.imgsz,device=a.device,
                tracker=str(paths[variant]),verbose=False)[0]
            if torch.cuda.is_available():torch.cuda.synchronize()
            times[variant]+=time.perf_counter()-begin
            for k,v in result.speed.items():model_speed[variant][k]+=v
            people=[]
            if result.boxes is not None and result.boxes.id is not None:
                for values in result.boxes.data.cpu().numpy():
                    if result.names.get(int(values[-1]))=='person':
                        people.append({'id':int(values[4]),'box':[float(x) for x in values[:4]],'conf':float(values[5])})
            frames[variant].append({'frame':fi,'t':fi/fps,'persons':people})
        pending_cut=False
    cap.release();runs=[]
    for i,name in enumerate(('baseline','native_reid')):
        write_json(a.out/(name+'.json'),frames[i]);ids=defaultdict(list)
        for frame in frames[i]:
            for person in frame['persons']:ids[person['id']].append(frame['t'])
        runs.append({'variant':name,'frames':len(frames[i]),'person_observations':sum(len(v) for v in ids.values()),
            'temporary_ids':len(ids),'median_id_span_s':statistics.median(v[-1]-v[0] for v in ids.values()) if ids else None,
            'synchronized_call_wall_seconds':times[i],'ultralytics_stage_ms':dict(model_speed[i]),
            'actual_encoder_model':getattr(models[i].predictor.trackers[0].args,'model',None),
            'idf1':None,'id_switch_accuracy':None})
    assert sha256(a.raw)==raw_sha
    write_json(a.out/'comparison.json',{'revision':revision,'runs':runs,'changed_settings':changed,
        'video_sha256':sha256(raw['video_path']),'raw_sha256':sha256(a.raw),'weights_sha256':sha256(weights),
        'window':[a.start,a.start+count/fps],'imgsz':a.imgsz,'confidence':.25,'stride':a.stride,
        'wall_seconds':time.perf_counter()-start,'independent_test':False,
        'ultralytics_version':ultralytics.__version__,'torch_version':torch.__version__,
        'court_filter_applied':False,'production_updated':False,
        'both_paths_warmed':True,'alternating_call_order':True,
        'note':'Person tracks include spectators and referees; fewer IDs can also mean incorrect merges. No identity ground truth.'})
    print(json.dumps(runs),flush=True)


if __name__=='__main__':main()
