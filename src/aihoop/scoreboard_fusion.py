"""Use measured broadcast score changes without inventing shooters or locations."""
import copy
import os


def score_changes(reference, cuts=()):
    """Reconstruct stable readings; cuts and large jumps remain explicit gaps."""
    groups=[]
    for row in sorted(reference.get('readings') or [],key=lambda r:r['t']):
        values=tuple(row.get('pair') or ())
        if len(values)!=2:continue
        if not groups or groups[-1]['pair']!=values or row['t']-groups[-1]['rows'][-1]['t']>1.01:
            groups.append({'pair':values,'rows':[]})
        groups[-1]['rows'].append(row)
    stable=[]
    for g in groups:
        rows=g['rows'];strong=(len(rows)>=2 and rows[-1]['t']-rows[0]['t']>=.45
                                  and all(r.get('confidence',0)>=.9 for r in rows))
        if len(rows)>=3 or strong:
            stable.append({'t':rows[0]['t'],'end':rows[-1]['t'],'pair':g['pair']})
    events=[];gaps=[]
    for old,new in zip(stable,stable[1:]):
        delta=[new['pair'][i]-old['pair'][i] for i in (0,1)]
        if delta==[0,0]:continue
        row={'t':new['t'],'previous_t':old['end'],
             'previous':list(old['pair']),'score':list(new['pair'])}
        valid=(sum(d>0 for d in delta)==1 and all(0<=d<=3 for d in delta)
               and new['t']-old['end']<=1.01
               and not any(old['end']<t<=new['t'] for t in cuts))
        if valid:
            i=0 if delta[0] else 1
            events.append(dict(row,screen_side=('left','right')[i],delta=delta[i]))
        else:
            gaps.append(dict(row,reason='比分跨段或读数间隔较大，不能还原为单次投篮'))
    # Validate each side independently as well: one team scoring shortly after
    # the other must not erase the first team's short-lived full-score pair.
    for side in (0,1):
        runs=[]
        for row in sorted(reference.get('readings') or [],key=lambda r:r['t']):
            values=tuple(row.get('pair') or ())
            if len(values)!=2:continue
            if not runs or runs[-1][-1]['pair'][side]!=values[side] or row['t']-runs[-1][-1]['t']>1.01:
                runs.append([])
            runs[-1].append(row)
        runs=[rows for rows in runs if len(rows)>=3 or
              (len(rows)>=2 and rows[-1]['t']-rows[0]['t']>=.45 and
               all(r.get('confidence',0)>=.9 for r in rows))]
        for old,new in zip(runs,runs[1:]):
            a,b=old[-1],new[0];delta=b['pair'][side]-a['pair'][side]
            if not 1<=delta<=3 or a['pair'][1-side]!=b['pair'][1-side]:continue
            if b['t']-a['t']>1.01 or any(a['t']<t<=b['t'] for t in cuts):continue
            name=('left','right')[side]
            if any(e['t']==b['t'] and e['screen_side']==name for e in events):continue
            events.append({'t':b['t'],'previous_t':a['t'],'previous':list(a['pair']),
                           'score':list(b['pair']),'screen_side':name,'delta':delta})
    def explained(gap):
        delta=[gap['score'][i]-gap['previous'][i] for i in (0,1)]
        matching=[e for e in events if gap['previous_t']<e['t']<=gap['t']]
        return matching and all(delta[i]==sum(e['delta'] for e in matching
                                      if e['screen_side']==('left','right')[i]) for i in (0,1))
    gaps=[g for g in gaps if not explained(g)]
    return sorted(events,key=lambda e:e['t']),gaps


def apply_scoreboard(attempts, meta):
    """Return fresh attempts with background score-change evidence.

    A score update can confirm an existing shot through a unique temporal match
    in the same camera shot. Team mappings are optional consistency checks,
    never inferred from score-screen order. Manual decisions win.
    No unmatched score update creates an Attempt or a fake position.
    """
    attempts=copy.deepcopy(attempts)
    if os.environ.get('AIHOOP_DISABLE_SCOREBOARD_FUSION') == '1':
        return attempts,None
    ref=meta.get('scoreboard_reference_only') or {}
    if not ref:return attempts,None
    cuts=[float(f['t']) for f in (meta.get('legacy_shots') or {}).get('frames',[]) if f.get('cut')]
    events,gaps=score_changes(ref,cuts)
    mapping=meta.get('scoreboard_team_map') or {}
    mapped=set(mapping)=={'left','right'} and set(mapping.values())=={'home','away'}
    def compatible(a, e):
        # An existing team mapping can reject a mismatch; an absent mapping
        # must not disable outcome assistance or invent a player's identity.
        if mapped and (a.get('team') != mapping[e['screen_side']]
                       or 'team_unknown' in a.get('tags', [])):
            return False
        free_throw = bool(a.get('is_free_throw') or a.get('forced_value') == 1)
        if free_throw != (e['delta'] == 1):
            return False
        explicit_value = a.get('forced_value')
        if explicit_value in (2, 3) and not a.get('value_assumed') and explicit_value != e['delta']:
            return False
        t = float(a.get('decision_t') or a['t'])
        if not -.5 <= e['t'] - t <= 3.5:
            return False
        start = min(float(a['t']), t, e['t'])
        return not any(start < cut <= max(t, e['t']) for cut in cuts)

    # Build matches from the original evidence once. A score change must match
    # only one attempt, and that attempt must match only one score change.
    candidates = [[i for i, a in enumerate(attempts) if compatible(a, e)] for e in events]
    matches=[]
    for j,e in enumerate(events):
        e['team']=mapping.get(e['screen_side']) if mapped else None
        e['matched_attempt_t']=None
        if len(candidates[j]) != 1:
            continue
        i = candidates[j][0]
        if sum(i in group for group in candidates) != 1:
            continue
        a = attempts[i]
        e['matched_attempt_t']=a['t']
        if not a.get('manual'):
            a.update(made=True,conf=.95,forced_value=e['delta'],is_free_throw=e['delta']==1,
                     value_assumed=False,value_source='scoreboard',
                     counts_for_score=bool(a.get('counts_for_score', True)
                                           and a.get('team') in ('home', 'away')
                                           and 'team_unknown' not in a.get('tags', [])),
                     source='scoreboard',evidence='scoreboard_confirmed',review_reason='')
            a['tags']=[tag for tag in a.get('tags',[]) if tag not in
                       {'outcome_unknown','needs_review','inferred_outcome','legacy_insufficient_evidence',
                        'legacy_left_region_or_timeout','legacy_cross_measured','value_assumed'}]
            a['tags']+=['scoreboard_confirmed']
        matches.append({'attempt_t':a['t'],'score_t':e['t'],'delta':e['delta'],
                        'team':a.get('team'),'manual_preserved':bool(a.get('manual'))})
    board={'start':ref.get('screen_start'),'final':ref.get('screen_final'),
           'events':events,'gaps':gaps,'team_map':mapping if mapped else None,
           'matched_shots':matches,'readings':ref.get('ocr_hit',0),'samples':ref.get('n_crops',0),
           'final_t':max((float(r['t']) for r in ref.get('readings',[])),default=0.)}
    return attempts,board
