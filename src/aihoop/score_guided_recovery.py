"""Opt-in offline score-guided investigation, never an online scoring policy.

Stable display changes are facts about the broadcast display. They are NOT
automatically made field goals. Recovery results remain separate hypotheses.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .scoreboard_fusion import score_changes


@dataclass(frozen=True)
class RecoveryOptions:
    enabled: bool = False
    confidence_floor: float = .9
    lookback_min_s: float = 3.
    lookback_max_s: float = 12.
    max_windows: int = 6
    allow_one_point_reanalysis: bool = False

    def __post_init__(self):
        if not (0 <= self.confidence_floor <= 1 and 3 <= self.lookback_min_s <= self.lookback_max_s <= 30
                and self.max_windows >= 1):
            raise ValueError('Invalid offline recovery options')


def investigate_score_changes(reference, forward_events=(), *, options=None, cuts=(),
                              excluded_intervals=(), team_map=None):
    """Reuse existing temporal confirmation, then apply conservative vetoes.

    Exclusion intervals must come from a separately recorded scene review (not
    a claim that replay recognition is solved). Regressed scores are quarantined
    until the previous display high-water mark is restored. Unknown screen-side
    to team mapping cannot be used to assign a shooter or confirm an outcome.
    """
    o=options or RecoveryOptions()
    if not o.enabled:return {'enabled':False,'facts':[],'windows':[],'rejected':[],'associations':[]}
    readings=[];invalid=[]
    for row in reference.get('readings',[]):
        values=row.get('pair');t=row.get('t');conf=row.get('confidence',0)
        if (not isinstance(t,(int,float)) or not math.isfinite(t) or
                not isinstance(conf,(int,float)) or not math.isfinite(conf) or
                not isinstance(values,(list,tuple)) or len(values)!=2 or
                any(isinstance(v,bool) or not isinstance(v,int) or not 0<=v<=999 for v in values)):
            invalid.append({'reason':'invalid_reading'});continue
        if conf<o.confidence_floor:
            invalid.append({'t':t,'reason':'low_ocr_confidence'});continue
        readings.append(row)
    # Explicitly excluded samples cannot provide the stable support for a fact.
    def excluded(t):return next((x.get('reason','excluded_scene') for x in excluded_intervals
                                if x['start_s']<=t<=x['end_s']),None)
    accepted_rows=[r for r in readings if not excluded(r['t']) and not r.get('is_replay')
                   and str(r.get('period','')).upper()!='FINAL']
    for r in readings:
        why=excluded(r['t']) or ('replay' if r.get('is_replay') else
                                'final_display' if str(r.get('period','')).upper()=='FINAL' else None)
        if why:invalid.append({'t':r['t'],'reason':why})
    candidates,gaps=score_changes({'readings':accepted_rows},cuts)
    regressions=[g for g in gaps if any(b<a for a,b in zip(g['previous'],g['score']))]
    facts=[];associations=[];windows=[];seen=set();mapping=team_map or {}
    mapped=set(mapping)=={'left','right'} and set(mapping.values())=={'home','away'}
    proposed=[]
    for c in candidates:
        why=None
        if any(g['t']<=c['t'] and any(v<h for v,h in zip(c['previous'],g['previous'])) for g in regressions):
            why='score_regression_quarantine'
        if any(c['previous_t']<=x['end_s'] and x['start_s']<=c['t'] for x in excluded_intervals):
            why='excluded_scene_boundary'
        key=json.dumps([reference.get('video_sha256'),c['previous'],c['score'],c['screen_side']])
        if key in seen:why='duplicate_display_transition'
        if why:invalid.append(dict(c,reason=why));continue
        seen.add(key)
        supporting=[r for r in accepted_rows if r['t']==c['previous_t'] or
                    c['t']<=r['t']<=c['t']+.6 and list(r['pair'])==c['score']]
        confidence=min((r['confidence'] for r in supporting),default=0.)
        identity='score_'+hashlib.sha256(key.encode()).hexdigest()[:16]
        fact=dict(c,score_event_id=identity,status='SCORE_DISPLAY_CHANGE_CONFIRMED',confidence=confidence,
            scoring_team=mapping[c['screen_side']] if mapped else 'UNKNOWN',
            scoring_type='FREE_THROW_OR_SPECIAL_UNKNOWN' if c['delta']==1 else 'UNKNOWN',
            evidence_sources=['SCOREBOARD'],physical_score_verified=False)
        facts.append(fact)
        eligible=[]
        for i,e in enumerate(forward_events):
            et=e.get('release_t') if e.get('release_known') else e.get('start_t',e.get('t'))
            if et is None or not 0<=c['t']-et<=o.lookback_max_s:continue
            if e.get('is_replay') or any(et<cut<=c['t'] for cut in cuts):continue
            if not mapped or e.get('team')!=mapping[c['screen_side']]:continue
            if bool(e.get('is_free_throw')) != (c['delta']==1):continue
            if e.get('value_verified') and e.get('value')!=c['delta']:continue
            eligible.append(i)
        proposed.append(eligible)
    for fact,eligible in zip(facts,proposed):
        unique=len(eligible)==1 and sum(eligible[0] in group for group in proposed)==1
        i=eligible[0] if unique else None
        associations.append({'score_event_id':fact['score_event_id'],
            'forward_event_index':i,'forward_event_id':forward_events[i].get('event_id') if i is not None else None,
            'status':'UNIQUE_EVIDENCE_LINK_REVIEW_REQUIRED' if i is not None else 'SCORE_CONFIRMED_SHOOTER_UNKNOWN',
            'shooter_track_id':'UNKNOWN','shot_result':'UNKNOWN',
            'reason':'unique_known_team_link' if i is not None else 'ambiguous_or_missing_visual_team_evidence'})
        if fact['delta']==1 and not o.allow_one_point_reanalysis:continue
        if len(windows)>=o.max_windows:continue
        windows.append({'score_event_id':fact['score_event_id'],
            'start_s':max(0.,fact['t']-o.lookback_max_s),'end_s':fact['t'],
            'initial_start_s':max(0.,fact['t']-o.lookback_min_s),
            'reason':'stable_display_change_requires_visual_evidence'})
    return dict(enabled=True,options=asdict(o),facts=facts,windows=windows,rejected=invalid,
                discontinuities=gaps,associations=associations,
                note='No Attempt is created or upgraded. No automatic player statistics are modified.')
