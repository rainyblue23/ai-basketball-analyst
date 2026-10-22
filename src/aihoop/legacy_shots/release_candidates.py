"""Parallel proximity/departure candidates; never creates a formal Attempt."""
from collections import deque
import math
from .release_binding import bind_release,touches


class ShotReleaseCandidateDetector:
    def __init__(self,fps,options):
        self.fps=fps;self.options=options;self.history=deque();self.candidates=[]
        self.seen=set();self.segment=0;self.last_phase='UNKNOWN'
        self.binding=dict(lookback=options['release_window_s'],min_contacts=2,min_departures=2,
            contact_gap=options['release_gap_s'],departure_gap=options['release_gap_s'],
            ambiguity_s=.1,x_pad=.25,top=-.2,bottom=options['release_contact_bottom'])

    def reset(self):
        for c in self.candidates:
            if c['candidate_state']=='COLLECTING_CONTEXT':
                c.update(candidate_state='UNKNOWN',context_truncated=True)
                c['rejection_reasons'].append('scene_cut_before_complete_context')
        self.history.clear();self.segment+=1

    def update(self,frame,t,ball,persons,rim):
        while self.history and t-self.history[0]['t']>self.options['release_window_s']:self.history.popleft()
        if ball is None or not ball.is_measurement:self.last_phase='UNKNOWN'
        if ball is not None and ball.is_measurement:
            row=dict(frame=frame,t=t,ball_xy=(ball.cx,ball.cy),ball_conf=ball.conf,
                person_boxes=[(p.track_id,*p.xyxy) for p in persons if p.track_id is not None and not p.predicted],
                rim=dict(rim) if rim else None)
            self.history.append(row)
            contacts=[p for p in row['person_boxes'] if touches(row['ball_xy'],p,self.binding)]
            self.last_phase='CONTESTED_POSSESSION' if len(contacts)>1 else 'POSSESSION_PROXY' if contacts else 'FREE_BALL'
            bound,evidence=bind_release(list(self.history),t,self.binding)
            if bound:
                _,pid,_,release_t=bound
                source=next(s for s in reversed(self.history) if s['t']==release_t)
                key=(self.segment,source['frame'],str(pid))
                if key not in self.seen:
                    self.seen.add(key)
                    owner=next(p for p in source['person_boxes'] if p[0]==pid)
                    parent=next((c for c in reversed(self.candidates) if c['segment']==self.segment
                                 and c['player_track_id']==pid and c['candidate_state'] not in ('REJECTED_NON_SHOT',)
                                 and evidence['contact_frames']<self.options['release_repossession_frames']
                                 and source['frame'] in {s['frame'] for s in c['observations']}
                                 and release_t-c['timestamp']<=self.options['release_window_s']),None)
                    c=dict(candidate_id=f'release_{self.segment}_{source["frame"]}_{pid}',
                        source_frame=source['frame'],timestamp=release_t,release_interval=evidence['interval_s'],
                        player_track_id=pid,rim_reference=source['rim'],confidence=.35,
                        supporting_evidence=['exclusive_upper_body_proximity','independent_departure_observations'],
                        rejection_reasons=[],candidate_state='COLLECTING_CONTEXT',shot_result='UNKNOWN',
                        shot_type='UNKNOWN',segment=self.segment,play_id='UNKNOWN',
                        replay_state='UNKNOWN',evidence_sources=['MODEL_OBSERVATIONS','PROXIMITY_PROXY'],
                        created_t=t,owner_box=list(owner),binding_evidence=evidence,
                        pre_release_observations=[dict(s) for s in self.history if s['t']<=release_t][:-evidence['contact_frames']],
                        observations=[],possible_continuation_of=parent['candidate_id'] if parent else None,
                        counts_for_statistics=False)
                    self.candidates.append(c)
            for c in self.candidates:
                if c['candidate_state']=='COLLECTING_CONTEXT' and c['segment']==self.segment:
                    c['observations']=[dict(s) for s in self.history if s['t']>=c['timestamp']]
        for c in self.candidates:
            if c['candidate_state']=='COLLECTING_CONTEXT' and t-c['created_t']>=self.options['release_context_s']:
                self._resolve(c)

    def _resolve(self,c):
        observations=c['observations'];relative=[];receivers=[];returns=[];rim_points=[]
        for s in observations:
            owner=next((p for p in s['person_boxes'] if p[0]==c['player_track_id']),None)
            if owner:
                height=max(1,owner[4]-owner[2])
                relative.append((s['t'],(s['ball_xy'][0]-(owner[1]+owner[3])/2)/height,
                                 (s['ball_xy'][1]-owner[2])/height))
                if s['t']>c['release_interval'][1] and touches(s['ball_xy'],owner,self.binding):returns.append(s['frame'])
            contacts=[p[0] for p in s['person_boxes'] if p[0]!=c['player_track_id'] and touches(s['ball_xy'],p,self.binding)]
            receivers.append((s['frame'],contacts))
            r=s.get('rim') or {}
            if r.get('measured_at_t') and r.get('w',0)>0:
                rim_points.append((s['frame'],r['segment'],math.hypot(s['ball_xy'][0]-r['cx'],s['ball_xy'][1]-r['cy'])/r['w']))
        rise=relative[0][2]-min(p[2] for p in relative) if relative else 0.
        drop=max(p[2] for p in relative)-relative[0][2] if relative else 0.
        near=bool(rim_points and rim_points[0][2]<=self.options['near_rim_widths'])
        approach=bool(len(rim_points)>=2 and rim_points[0][1]==rim_points[-1][1]
                      and rim_points[-1][2]<rim_points[0][2]*.8)
        received=any(set(a[1])&set(b[1]) and 0<b[0]-a[0]<=2 for a,b in zip(receivers,receivers[1:]))
        c['features']=dict(body_relative_rise=rise,body_relative_drop=drop,
            near_rim=near,approaching_rim=approach,receiver_contact_sequence=received,
            return_to_owner_frames=returns,model_observations=len(observations),
            source_frame_ids=[s['frame'] for s in observations])
        prior=c.get('pre_release_observations',[])
        contested=any(sum(touches(s['ball_xy'],p,self.binding) for p in s['person_boxes'])>1 for s in prior)
        gap=any(b['t']-a['t']>self.options['release_gap_s'] for a,b in zip(prior,prior[1:]))
        free=[s for s in prior if not any(touches(s['ball_xy'],p,self.binding) for p in s['person_boxes'])]
        owner_height=max(1.,c['owner_box'][4]-c['owner_box'][2])
        flight=(len(free)>=self.options['release_prior_free_frames'] and
                math.dist(free[0]['ball_xy'],free[-1]['ball_xy'])/owner_height>=self.options['release_rise_body_ratio'])
        c['features'].update(prior_contested_possession=contested,prior_observation_gap=gap,prior_free_flight=flight)
        c['candidate_state']='UNKNOWN';c['confidence']=.35
        if len(relative)<3:
            c['rejection_reasons'].append('insufficient_owner_motion_context')
        elif received and not near:
            c.update(candidate_state='REJECTED_NON_SHOT',shot_type='PASS_LIKE',confidence=.65)
            c['rejection_reasons'].append('receiver_contact_without_near_rim_evidence')
        elif len(returns)>=2 and drop>self.options['release_rise_body_ratio'] and not near:
            c.update(candidate_state='REJECTED_NON_SHOT',shot_type='DRIBBLE_OR_RETURN_LIKE',confidence=.6)
            c['rejection_reasons'].append('downward_ball_return_to_same_owner')
        elif rise>=self.options['release_rise_body_ratio'] and (near or approach) and not received:
            c.update(candidate_state='REVIEW_REQUIRED',shot_type='SHOT_LIKE',confidence=.7)
            c['supporting_evidence']+=['body_relative_rise','near_or_approaching_measured_rim']
        elif near and not received:
            c.update(candidate_state='REVIEW_REQUIRED',shot_type='SHORT_NEAR_RIM_UNRESOLVED',confidence=.5)
            c['supporting_evidence'].append('near_rim_departure_with_short_or_occluded_track')
        if near and len(relative)>=3:
            ys=[p[2] for p in relative]
            if min(ys)<ys[0] and ys[-1]>min(ys)+self.options['release_rise_body_ratio']:
                c['possible_subtype']='BLOCKED_REBOUND_OR_DEFLECTION_UNKNOWN'
        if c['possible_continuation_of']:
            c['candidate_state']='UNKNOWN';c['confidence']=min(c['confidence'],.35)
            c['rejection_reasons'].append('possible_same_possession_continuation_requires_review')
        if c['shot_type']=='SHOT_LIKE' and not near and c['binding_evidence']['contact_frames']<self.options['release_strong_contact_frames']:
            c.update(candidate_state='UNKNOWN',shot_type='UNKNOWN',confidence=.35)
            c['rejection_reasons'].append('weak_far_release_proxy_without_additional_action_evidence')
        if near and contested and (gap or flight) and c['candidate_state']=='REVIEW_REQUIRED':
            c.update(candidate_state='UNKNOWN',shot_type='UNKNOWN',confidence=.35)
            c['rejection_reasons'].append('contested_reacquisition_after_gap_or_flight; possible_deflection_rebound_or_return')
        if c['candidate_state']=='UNKNOWN':c['rejection_reasons'].append('shot_pass_scramble_or_rebound_not_resolved')

    def finish(self):
        for c in self.candidates:
            if c['candidate_state']=='COLLECTING_CONTEXT':
                self._resolve(c);c['context_truncated']=True
                c['rejection_reasons'].append('video_end_before_complete_context')


def link_forward_evidence(candidates,events,frames):
    """Link shared measured trajectory frames, not just nearby timestamps."""
    links=[]
    for c in candidates:
        ids=set(c.get('features',{}).get('source_frame_ids',[]))
        for i,event in enumerate(events):
            start=event.get('candidate_t',event.get('release_t',event.get('t',0)))
            end=event.get('t',start)
            shared=[r['frame'] for r in frames if r['frame'] in ids and start<=r['t']<=end
                    and (r.get('ball') or {}).get('measurement')]
            if len(shared)<2:continue
            event_pid=event.get('player_id')
            if event_pid is not None and str(event_pid)!=str(c['player_track_id']):continue
            links.append(dict(candidate_id=c['candidate_id'],forward_event_index=i,
                shared_measured_frames=shared,status='SHARED_VISUAL_EVIDENCE_REVIEW_REQUIRED',
                merged_into_statistics=False))
    return links
