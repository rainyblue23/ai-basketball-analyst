"""Compare cached whole-video traces; emit pending review evidence, never truth."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from collect_cv_baseline import sha256, write_json
from diagnose_nba_clip import blocking_evidence
from aihoop.legacy_shots.release_binding import touches, contact_region
from aihoop.legacy_shots.release_candidates import ShotReleaseCandidateDetector
from aihoop.legacy_shots.settings import GeneralVisionOptions


def measured(row):
    ball=row.get('ball') or {}
    return bool(ball.get('xyxy') and ball.get('measurement',not ball.get('predicted'))
                and ball.get('cls')!='motion_ball')


def proximity_context(row,options):
    """Expose the existing shadow proxy, without calling overlap 'possession'."""
    if not measured(row):return dict(status='no_model_ball_observation',contacts=[])
    box=row['ball']['xyxy'];xy=((box[0]+box[2])/2,(box[1]+box[3])/2)
    contacts=[]
    for person in row.get('persons',[]):
        if person.get('predicted') or person.get('track_id') is None:continue
        p=(person['track_id'],*person['xyxy'])
        if touches(xy,p,options):
            contacts.append(dict(track_id=p[0],person_xyxy=person['xyxy'],proxy_region=contact_region(p,options)))
    return dict(status='ambiguous_overlap' if len(contacts)>1 else
                'single_proximity_proxy' if contacts else 'no_proximity_proxy',contacts=contacts,
                confirms_hand_contact=False,confirms_player_identity=False)


def compare_traces(before,after):
    """Require matching frame identities; compare observations, not TP/FP."""
    for key in ('fps','width','height'):
        if before[key]!=after[key]:raise ValueError('Mismatched video geometry/time basis: '+key)
    b=before['detections_meta']['legacy_shots'];a=after['detections_meta']['legacy_shots']
    bindings=[ShotReleaseCandidateDetector(raw['fps'],GeneralVisionOptions(**trace['config']['detect'].get('general',{})).model_dump()).binding
              for raw,trace in ((before,b),(after,a))]
    left,right=b['frames'],a['frames']
    if len(left)!=len(right):raise ValueError('Mismatched decoded frame count')
    if len({r['frame'] for r in left})!=len(left):raise ValueError('Duplicate source frame')
    rows=[]
    for old,new in zip(left,right):
        if old['frame']!=new['frame'] or abs(old['t']-new['t'])>1e-7:
            raise ValueError('Mismatched original frame/time')
        old_m,new_m=measured(old),measured(new)
        kind=('observation_added' if new_m and not old_m else
              'observation_removed' if old_m and not new_m else
              'selected_observation_changed' if old_m and new_m and old['ball']['xyxy']!=new['ball']['xyxy'] else
              'unchanged')
        # Preserve both candidates and refusals, including any ROI with no result.
        rows.append(dict(frame=old['frame'],t=old['t'],change=kind,
            before=blocking_evidence(old,b['config']),after=blocking_evidence(new,a['config']),
            before_ball=old.get('ball'),after_ball=new.get('ball'),
            before_release_proximity=proximity_context(old,bindings[0]),
            after_release_proximity=proximity_context(new,bindings[1]),
            after_tracked_rim=new.get('tracked_rim'),
            review_status='pending',basketball_truth='UNKNOWN',counts_as_accuracy=False))
    summary=dict(frames=len(rows),changes=dict(Counter(r['change'] for r in rows)),
        before_model_observation_frames=sum(measured(r) for r in left),
        after_model_observation_frames=sum(measured(r) for r in right),
        before_events=b['events'],after_events=a['events'],
        tp=None,fp=None,fn=None,precision=None,recall=None,
        scope='Development observation changes only; complete reviewed ball/shot truth unavailable',
        roi_audit={key:dict(Counter((r.get(key) or {}).get('reason','not_triggered') for r in right))
                   for key in ('ball_recovery','rim_recovery')})
    return rows,summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('Choose a new output directory')
    before=json.loads(a.before.read_text());after=json.loads(a.after.read_text())
    # Names and nominal duration are insufficient to establish the same input.
    hashes=[sha256(Path(raw['video_path'])) for raw in (before,after)]
    if hashes[0]!=hashes[1]:p.error('Video SHA mismatch')
    rows,summary=compare_traces(before,after);a.out.mkdir(parents=True)
    summary.update(video_sha256=hashes[0],before_raw_sha256=sha256(a.before),
                   after_raw_sha256=sha256(a.after),before=str(a.before),after=str(a.after))
    with (a.out/'frames.jsonl').open('w') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    with (a.out/'changes.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['frame','t','change','before_candidates','after_candidates','after_source','before_block','after_block'])
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(frame=row['frame'],t=row['t'],change=row['change'],
                before_candidates=row['before']['model_ball_candidates'],after_candidates=row['after']['model_ball_candidates'],
                after_source=(row['after_ball'] or {}).get('source'),
                before_block=';'.join(row['before']['blocking_reasons']),after_block=';'.join(row['after']['blocking_reasons'])))
    write_json(a.out/'summary.json',summary)
    write_json(a.out/'review_tasks.json',dict(video_sha256=hashes[0],split='Development',
        review_status='pending',training_approved=False,frame_complete=False,
        tasks=[dict(frame=r['frame'],timestamp=r['t'],change=r['change'],truth='UNKNOWN')
               for r in rows if r['change']!='unchanged']))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
