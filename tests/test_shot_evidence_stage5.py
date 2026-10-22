"""Evidence semantics, release ownership and measured geometry regressions."""
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.scorer import ScoreEngine, Attempt


def ball(x,y):
    return Det('basketball',.9,(x-5,y-5,x+5,y+5))


def person(pid='A',x=100):
    return Det('person',.9,(x-30,100,x+30,300),pid)


def history(engine, samples, persons=None):
    for index,(x,y) in enumerate(samples):
        engine.update(index,index/30,ball(x,y),None,persons or [person()])


def test_ball_by_feet_does_not_prove_possession_or_shooter():
    e=ScoreEngine({},30)
    history(e,[(100,290)]*4+[(180,80),(240,60)])
    assert e._bind_shooter(5/30)[1] is None


def test_overlapping_players_remain_unassigned():
    e=ScoreEngine({},30)
    history(e,[(100,170)]*4+[(180,80),(240,60)],[person('A'),person('B')])
    assert e._bind_shooter(5/30)[1] is None


def test_shooter_needs_observed_contact_then_observed_departure():
    e=ScoreEngine({},30)
    history(e,[(100,170),(106,160),(180,80),(240,60)])
    origin,pid,binding,t=e._bind_shooter(3/30)
    assert (pid,binding)==('A','contact_sequence')
    assert origin==(100,300) and t==1/30
    assert e.release_evidence['ball_xy']==(106,160)
    assert e.release_evidence['interval_s']==[1/30,2/30]


def test_single_contact_cannot_establish_shooter():
    e=ScoreEngine({},30)
    history(e,[(100,170),(180,80),(240,60)])
    assert e._bind_shooter(2/30)[1] is None


def test_measured_geometry_cannot_mix_x_and_y_from_different_frames():
    e=ScoreEngine({},30)
    e.recent_real.extend([(80,90),(120,60),(100,130)])
    assert e._smooth_xy(ball(100,130))==(100,130)


def test_unmapped_two_point_estimate_is_never_verified_score():
    e=ScoreEngine({},30)
    e.attempt=Attempt(0,0,(0,0),2,None)
    event=e._close(10,1/3,'make',ball(100,120))
    assert event['points']==2
    assert event['points_verified'] is False
    assert e.score==0


def test_unknown_value_cannot_reach_confirmed_team_score():
    from aihoop.legacy_shots.adapter import to_attempts
    from aihoop.sources import RawTrack
    from aihoop.model import Player
    from aihoop.rules import build_shots
    rt=RawTrack(fps=30,players={'A':Player('A','A','home')})
    event={'t':1.,'type':'make','player_id':'A','points':2,'points_verified':False}
    attempt=to_attempts([event],rt)[0]
    assert attempt.made is True and attempt.value_assumed
    assert build_shots([attempt.to_dict()])[0].score_points==0


def test_release_ball_position_and_time_come_from_the_same_observation():
    e=ScoreEngine({},30);rim=Det('rim',.9,(300,95,340,105))
    for i in (0,1):e.update(i,i/30,None,rim,[])
    for i,xy in enumerate([(100,170),(106,160),(180,120),(240,60)],2):
        e.update(i,i/30,ball(*xy),rim,[person()])
    event=e.finalize(6,.2)[0]
    assert event['release_known'] is True
    assert event['release_t']==.1
    assert event['ball_release_xy']==[106.,160.]
    assert event['candidate_t']==round(5/30,3)


def test_missing_person_during_departure_cannot_establish_release():
    e=ScoreEngine({},30)
    history(e,[(100,170),(106,160)])
    for i,xy in enumerate([(180,80),(240,60)],2):e.update(i,i/30,ball(*xy),None,[])
    assert e._bind_shooter(3/30)[1] is None


def test_timeout_uses_candidate_age_not_an_earlier_contact_time():
    e=ScoreEngine({},30)
    e.attempt=Attempt(90,0,(0,0),2,None,candidate_t=3.)
    e._advance_without_ball(3.6,108)
    assert e.attempt is not None
    e._advance_without_ball(6.6,198)
    assert e.attempt is None and e.events[0]['result']=='unknown'


def test_release_evidence_survives_final_json_pipeline():
    from aihoop.sources import RawTrack
    from aihoop.legacy_shots.adapter import to_attempts
    from aihoop.rules import build_shots
    from aihoop.pipeline import _shot_event
    rt=RawTrack(fps=30,duration=3.)
    event=dict(type='uncertain',t=2.,release_t=1.,candidate_t=1.5,
        release_known=True,release_evidence={'interval_s':[1.,1.1]},geometry_source='measured')
    attempt=to_attempts([event],rt)[0]
    shot=build_shots([attempt.to_dict()])[0]
    output=_shot_event(shot,rt)
    assert output['release_known'] is True
    assert output['release_evidence']=={'interval_s':[1.,1.1]}
    assert output['candidate_t']==1.5


def test_legacy_geometry_and_binding_are_explicit_comparison_modes():
    e=ScoreEngine({'score':{'ball_geometry_mode':'median3',
        'release_binding_mode':'legacy_nearest_feet'}},30)
    history(e,[(100,290)]*3)
    assert e._bind_shooter(2/30)[1]=='A'
    e.recent_real.clear();e.recent_real.extend([(80,90),(120,60),(100,130)])
    assert e._smooth_xy(ball(100,130))==(100,90)


def test_public_configuration_reaches_scorer_and_rejects_unsafe_counts():
    import pytest
    from pydantic import ValidationError
    from aihoop.legacy_shots.settings import resolve_detect
    from aihoop.legacy_shots.stream import LegacyShotStream
    options=resolve_detect({'shot_evidence':{'ball_geometry_mode':'median3'}})
    stream=LegacyShotStream(30,640,{'detect':options})
    assert stream.engine.ball_geometry_mode=='median3'
    with pytest.raises(ValidationError):resolve_detect({'shot_evidence':{'release_min_contact_frames':1}})


def test_unassigned_shooter_does_not_become_a_home_team_attempt():
    from aihoop.legacy_shots.adapter import to_attempts
    from aihoop.sources import RawTrack
    from aihoop.rules import build_shots,compute_team_stats,compute_player_stats
    from aihoop.pipeline import _team_name
    attempt=to_attempts([dict(type='make',t=1.,points_verified=False)],RawTrack(fps=30))[0]
    shot=build_shots([attempt.to_dict()])[0]
    assert shot.team=='unknown'
    assert compute_team_stats([shot],'home').fga==0
    assert compute_team_stats([shot],'away').fga==0
    assert compute_player_stats([shot])==[]
    assert _team_name(RawTrack(),shot.team)=='球队未知'
