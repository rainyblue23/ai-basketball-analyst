from aihoop.legacy_shots.release_candidates import ShotReleaseCandidateDetector,link_forward_evidence
from aihoop.legacy_shots.settings import resolve_detect
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.player_roles import PlayerRoleClassifier
from aihoop.replay_candidates import ReplayCandidateLinker
import numpy as np
import cv2

P=Det('person',.9,(100,100,200,300),'P1')
R=dict(cx=320,cy=110,w=80,h=20,fresh=True,measured_at_t=True,status='DETECTED',segment=1)


def detector():return ShotReleaseCandidateDetector(30,resolve_detect()['general'])
def feed(d,points,rim=R):
    for i,xy in enumerate(points):
        people=[P] if len(xy)<3 or not xy[2] else [P,Det('person',.9,(230,100,330,300),'P2')]
        d.update(i,i/30,Det('basketball',.9,(xy[0]-6,xy[1]-6,xy[0]+6,xy[1]+6)),people,rim)
    d.update(35,35/30,None,[],None);d.finish()


def test_far_release_can_be_recorded_before_ball_reaches_rim_without_formal_score():
    d=detector();feed(d,[(150,155),(155,150),(235,125),(250,100),(275,70)])
    assert len(d.candidates)==1
    c=d.candidates[0]
    assert c['source_frame']==1 and c['player_track_id']=='P1'
    assert c['candidate_state']=='REVIEW_REQUIRED'
    assert c['shot_result']=='UNKNOWN' and not c['counts_for_statistics']


def test_receiver_contact_rejects_a_pass_and_rise_alone_is_insufficient():
    d=detector();feed(d,[(150,155),(155,150),(235,150),(250,150),(280,150,True),(290,150,True)],rim=None)
    assert d.candidates[0]['shot_type']=='PASS_LIKE'
    assert d.candidates[0]['candidate_state']=='REJECTED_NON_SHOT'
    d=detector();feed(d,[(150,155),(155,150),(235,125),(250,100),(275,70)],rim=None)
    assert d.candidates[0]['candidate_state']=='UNKNOWN'


def test_dribble_return_and_contested_possession_do_not_become_confirmed_shots():
    d=detector();feed(d,[(150,155),(155,150),(150,260),(155,300),(150,155),(155,150)],rim=None)
    assert d.candidates[0]['shot_type']=='DRIBBLE_OR_RETURN_LIKE'
    d=detector()
    for i in range(8):
        d.update(i,i/30,Det('basketball',.9,(145,145,155,155)),[P,Det('person',.9,P.xyxy,'P2')],R)
    assert d.last_phase=='CONTESTED_POSSESSION' and not d.candidates


def test_short_near_rim_attempt_stays_unknown_and_return_toss_is_continuation():
    d=detector();feed(d,[(150,155),(155,150),(235,145),(250,140),(150,155),(155,150),(235,170),(250,190)])
    assert len(d.candidates)>=2
    assert all(c['shot_result']=='UNKNOWN' for c in d.candidates)
    assert d.candidates[1]['possible_continuation_of']==d.candidates[0]['candidate_id']
    assert d.candidates[1]['candidate_state']=='UNKNOWN'


def test_prediction_and_motion_blob_never_supply_release_votes():
    d=detector()
    for i in range(10):
        d.update(i,i/30,Det('basketball',.9,(145,145,155,155),predicted=True),[P],R)
        d.update(i,i/30,Det('motion_ball',.9,(145,145,155,155)),[P],R)
    assert not d.history and not d.candidates


def test_weak_far_release_and_contested_reacquisition_remain_unknown():
    far=dict(R,cx=800)
    d=detector();feed(d,[(150,155),(155,150),(235,125),(250,100),(275,70)],rim=far)
    assert d.candidates[0]['candidate_state']=='UNKNOWN'
    d=detector();other=Det('person',.9,P.xyxy,'P2')
    d.update(0,0,Det('basketball',.9,(240,80,252,92)),[P],R)
    d.update(15,.5,Det('basketball',.9,(145,145,155,155)),[P,other],R)
    for i in range(16,22):d.update(i,i/30,Det('basketball',.9,(145,145,155,155)),[P],R)
    for i,x in ((22,240),(23,250),(24,275)):d.update(i,i/30,Det('basketball',.9,(x,110,x+12,122)),[P],R)
    d.update(50,50/30,None,[],None);d.finish()
    c=d.candidates[-1]
    assert c['candidate_state']=='UNKNOWN'
    assert any('contested_reacquisition' in r for r in c['rejection_reasons'])


def test_contested_return_after_observed_flight_needs_no_artificial_tracking_gap():
    d=detector();other=Det('person',.9,P.xyxy,'P2')
    for i,x in enumerate([245,270,300]):d.update(i,i/30,Det('basketball',.9,(x,60,x+12,72)),[P],R)
    d.update(3,3/30,Det('basketball',.9,(145,145,155,155)),[P,other],R)
    for i in range(4,10):d.update(i,i/30,Det('basketball',.9,(145,145,155,155)),[P],R)
    for i,x in ((10,240),(11,250),(12,275)):d.update(i,i/30,Det('basketball',.9,(x,100,x+12,112)),[P],R)
    d.update(40,40/30,None,[],None);d.finish();c=d.candidates[-1]
    assert c['features']['prior_free_flight'] and not c['features']['prior_observation_gap']
    assert c['candidate_state']=='UNKNOWN' and c['shot_result']=='UNKNOWN'


def test_cut_and_unknown_people_cannot_link_possession():
    d=detector()
    for i in range(2):d.update(i,i/30,Det('basketball',.9,(145+i,145,155+i,155)),[P],R)
    d.reset()
    for i in range(2,4):d.update(i,i/30,Det('basketball',.9,(235,120,247,132)),[P],R)
    assert not d.candidates


def test_shadow_mode_preserves_official_event_output():
    streams=[LegacyShotStream(30,640,height=360,config={'detect':resolve_detect({'general':g})})
             for g in ({},{'release_shadow':True})]
    rim=Det('rim',.9,(280,190,360,210))
    for i,y in enumerate([150,150,150,170,195,225,250]):
        for s in streams:s.update(i,i/30,[rim,Det('basketball',.9,(310,y,326,y+16))],[P])
    assert streams[0].finish(8,8/30)==streams[1].finish(8,8/30)
    assert streams[1].to_dict()['release_shadow']['counts_for_statistics'] is False


def test_time_proximity_without_shared_observations_does_not_link():
    c={'candidate_id':'C','features':{'source_frame_ids':[3,4]},'player_track_id':'P1'}
    frames=[{'frame':i,'t':i/30,'ball':{'measurement':True}} for i in range(5)]
    assert not link_forward_evidence([c],[{'t':.02,'candidate_t':0}],frames)
    assert link_forward_evidence([c],[{'t':.2,'candidate_t':0,'player_id':'P1'}],frames)


def test_role_votes_preserve_unknown_and_cut_resets_identity():
    options=resolve_detect()['general'];role=PlayerRoleClassifier(options)
    assert role.update([P],[])[0]['role']=='UNKNOWN'
    referee=Det('referee',.9,P.xyxy)
    for _ in range(4):rows=role.update([P],[referee])
    assert rows[0]['role']=='REFEREE'
    assert role.update([P],[],{'P1':False})[0]['spectator_hypothesis']
    role.reset();assert role.update([P],[])[0]['role']=='UNKNOWN'


def test_replay_sequence_links_are_only_uncertain_and_static_logo_is_insufficient():
    o=resolve_detect()['general'];linker=ReplayCandidateLinker(o)
    rng=np.random.default_rng(22);base=rng.integers(0,255,(160,240,3),dtype=np.uint8)
    images=[cv2.warpAffine(base,np.float32([[1,0,i*5],[0,1,i*3]]),(240,160)) for i in range(10)]
    for segment in range(2):
        for i,image in enumerate(images):linker.sample(i,segment*5+i/30,image)
        linker.observe({'candidate_id':str(segment),'timestamp':segment*5+.15,'segment':segment})
    assert linker.links and not linker.links[0]['automatic_merge'] and linker.links[0]['play_id']=='UNKNOWN'
    linker=ReplayCandidateLinker(o)
    for segment in range(2):
        for i in range(10):linker.sample(i,segment*5+i/30,base)
        linker.observe({'candidate_id':str(segment),'timestamp':segment*5+.15,'segment':segment})
    assert not linker.links
