import cv2
import numpy as np
from aihoop.legacy_shots.settings import resolve_detect
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.scorer import RimTracker
from aihoop.frame_motion import validated_forward_motion


def stream(**options):
    return LegacyShotStream(30,1280,height=720,config={'detect':resolve_detect({'general':options})})


def test_all_general_strategies_default_off():
    o=resolve_detect()['general']
    assert not any(o[k] for k in ('adaptive_ball','dynamic_rim','release_shadow','role_shadow','replay_shadow'))
    import pytest
    with pytest.raises(ValueError):resolve_detect({'general':{'replay_shadow':True}})


def test_size_growth_requires_independent_raw_model_votes():
    s=stream(adaptive_ball=True)
    s.update(0,0,[Det('basketball',.9,(220,300,268,348))])
    big=Det('basketball',.9,(228,292,298,362))
    for _ in range(10):assert s.preview_ball(1,[big])[0] is None
    s.update(1,1/30,[big]);assert not s.frames[-1]['ball']['measurement']
    s.update(2,2/30,[Det('basketball',.9,(236,284,306,354))])
    assert s.frames[-1]['ball']['measurement']
    assert s.frames[-1]['ball_candidates'][0]['size_adaptation']['mode']=='adaptive_confirmed'


def test_large_stationary_head_and_unseeded_logo_cannot_vote_to_expand():
    for persons in [[],[Det('person',.9,(170,160,350,600),'P')]]:
        s=stream(adaptive_ball=True)
        for i in range(12):s.update(i,i/30,[Det('basketball',.95,(225,180,295,250))],head_context=persons)
        assert s.real_seen==0


def test_cut_clears_adaptive_votes_and_predictions_expire():
    s=stream(adaptive_ball=True)
    s.update(0,0,[Det('basketball',.9,(220,300,268,348))])
    s.update(1,1/30,[Det('basketball',.9,(228,292,298,362))])
    s.update(2,2/30,[Det('basketball',.9,(236,284,306,354))],cut=True)
    assert s.frames[-1]['ball'] is None
    s.update(3,3/30,[Det('basketball',.9,(220,300,268,348))])
    for i in range(4,12):s.update(i,i/30,[])
    assert s.frames[-1]['ball_state']=='LOST' and s.frames[-1]['ball'] is None


def test_camera_compensation_is_forward_and_requires_distributed_pixels():
    rng=np.random.default_rng(73)
    a=cv2.GaussianBlur(rng.integers(0,255,(360,640),dtype=np.uint8),(3,3),0)
    b=cv2.warpAffine(a,np.float32([[1,0,30],[0,1,8]]),(640,360))
    audit=validated_forward_motion(a,b,resolve_detect()['general'])
    assert audit['ok']
    assert abs(audit['forward_H'][0][2]-30)<2
    assert not validated_forward_motion(a,np.zeros_like(a),resolve_detect()['general'])['ok']


def test_rim_prediction_never_refreshes_measurements_and_measured_pan_has_no_ema_lag():
    r=RimTracker(dynamic_enabled=True)
    old=Det('rim',.9,(280,190,360,210))
    r.update(old,0,0,60);r.update(old,1/30,1,60)
    r.compensate({'ok':True,'forward_H':[[1,0,70],[0,1,0],[0,0,1]]},2/30,2)
    assert r.last_seen_t==1/30 and r.cx==390 and not r.fresh(2/30,1.5)
    assert r.status(2/30,1.5)=='PREDICTED'
    r.update(Det('rim_refined',.9,(352,190,432,210)),2/30,2,60)
    assert r.cx==392 and r.fresh(2/30,1.5) and r.status(2/30,1.5)=='REFINED'
    r.compensate({'ok':False},3/30,3);r.update(None,3/30,3,60)
    assert r.status(3/30,1.5)=='STALE' and not r.fresh(3/30,1.5)
    assert r.status(2.,1.5)=='LOST'


def test_predicted_rim_cannot_create_a_formal_make():
    s=stream(dynamic_rim=True)
    rim=Det('rim',.9,(280,190,360,210))
    s.update(0,0,[rim]);s.update(1,1/30,[rim])
    for i,y in enumerate([150,170,190,220,250],2):
        s.engine.rim.compensate({'ok':True,'forward_H':[[1,0,0],[0,1,0],[0,0,1]]},i/30,i)
        s.update(i,i/30,[Det('basketball',.9,(310,y,326,y+16))])
    assert not s.finish(7,7/30)


def test_camera_transform_failure_breaks_chain_until_real_rim_reacquisition():
    r=RimTracker(dynamic_enabled=True)
    rim=Det('rim',.9,(280,190,360,210))
    shift={'ok':True,'forward_H':[[1,0,12],[0,1,0],[0,0,1]]}
    r.update(rim,0,0,60);r.update(rim,1/30,1,60)
    r.compensate(shift,2/30,2);r.update(None,2/30,2,60)
    assert r.cx==332 and r.status(2/30,1.5)=='PREDICTED'
    r.compensate({'ok':False},3/30,3);r.update(None,3/30,3,60)
    assert r.status(3/30,1.5)=='STALE'
    r.compensate(shift,4/30,4);r.update(None,4/30,4,60)
    assert r.cx==332 and not r.camera_verified
    assert r.status(4/30,1.5)=='STALE' and r.last_seen_frame==1
    # A real current measurement restores the reference frame for the next map.
    r.update(Det('rim',.9,(316,190,396,210)),4/30,4,60)
    r.compensate(shift,5/30,5);r.update(None,5/30,5,60)
    assert r.cx==368 and r.status(5/30,1.5)=='PREDICTED'
    assert r.last_seen_frame==4


def test_nonadjacent_or_future_time_does_not_claim_current_camera_prediction():
    r=RimTracker(dynamic_enabled=True)
    rim=Det('rim',.9,(280,190,360,210))
    shift={'ok':True,'forward_H':[[1,0,12],[0,1,0],[0,0,1]]}
    r.update(rim,0,0,60);r.update(rim,1/30,1,60)
    r.compensate(shift,3/30,3)
    assert r.cx==320 and r.status(3/30,1.5)=='STALE'
    r.update(rim,4/30,4,60);r.compensate(shift,5/30,5)
    assert r.status(5/30,1.5)=='PREDICTED'
    assert r.status(6/30,1.5)=='STALE'
