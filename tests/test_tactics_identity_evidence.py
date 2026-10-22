import copy
from dataclasses import asdict
import numpy as np
import pytest

from aihoop.sources import stitch_player_tracks
from aihoop.tactics import PlayerSample
from aihoop.tactics_roster import (RosterEvidenceConfig,TrackletLinkEvaluator,
    torso_descriptor,appearance_distance,samples_signature,stitch_roster_evidence)


def sample(t,pid,x,team='team_a'):
    return PlayerSample(t,pid,team,x,4.)


def fixture():
    a=[sample(t,'a',t) for t in (0.,.1,.2)]
    b=[sample(t,'b',t) for t in (.3,.4,.5)]
    endpoints={}
    for pid,points in [('a',a),('b',b)]:
        obs=[{'frame':round(p.t*10),'t':p.t,'box':[100+p.t*10,100,140+p.t*10,200],
              'descriptor':[1.,0.]} for p in points]
        endpoints[pid]={'head':copy.deepcopy(obs),'tail':copy.deepcopy(obs)}
    camera={f'2:{i}':{'ok':True,'H':np.eye(3).tolist()} for i in (0,1,3,4,5)}
    return a,b,{'endpoints':endpoints,'camera_links':camera,'image_size':[640,480],
                'camera_size':[640,480],'proposals':[{'a':'a','b':'b'}]}


def run(a,b,data,**kwargs):
    cfg=RosterEvidenceConfig(stitch_tracks=True,**kwargs)
    return stitch_player_tracks(a+b,max_gap=.5,max_dist=1.5,max_iter=10,
        link_evaluator=TrackletLinkEvaluator(data,cfg),allow_unknown=True)


def test_same_camera_measured_motion_links_without_creating_observations_or_mutating():
    a,b,data=fixture();original=copy.deepcopy(a+b)
    joined,meta=run(a,b,data)
    assert meta['aliases']=={'b':'a'} and len(joined)==len(original)
    assert [(s.t,s.x,s.y) for s in joined]==[(s.t,s.x,s.y) for s in original]
    assert a+b==original


def test_pixel_association_survives_projected_position_jitter_without_relaxing_world_gate():
    a,b,data=fixture()
    for p in b:p.x+=.9
    assert not run(a,b,data,stitch_motion_space='court')[1]['aliases']
    joined,meta=run(a,b,data)
    assert meta['aliases']=={'b':'a'}
    assert meta['accepted_links'][0]['forward_error_m']>.75
    assert meta['accepted_links'][0]['camera_pixel_error_ratio']<.01
    assert joined[3].x==b[0].x  # no smoothed/fabricated ground coordinates


@pytest.mark.parametrize('fault,reason',[
    ('appearance','appearance_mismatch'),('camera','camera_continuity_unverified'),
    ('pixel_camera','pixel_camera_motion_unverified'),('short','insufficient_measured_endpoint_appearance'),
    ('time','endpoint_evidence_time_mismatch')])
def test_uncertain_or_contradicting_evidence_cannot_link(fault,reason):
    a,b,data=fixture()
    if fault=='appearance':
        for o in data['endpoints']['b']['head']:o['descriptor']=[0.,1.]
    elif fault=='camera':data['camera_links']['2:3']['ok']=False
    elif fault=='pixel_camera':data['camera_links'].pop('2:4')
    elif fault=='short':data['endpoints']['b']['head']=data['endpoints']['b']['head'][:1]
    elif fault=='time':data['endpoints']['b']['head'][0]['t']+=.01
    meta=run(a,b,data)[1]
    assert not meta['aliases']
    assert reason in meta['link_evaluations'][0]['rejection_reasons']


def test_cuts_team_conflicts_and_concurrent_tracks_are_never_merged():
    a,b,data=fixture();evaluator=TrackletLinkEvaluator(data)
    for rows,cuts in [(a+b,(.25,)),(a+[sample(p.t,'b',p.x,'team_b') for p in b],()),
                      (a+[sample(p.t-.2,'b',p.x) for p in b],())]:
        assert not stitch_player_tracks(rows,cuts=cuts,link_evaluator=evaluator,allow_unknown=True)[1]['aliases']


def test_plausible_unknown_alternative_with_missing_appearance_blocks_a_forced_match():
    a,b,data=fixture();c=[sample(p.t,'c',p.x+.05,'unknown') for p in b]
    # c lacks appearance evidence. Choosing b merely because it has a crop
    # would hide a physically plausible alternative.
    joined,meta=stitch_player_tracks(a+b+c,max_gap=.5,max_dist=1.5,
        link_evaluator=TrackletLinkEvaluator(data),allow_unknown=True)
    assert not meta['aliases'] and len({s.player_id for s in joined})==3


def test_chain_uses_original_endpoint_provenance_after_first_alias():
    rows=[sample(0,'a',0,'home'),sample(.1,'b',.1,'home'),sample(.2,'c',.2,'home')]
    calls=[]
    def evidence(a,b,ta,tb):
        calls.append((a,b))
        return {'accepted':(a,b) in [('a','b'),('b','c')],
                'plausible':(a,b) in [('a','b'),('b','c')]}
    joined,meta=stitch_player_tracks(rows,max_gap=.15,link_evaluator=evidence)
    assert meta['aliases']=={'b':'a','c':'a'}
    assert [p.player_id for p in joined]==['a']*3 and ('b','c') in calls


def test_linked_known_team_can_support_unknown_fragment_only_after_identity_gate():
    a,b,data=fixture()
    for p in b:p.team='unknown'
    joined,meta=run(a,b,data)
    assert meta['aliases'] and {p.team for p in joined}=={'team_a'}
    for o in data['endpoints']['b']['head']:o['descriptor']=[0.,1.]
    joined,meta=run(a,b,data)
    assert not meta['aliases'] and joined[-1].team=='unknown'


def test_defaults_and_filtered_roster_signature_prevent_stale_evidence():
    a,b,data=fixture();data['samples_signature']=samples_signature(a+b)
    raw_evidence={'identity_links':data}
    assert not RosterEvidenceConfig().stitch_tracks
    assert not stitch_roster_evidence(a+b,raw_evidence)[1]['enabled']
    assert stitch_roster_evidence(a+b,raw_evidence,cfg=RosterEvidenceConfig(stitch_tracks=True))[1]['aliases']
    with pytest.raises(ValueError,match='filtered roster'):
        stitch_roster_evidence(a,raw_evidence,cfg=RosterEvidenceConfig(stitch_tracks=True))


def test_torso_histogram_ignores_white_hue_noise_and_does_not_mutate_image():
    import cv2
    rng=np.random.default_rng(8);hsv=np.empty((100,60,3),np.uint8)
    hsv[:,:,0]=rng.integers(0,180,(100,60));hsv[:,:,1]=8;hsv[:,:,2]=200
    frame=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR);original=frame.copy()
    descriptor=torso_descriptor(frame,[0,0,60,100])
    hsv[:,:,0]=50;other=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
    assert appearance_distance(descriptor,torso_descriptor(other,[0,0,60,100]))<.01
    assert np.array_equal(frame,original)
    assert torso_descriptor(frame,[0,0,2,2]) is None
