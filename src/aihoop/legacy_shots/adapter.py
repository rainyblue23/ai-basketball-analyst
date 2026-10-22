"""旧事件转换为新版 Attempt；不导入旧应用、统计或估算三分。"""
import math

def to_attempts(events, rt, calibration=None, value=2, counts_for_score=True):
    from ..sources import Attempt
    result=[]
    for event in events:
        t=float(event.get('release_t',event['t']))
        pid=str(event['player_id']) if event.get('player_id') is not None else ''
        player=rt.players.get(pid)
        known_team=bool(player and player.team in ('home','away'))
        team=player.team if known_team else 'unknown'
        kind=event['type'];made={'make':True,'miss':False,'uncertain':None}[kind]
        suggestion=event.get('suggested_made')
        evidence=('legacy_occlusion_descent' if suggestion is not None and event.get('review_reason') == 'occlusion_descent_suggestion' else
                  'legacy_occluded_entry' if suggestion is not None else
                  'legacy_cross_measured' if made is True else
                  'legacy_left_region_or_timeout' if made is False else
                  'legacy_insufficient_evidence')
        tags=[evidence,'legacy_shot_engine']
        if made is None:tags+=['outcome_unknown','needs_review']
        if suggestion is not None:tags+=['inferred_outcome','needs_review'];made=None
        if not known_team:tags+=['team_unknown','needs_review']
        if event.get('points_verified') is False:tags+=['value_unconfirmed']
        a=Attempt(t=t,team=team,player_id=pid or 'UNASSIGNED',x=0.,y=-1.575,
            made=made,conf=.8 if made is not None else .4,source='legacy_ball_rim',
            release_frame=round(t*rt.fps),location_source='rim_placeholder',location_estimated=True,
            forced_value=value,value_assumed=True,value_source='default',
            counts_for_score=counts_for_score and known_team and made is not None
                             and event.get('points_verified') is not False,
            tags=list(dict.fromkeys(tags)),evidence=evidence,
            review_reason=event.get("review_reason") or "",
            crossing_t=event.get('crossing_t',event.get('rim_crossing_t')),
            suggested_made=suggestion, review_t=event.get('review_t'), decision_t=float(event["t"]),
            release_source=event.get("release_source", ""),
            release_known=event.get('release_known'),
            release_evidence=dict(event.get('release_evidence') or {}),
            candidate_t=event.get('candidate_t'),geometry_source=event.get('geometry_source',''),
            clip_end=min(rt.duration, float(event['t'])+1.5) if rt.duration>0 else float(event['t'])+1.5)
        # 只把出手人脚下投到地面；空中篮球不能当作地面出手点。
        xy=event.get('release_xy')
        cal = calibration(t) if callable(calibration) else calibration
        if (cal is not None and rt.detections_meta.get('calibration_valid')
                and event.get('release_source')=='player_feet' and xy):
            x,y=cal.to_court(*xy)
            if math.isfinite(x) and math.isfinite(y) and abs(x)<=9 and abs(y)<=16:
                a.x,a.y=x,y;a.location_source='player_feet';a.location_estimated=False
                from ..rules import is_free_throw_position
                if is_free_throw_position(x, y):
                    a.is_free_throw=True;a.forced_value=1
                    a.value_assumed=False;a.value_source='free_throw_geometry'
                    a.tags.append('free_throw_detected')
                else:
                    a.forced_value=None;a.value_assumed=False;a.value_source='court_geometry'
                a.counts_for_score=counts_for_score and known_team and made is not None
                a.tags=[tag for tag in a.tags if tag!='value_unconfirmed']
        result.append(a)
    return sorted(result,key=lambda a:a.t)
