"""One opt-in crossing-window experiment. No truth enters ScoreEngine."""
import copy
import csv
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from aihoop.legacy_shots.scorer import ScoreEngine
from aihoop.legacy_shots.detector import Det

OLD = ROOT / 'out/stage2_audit_20261020'
OUT = ROOT / 'out/crossing_window_20261020'

def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def det(d):
    return Det(d['cls'], d['conf'], tuple(d['xyxy']), d.get('track_id'), d.get('predicted', False)) if d else None

class ObservedEngine(ScoreEngine):
    def _close(self, *args, **kwargs):
        self.closing.append(asdict(self.attempt))
        return super()._close(*args, **kwargs)

def replay(raw, enabled):
    cfg = copy.deepcopy(raw['detections_meta']['legacy_shots']['config'])
    if enabled:
        cfg['score']['make_window_from_crossing'] = True
    def engine():
        e = ObservedEngine(cfg, raw['fps'])
        e.closing = []
        return e
    e = engine()
    events, states = [], []
    frames = raw['detections_meta']['legacy_shots']['frames']
    for f in frames:
        before = asdict(e.attempt) if e.attempt else None
        closed = []
        if f['cut']:
            events.extend(e.finalize(f['frame'], f['t']))
            closed.extend(e.closing)
            e = engine()
        emitted = e.update(f['frame'], f['t'], det(f['ball']), det(f['rim']), [det(x) for x in f['persons']])
        events.extend(emitted)
        closed.extend(e.closing)
        e.closing.clear()
        after = asdict(e.attempt) if e.attempt else None
        at = after or (closed[-1] if closed else None)
        state = dict(frame=f['frame'], t=f['t'], cut=f['cut'], before=before, after=after,
                     closed=closed, events=emitted, raw_ball=f['ball'], raw_rim=f['rim'],
                     tracked_rim=dict(cx=e.rim.cx, cy=e.rim.cy, w=e.rim.w, h=e.rim.h,
                                      bottom=e.rim.bottom, generation=e.rim.generation,
                                      fresh=e.rim.fresh(f['t'], e.rim_stale_s)))
        if at:
            entry = at['entered_t']; cross = at['crossing_t']
            state.update(entry_deadline=entry + e.make_window_s if entry is not None else None,
                         crossing_deadline=cross + e.make_window_s if cross is not None else None,
                         entry_expired=entry is not None and f['t'] - entry > e.make_window_s,
                         crossing_active=cross is not None and f['t'] - cross <= e.make_window_s)
        states.append(state)
    events.extend(e.finalize(len(frames), len(frames) / raw['fps']))
    return events, states, cfg

def evaluate(sample, events, match):
    truth = sample['truth']
    # Truth is only used AFTER replay, at the frozen tolerance.
    pairs = match([x['release_s'] for x in truth], [x['release_t'] for x in events], tolerance=1.5)
    mapping = {i:j for i,j,_ in pairs}
    rows = []
    for i, tr in enumerate(truth):
        ev = events[mapping[i]] if i in mapping else None
        rows.append(dict(key=f"{sample['id']}:truth:{i}", truth_time=tr['release_s'], truth_result=tr['result'],
                         event_class='TP' if ev else 'FN',
                         made_class=('TP' if tr['result']=='made' else 'FP') if ev and ev['result']=='made' else ('FN' if tr['result']=='made' else None),
                         event=ev))
    used = set(mapping.values())
    for j, ev in enumerate(events):
        if j not in used:
            rows.append(dict(key=f"{sample['id']}:extra:{ev['release_t']}", truth_time=None, truth_result=None,
                             event_class='FP', made_class='FP' if ev['result']=='made' else None, event=ev))
    return rows

def metrics(rows):
    return dict(shot={k:sum(r['event_class']==k for r in rows) for k in ('TP','FP','FN')},
                made={k:sum(r['made_class']==k for r in rows) for k in ('TP','FP','FN')},
                UNKNOWN=sum(r['event'] is not None and r['event']['result']=='unknown' for r in rows))

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    protected = [ROOT/'eval/ground_truth/shots_split2_20261011.json', ROOT/'src/aihoop/legacy_shots/scorer.py',
                 ROOT/'src/aihoop/legacy_shots/stream.py', ROOT/'runs/detect/ball/weights/best.pt', ROOT/'runs/detect/rim/weights/best.pt']
    before = {str(p):sha(p) for p in protected}
    dump('predeclared_plan.json', dict(change={'score.make_window_from_crossing':[False,True]},
         make_window_s=.9, tolerance_s=1.5, threshold_search=False, inputs='frozen measured selected-ball/rim traces',
         acceptance='Target restored, no added make FP, all three existing FP separately checked; no production enable while false-MADE safety unmet.',
         other_changes=False, production_default=False))
    # Read all four requested evidence files in full.
    docs = [ROOT/'DATASET_IDENTITY_AUDIT.md', ROOT/'EVENT_ERROR_ANALYSIS.md', OLD/'fp_fn_made_errors.csv', OLD/'diagnostic_index.html']
    dump('inputs.json', {str(p):dict(sha256=sha(p),characters=len(p.read_text(encoding='utf-8'))) for p in docs})
    spec=importlib.util.spec_from_file_location('eval_match', ROOT/'scripts/eval_match_annotations.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    baseline=read(OLD/'current_baseline/results.json')
    assert baseline['truth_sha256']==before[str(protected[0])]
    all_a, all_b, comparison, summaries = [], [], [], []
    for sample in baseline['samples']:
        raw=read(OLD/'current_baseline'/sample['id']/'raw_track.json')
        a,sa,ca=replay(raw,False)
        assert a==raw['detections_meta']['legacy_shots']['events'], sample['id']+': A not exact'
        b,sb,cb=replay(raw,True)
        ra=evaluate(sample,a,mod.match_times);rb=evaluate(sample,b,mod.match_times)
        all_a+=ra;all_b+=rb
        summaries.append(dict(sample=sample['id'], truth_count=len(sample['truth']), A_exact=True, A=metrics(ra),B=metrics(rb)))
        dump(sample['id']+'_A_events.json',a);dump(sample['id']+'_B_events.json',b)
        dump(sample['id']+'_config.json',dict(A=ca,B=cb))
        # Complete frame-by-frame before/update/close observations, not just surviving attempts.
        dump(sample['id']+'_A_states.json',sa);dump(sample['id']+'_B_states.json',sb)
        ma={r['key']:r for r in ra};mb={r['key']:r for r in rb}
        for key in dict.fromkeys([*ma,*mb]):
            x=ma.get(key);y=mb.get(key)
            r=dict(key=key,truth_time=(x or y)['truth_time'],truth_result=(x or y)['truth_result'])
            for arm,row in [('A',x),('B',y)]:
                ev=row['event'] if row else None
                r.update({arm+'_shot':row['event_class'] if row else None,arm+'_made':row['made_class'] if row else None,
                          arm+'_release':ev['release_t'] if ev else None,arm+'_result':ev['result'] if ev else None,
                          arm+'_decision':ev['t'] if ev else None,arm+'_crossing':ev['crossing_t'] if ev else None})
            r['changed']=x!=y
            comparison.append(r)
        if sample['id']=='s2_hs_game01':
            for arm,states in [('A',sa),('B',sb)]:
                focus=[s for s in states if 14.9<=s['t']<=17.5]
                dump('target_'+arm+'_timeline.json',focus)
    dump('results.json',dict(samples=summaries,A=metrics(all_a),B=metrics(all_b),tolerance_s=1.5,
         truth_count=sum(x['truth_count'] for x in summaries),independent_test_count=0,
         limitations=['fixed perception replay, not end-to-end GPU B','game03 is exposed validation','2D crossing cannot prove a physical basket'],
         default_changed=False,recommendation='DO_NOT_ENABLE'))
    with (OUT/'per_event_ab.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(comparison[0]));w.writeheader();w.writerows(comparison)
    dump('per_event_ab.json',comparison)
    imported=read(ROOT/'eval/annotation_imports/three_bili_20261020/annotations.normalized.json')
    source=ROOT/'三个视频出手记录.txt'; archived=Path(imported['archived_original'])
    imports=[]
    for s in imported['samples']:
        video=Path(s['video'])
        old=read(ROOT/f"eval/ground_truth/{s['id']}_bili_timed.json")
        imports.append(dict(id=s['id'],source_id=s['source_id'],count=len(s['shots']),
          replay=sum(x['is_replay'] for x in s['shots']),unique=sum(not x['is_replay'] for x in s['shots']),
          video_exists=video.exists(),video_sha_matches=video.exists() and sha(video)==s['source_sha256'],
          all_times_in_prior=all(any(x['release_s']==o['release_t'] for o in old['shots']) for x in s['shots']),
          split=s['dataset_split']))
    dump('annotation_import_check.json',dict(samples=imports,source_sha_matches=sha(source)==sha(archived)==imported['original_sha256'],
         imported=True,in_31_baseline=False,evaluated_in_this_experiment=False,
         count=sum(x['count'] for x in imports),unique=sum(x['unique'] for x in imports),
         missing_known_sources=[],pending=['harden 116s precise release','full match identity and clip offsets'],
         scope='Only locally supplied three-video TXT verified; additional unprovided records cannot be inferred.'))
    after={str(p):sha(p) for p in protected}
    assert before==after
    dump('protected_hashes.json',dict(before=before,after=after,unchanged=True))
    print(json.dumps(dict(samples=summaries,A=metrics(all_a),B=metrics(all_b),changes=[x for x in comparison if x['changed']]),ensure_ascii=False))

if __name__=='__main__':main()
