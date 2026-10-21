"""Single predeclared existing-config experiment on measured frozen traces."""
import copy
import importlib.util
import json
from pathlib import Path
import cv2
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.scorer import ScoreEngine

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/stage2_audit_20261020'


def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def det(d):return Det(d['cls'],d['conf'],tuple(d['xyxy']),d.get('track_id'),d.get('predicted',False)) if d else None


def replay(raw, strict=False):
    legacy=raw['detections_meta']['legacy_shots'];cfg=copy.deepcopy(legacy['config'])
    if strict:cfg['score']['strict_shot_gate']=True
    engine=ScoreEngine(cfg,raw['fps']);events=[];states=[]
    for f in legacy['frames']:
        if f['cut']:
            events.extend(engine.finalize(f['frame'],f['t']));engine=ScoreEngine(cfg,raw['fps'])
        events.extend(engine.update(f['frame'],f['t'],det(f['ball']),det(f['rim']),[det(d) for d in f['persons']]))
        at=engine.attempt
        if at:
            states.append(dict(t=f['t'],release_t=at.start_t,entered_t=at.entered_t,crossing_t=at.crossing_t,
                rim_rebound_seen=at.rim_rebound_seen,real_obs=at.real_obs,
                entered_window_expired=at.entered_t is not None and f['t']-at.entered_t>engine.make_window_s,
                measured_crossing_available=at.crossing_t is not None))
    events.extend(engine.finalize(len(legacy['frames']),len(legacy['frames'])/raw['fps']))
    return events,states


def main():
    spec=importlib.util.spec_from_file_location('audit',ROOT/'scripts/stage2_evidence_audit.py')
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    spec2=importlib.util.spec_from_file_location('evaluate',ROOT/'scripts/eval_match_annotations.py')
    evaluate=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(evaluate)
    baseline=load(OUT/'current_baseline/results.json');truth=load(ROOT/'eval/ground_truth/shots_split2_20261011.json')
    result=[]
    for sample in baseline['samples']:
        raw=load(OUT/'current_baseline'/sample['id']/'raw_track.json')
        original,states=replay(raw)
        if original!=raw['detections_meta']['legacy_shots']['events']:
            raise RuntimeError(sample['id']+': replay A not exact, refuse experimental conclusions')
        new,_=replay(raw,True)
        def summarize(events):
            preds=[dict(release_s=e['release_t'],result=e['result'],decision_s=e['t']) for e in events]
            pairs=evaluate.match_times([s['release_s'] for s in sample['truth']],[e['release_s'] for e in preds])
            rows=[];paired=set()
            for ti,ei,delta in pairs:
                paired.add(ei);tr=sample['truth'][ti];ev=preds[ei]
                rows.append(dict(event_class='TP',made_class='TP' if ev['result']=='made' and tr['result']=='made' else ('FP' if ev['result']=='made' else ('FN' if tr['result']=='made' else None)),model_result=ev['result']))
            for ei,ev in enumerate(preds):
                if ei not in paired:rows.append(dict(event_class='FP_unmatched',made_class='FP' if ev['result']=='made' else None,model_result=ev['result']))
            for ti,tr in enumerate(sample['truth']):
                if ti not in {p[0] for p in pairs}:rows.append(dict(event_class='FN_unmatched',made_class='FN' if tr['result']=='made' else None,model_result=None))
            return dict(events=preds,metrics=audit.metrics(rows),rows=rows)
        result.append(dict(id=sample['id'],split='Validation_exposed' if 'game03' in sample['id'] else 'Development',
            replay_A_exact=True,baseline=summarize(original),strict_candidate=summarize(new),
            predeclared_change='existing strict_shot_gate=True; no threshold search; all other inputs unchanged',
            selected_evidence_fixed=True))
        audit.dump(OUT/f"{sample['id']}_state_observations.json",states)
    aggregate={arm:audit.metrics([r for s in result for r in s[arm]['rows']]) for arm in ('baseline','strict_candidate')}
    audit.dump(OUT/'strict_gate_ab.json',dict(samples=result,aggregate=aggregate,
        limits=['Offline measured selected-ball/rim replay, not end-to-end GPU B.', 'No Independent Test.', 'Config default not changed.']))
    print(json.dumps(aggregate,ensure_ascii=False))
    cases=load(OUT/'event_cases.json')['cases']
    for row in cases:
        if row['made_class'] not in ('FP','FN') and row['event_class']=='TP':continue
        video=row['video'];cap=cv2.VideoCapture(video);tiles=[]
        center=(row.get('model_output') or {}).get('crossing_s') or row['video_time_s']+1
        for dt in (-1.5,-1,-.5,0,.25,.5,1,1.5):
            t=max(0,center+dt);cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,img=cap.read()
            if not ok:continue
            img=cv2.resize(img,(480,270));cv2.putText(img,f't={t:.3f}',(8,24),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,255),2);tiles.append(img)
        cap.release()
        if len(tiles)==8:
            import numpy as np
            cv2.imwrite(str(OUT/'keyframes'/f"{row['case_id']}_sheet.jpg"),np.vstack([np.hstack(tiles[:4]),np.hstack(tiles[4:])]))


if __name__=='__main__':main()
