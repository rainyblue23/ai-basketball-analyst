"""Bounded offline attribution from an existing made event back to possession.

The existing result is an anchor, not human truth. This module never edits an
event, creates a shot, or changes team scores. Predictions and hard-rejected
head/UI/size candidates cannot establish a reverse observation chain.
"""
from dataclasses import dataclass
import math

from .legacy_shots.release_binding import bind_release


@dataclass(frozen=True)
class MadeAttributionOptions:
    enabled: bool = False
    lookback_s: float = 4.
    max_gap_s: float = .25
    anchor_gap_s: float = .25
    max_speed_widths_s: float = 1.5
    max_size_ratio: float = 2.5
    min_confidence: float = .25
    beam_width: int = 6
    max_candidates_per_frame: int = 16
    max_frames: int = 300
    ambiguity_cost: float = .12
    body_contact_top_ratio: float = .05

    def __post_init__(self):
        if not (0 < self.lookback_s <= 6 and 0 < self.max_gap_s <= .5
                and 0 < self.anchor_gap_s <= .5 and 0 < self.max_speed_widths_s <= 3
                and 1 <= self.max_size_ratio <= 4 and 0 < self.min_confidence <= 1
                and 1 <= self.beam_width <= 12 and 1 <= self.max_candidates_per_frame <= 32
                and 2 <= self.max_frames <= 600 and self.ambiguity_cost >= 0
                and 0 <= self.body_contact_top_ratio <= .25):
            raise ValueError('Invalid made-shooter recovery budget')


def _box(row):
    values=row.get('xyxy')
    if not isinstance(values,(list,tuple)) or len(values)!=4:
        return None
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in values):
        return None
    x1,y1,x2,y2=values
    return tuple(values) if x2>x1 and y2>y1 else None


def _observations(frame, options, *, recheck_ground=False):
    allowed={'selected','not_selected','motion_rejected','reacquired','eligible'}
    result=[]
    rows=list(frame.get('ball_candidates') or [])
    selected=frame.get('ball')
    if selected:
        # The selected observation is already accepted by the forward filters.
        rows.append(dict(selected,selection_reason='selected'))
    seen=set()
    for row in rows:
        box=_box(row)
        if (box is None or box in seen or row.get('predicted')
                or row.get('measurement') is False or row.get('cls')!='basketball'
                or row.get('selection_reason') not in allowed
                or not isinstance(row.get('conf'),(int,float))
                or not math.isfinite(row['conf']) or row['conf']<options.min_confidence):
            continue
        seen.add(box)
        result.append(dict(frame=frame['frame'],t=float(frame['t']),xyxy=box,
            ball_xy=((box[0]+box[2])/2,(box[1]+box[3])/2),
            size=max(box[2]-box[0],box[3]-box[1]),conf=float(row['conf']),
            source=row.get('source','model'),selection_reason=row['selection_reason'],
            person_boxes=[(p['track_id'],*p['xyxy']) for p in frame.get('persons',[])
                          if p.get('track_id') is not None and not p.get('predicted')
                          and (recheck_ground or p.get('on_court') is not False)
                          and str(p.get('role','')).upper() not in ('REFEREE','SPECTATOR')
                          and _box(p)]))
    return sorted(result,key=lambda r:-r['conf'])[:options.max_candidates_per_frame]


def recover_made_shooter(event, frames, width, *, options=None, players=None,
                         calibration_at=None):
    """Return a separate attribution proposal; original records stay immutable.

    Hard filters stay in force. A forward motion-gate rejection may be retried
    because reverse association starts at this basket instead of a stale ball.
    Every selected edge is between real observations, bounded by time/scale/
    speed. The existing contact/departure binder validates the last possessor.
    """
    o=options or MadeAttributionOptions()
    output=dict(enabled=o.enabled,status='DISABLED',counts_for_statistics=False,
                player_track_id=None,team=None,value=None,observations=[],candidates=[])
    if not o.enabled:
        return output
    output['status']='UNRESOLVED'
    if (event.get('result')!='made' or event.get('type')!='make'
            or event.get('suggested_made') is not None):
        return dict(output,reason='not_an_existing_confirmed_make')
    anchor_t=event.get('crossing_t')
    if not isinstance(anchor_t,(int,float)) or not math.isfinite(anchor_t):
        return dict(output,reason='missing_crossing_anchor')
    if not isinstance(width,(int,float)) or not math.isfinite(width) or width<=0:
        raise ValueError('Original video width is required')
    rows=sorted((f for f in frames if isinstance(f.get('t'),(int,float))
                 and math.isfinite(f['t']) and anchor_t-o.lookback_s<=f['t']<=anchor_t),
                key=lambda f:f['t'])
    if len(rows)>o.max_frames:
        return dict(output,reason='frame_budget_exceeded')
    # Start after the most recent explicit camera/trajectory boundary. A missing
    # boundary contract is not permission to join different segments.
    boundary=0
    for i,f in enumerate(rows):
        if f.get('cut') or (i and f.get('evidence_segment')!=rows[i-1].get('evidence_segment')):
            boundary=i
    rows=rows[boundary:]
    output.update(anchor_t=anchor_t,anchor_evidence='EXISTING_MODEL_MADE_NOT_HUMAN_TRUTH',
                  source_frame_count=len(rows),scene_boundary_applied=boundary>0)
    anchor=None;anchor_index=None
    rim=event.get('rim_xy');rim_w=event.get('rim_w')
    if (not isinstance(rim,(list,tuple)) or len(rim)!=2 or
            not all(isinstance(v,(int,float)) and math.isfinite(v) for v in rim)
            or not isinstance(rim_w,(int,float)) or not math.isfinite(rim_w) or rim_w<=0):
        return dict(output,reason='missing_rim_anchor')
    for index in range(len(rows)-1,-1,-1):
        f=rows[index]
        if anchor_t-f['t']>o.anchor_gap_s:
            break
        candidates=[b for b in _observations(f,o,recheck_ground=calibration_at is not None)
                    if math.dist(b['ball_xy'],rim)<=2*rim_w]
        if candidates:
            anchor=min(candidates,key=lambda b:math.dist(b['ball_xy'],rim))
            anchor_index=index
            break
    if anchor is None:
        return dict(output,reason='no_measured_ball_at_crossing')
    # Each beam entry: reverse observations, cumulative association cost.
    beam=[([anchor],0.)];finished=[]
    for f in reversed(rows[:anchor_index]):
        candidates=_observations(f,o,recheck_ground=calibration_at is not None);next_beam=[]
        for path,cost in beam:
            last=path[-1];dt=last['t']-f['t']
            if dt<=0:
                continue
            if dt>o.max_gap_s:
                finished.append((path,cost));continue
            vx=vy=0.
            if len(path)>1:
                newer=path[-2];step=newer['t']-last['t']
                if step>0:
                    vx=(last['ball_xy'][0]-newer['ball_xy'][0])/step
                    vy=(last['ball_xy'][1]-newer['ball_xy'][1])/step
            predicted=(last['ball_xy'][0]+vx*dt,last['ball_xy'][1]+vy*dt)
            for b in candidates:
                scale=max(b['size'],last['size'])/max(1.,min(b['size'],last['size']))
                distance=math.dist(last['ball_xy'],b['ball_xy'])
                limit=max(2*last['size'],o.max_speed_widths_s*width*dt)
                if scale>o.max_size_ratio or distance>limit:
                    continue
                residual=math.dist(predicted,b['ball_xy'])/max(limit,1.)
                penalty=.4*residual+.15*abs(math.log(scale))+.1*(1-b['conf'])
                next_beam.append((path+[b],cost+penalty))
            # Missing observations remain missing. A skip does not interpolate
            # positions or refresh the timestamp used by the bounded gap gate.
            next_beam.append((path,cost+.12))
        beam=sorted(next_beam,key=lambda p:p[1]/len(p[0])-.03*len(p[0]))[:o.beam_width]
        if not beam:
            break
    finished.extend(beam)
    binder=dict(lookback=o.lookback_s,min_contacts=2,min_departures=2,
                contact_gap=o.max_gap_s,departure_gap=o.max_gap_s,
                ambiguity_s=.1,x_pad=.25,top=-.2,bottom=.75)
    proposals={};rejections=[]
    for path,cost in finished:
        history=list(reversed(path))
        bound,evidence=bind_release(history,anchor_t,binder)
        if bound is None:
            continue
        feet,pid,_,release_t=bound
        # Brief contact with a flying ball near the rim can be a head passing
        # behind it, a deflection or a rebound. Require additional possession
        # support instead of attributing that pre-existing flight to this body.
        before=[s for s in history if s['t']<release_t]
        contacts=evidence['contact_frames']
        prior=before[:-max(0,contacts-1)] if contacts>1 else before
        free=[]
        from .legacy_shots.release_binding import touches
        contact_run=[]
        for s in reversed([s for s in history if s['t']<=release_t]):
            box=next((p for p in s['person_boxes'] if p[0]==pid),None)
            if box is None or not touches(s['ball_xy'],box,binder):
                break
            contact_run.append((s,box))
            if len(contact_run)>=contacts:
                break
        # Above-head proximity alone cannot distinguish possession from a
        # flying ball passing in front of a referee or a spectator's head.
        if not any(s['ball_xy'][1]>=p[2]+o.body_contact_top_ratio*(p[4]-p[2])
                   for s,p in contact_run):
            rejections.append(dict(player_track_id=pid,reason='head_only_contact'))
            continue
        for s in reversed(prior):
            if any(touches(s['ball_xy'],p,binder) for p in s['person_boxes']):
                break
            free.append(s)
        owner=next(p for s in reversed(history) if s['t']==release_t
                   for p in s['person_boxes'] if p[0]==pid)
        height=owner[4]-owner[2]
        if (contacts<4 and len(free)>=3 and
                math.dist(free[0]['ball_xy'],free[-1]['ball_xy'])>.25*height):
            rejections.append(dict(player_track_id=pid,reason='brief_contact_after_free_flight'))
            continue
        candidate=dict(player_track_id=pid,release_t=release_t,foot_xy=list(feet),
                       association_cost=cost/len(path),contact_evidence=evidence,
                       observations=history)
        if calibration_at is not None:
            cal=calibration_at(release_t)
            if cal is None:
                rejections.append(dict(player_track_id=pid,reason='no_corresponding_ground_calibration'))
                continue
            x,y=cal.to_court(*feet)
            if not (math.isfinite(x) and math.isfinite(y) and cal.in_court(x,y,tol=.12)):
                rejections.append(dict(player_track_id=pid,reason='feet_outside_verified_court'))
                continue
            from .rules import shot_value
            candidate.update(court_xy=[x,y],value=1 if event.get('is_free_throw') is True else shot_value(x,y),
                             value_source='release_feet_and_corresponding_calibration')
        old=proposals.get(str(pid))
        if old is None or candidate['association_cost']<old['association_cost']:
            proposals[str(pid)]=candidate
    ranked=sorted(proposals.values(),key=lambda c:c['association_cost'])
    output['candidates']=[{k:v for k,v in p.items() if k!='observations'} for p in ranked]
    output['rejections']=rejections
    if not ranked:
        best=max(finished,key=lambda p:len(p[0]),default=([],0.))[0]
        return dict(output,reason='no_connected_contact_departure',observations=list(reversed(best)))
    if len(ranked)>1 and ranked[1]['association_cost']-ranked[0]['association_cost']<=o.ambiguity_cost:
        return dict(output,reason='ambiguous_last_possessor')
    winner=ranked[0]
    output.update(status='ATTRIBUTION_PROPOSAL',reason='connected_measured_path_to_release',
                  **{k:v for k,v in winner.items() if k!='association_cost'})
    player=(players or {}).get(str(winner['player_track_id'])) or {}
    output['team']=player.get('team') if player.get('team') in ('home','away') else None
    return output
