import copy
from types import SimpleNamespace
import numpy as np
import cv2

from aihoop.sources import VideoSource
from aihoop.tactics import PlayerSample, population_status, build_tactics, TacticsConfig, detect_passes, PlayerIndex
from aihoop.tactics_roster import RosterEvidenceConfig, apply_roster_evidence


def test_skin_mask_preserves_white_and_saturated_jersey_pixels():
    # Medium-saturation background must not displace a majority white/blue/red jersey.
    for color in [(0,10,200),(110,220,180),(0,230,180)]:
        hsv=np.zeros((100,50,3),np.uint8)
        hsv[:]=color
        hsv[25:36,12:38]=(70,70,150)
        bgr=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        actual=VideoSource._jersey_color_of(bgr,[0,0,50,100])
        assert abs(actual[1]-color[1])<5


def test_conservative_teams_use_multiple_votes_and_mark_short_tracks_unknown():
    players={p:SimpleNamespace(team='away') for p in ['a','b','c','d','short','mixed']}
    rt=SimpleNamespace(players=players,detections_meta={})
    records={}
    for pid,sat in [('a',10),('b',12),('c',210),('d',212),('mixed',12)]:
        colors=[(100,sat,180)]*4
        if pid=='mixed': colors=[(100,10,180)]*2+[(100,210,180)]*2
        records[pid]={'n':4,'bins':{(12,int(sat)//32,2):4},'colors':colors}
    records['short']={'n':1,'bins':{(12,6,2):1},'colors':[(100,210,180)]}
    VideoSource._assign_teams(SimpleNamespace(jersey_teams=None),rt,records,conservative=True)
    assert players['a'].team==players['b'].team
    assert players['a'].team!=players['c'].team
    assert players['short'].team==players['mixed'].team=='unknown'
    assert rt.detections_meta['teams']['home_away_mapping_verified'] is False


def test_white_jersey_hue_noise_does_not_let_a_small_coloured_stripe_win():
    rng=np.random.default_rng(4)
    hsv=np.empty((100,50,3),np.uint8)
    hsv[:,:,0]=rng.integers(0,180,(100,50))
    hsv[:,:,1]=8
    hsv[:,:,2]=210
    hsv[30:39,12:38]=(170,210,160)
    actual=VideoSource._jersey_color_of(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),[0,0,50,100])
    assert actual[1]<20 and actual[2]>190


def test_low_saturation_hue_is_never_used_as_team_separation():
    players={str(i):SimpleNamespace(team='away') for i in range(8)}
    records={}
    for i,pid in enumerate(players):
        color=(5 if i<4 else 100, 10 if i<4 else 220, 180)
        records[pid]={'n':4,'bins':{tuple(int(v)//d for v,d in zip(color,(8,32,64))):4},'colors':[color]*4}
    rt=SimpleNamespace(players=players,detections_meta={})
    VideoSource._assign_teams(SimpleNamespace(jersey_teams=None),rt,records,conservative=True)
    assert rt.detections_meta['teams']['method']=='color-2means:sat'
    assert rt.detections_meta['teams']['rejected_features']['hue']=='low_saturation_hue_is_unreliable'


def test_warm_tinted_jersey_is_not_replaced_by_its_red_stripe_in_torso_trial():
    hsv=np.empty((100,50,3),np.uint8)
    hsv[:]=(12,55,190)  # valid fabric inside the old skin mask
    hsv[30:38,12:38]=(170,210,160)
    color=VideoSource._jersey_color_of(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),[0,0,50,100],skin_filter=False)
    assert color[1]<60 and color[2]>180


def test_roster_defaults_preserve_input_and_roles_are_time_local():
    s=[PlayerSample(t,'p','away',0,5) for t in (0,.1,1)]
    evidence={'observations':[{'t':.1,'player_id':'p','role':'REFEREE','confidence':.85}]}
    old=copy.deepcopy(s)
    unchanged,decisions=apply_roster_evidence(s,evidence)
    assert unchanged==old and not decisions and s==old
    filtered,decisions=apply_roster_evidence(s,evidence,RosterEvidenceConfig(use_roles=True))
    assert [p.t for p in filtered]==[0,1]
    assert len(decisions)==1 and s==old
    evidence['observations'][0]['confidence']=.5
    assert len(apply_roster_evidence(s,evidence,RosterEvidenceConfig(use_roles=True))[0])==3


def test_unknown_membership_is_not_a_third_team_and_does_not_create_team_stats():
    pos={str(i):(i,5) for i in range(7)}
    assert population_status(pos,{p:'unknown' for p in pos})['valid']
    assert not population_status(pos,{p:'home' for p in pos})['valid']
    assert not population_status({str(i):(i,5) for i in range(11)}, {})['valid']
    samples=[PlayerSample(t,p,'unknown',x,y) for t in range(4) for p,(x,y) in pos.items()]
    tac=build_tactics(samples,[],duration=3,cfg=TacticsConfig(roster_evidence_filter=True))
    assert not tac.get('spacing_timeline')
    spells=[{'t0':0,'t1':1,'player_id':'0','team':'unknown'}, {'t0':1.5,'t1':2,'player_id':'6','team':'unknown'}]
    assert detect_passes(spells,PlayerIndex(samples,TacticsConfig()),TacticsConfig())==[]
    from aihoop.tactics import detect_possessions
    ball=[SimpleNamespace(t=i*.2,x=0,y=5) for i in range(11)]
    assert detect_possessions(ball,PlayerIndex(samples,TacticsConfig()),TacticsConfig())==[]
    from aihoop.tactics import detect_passes_from_flights
    flight=[SimpleNamespace(t=t,x=x,y=5) for t,x in [(0,0),(.2,3),(1,6)]]
    events=detect_passes_from_flights([flight],PlayerIndex(samples,TacticsConfig()),TacticsConfig())
    assert events[0]['kind']=='unattributed' and not events[0]['same_team']


def test_pipeline_evidence_is_opt_in_bound_to_input_and_preserves_shots(tmp_path):
    import pytest
    from aihoop.sources import RawTrack
    from aihoop.model import Player
    from aihoop.pipeline import PipelineConfig, run_pipeline
    from aihoop.tactics_roster import roster_signature
    raw=RawTrack(fps=25,duration=3,video_path='unused.mp4',width=960,height=544)
    raw.detections_meta.update(calibration_valid=True)
    for i in range(7):
        pid=f'T{i}'
        raw.players[pid]=Player(player_id=pid,name='unknown',team='home')
        for j in range(31):
            raw.player_track.append(PlayerSample(j/10,pid,'home',-6+i*2,2+i*1.5))
    before=copy.deepcopy(raw)
    from dataclasses import asdict
    evidence={'input_signature':roster_signature(raw),'teams':{'assignments':{}},'observations':[],
              'config':asdict(RosterEvidenceConfig())}
    base=run_pipeline(raw,PipelineConfig(out_dir=str(tmp_path/'before'),make_highlights=False))
    result=run_pipeline(raw,PipelineConfig(out_dir=str(tmp_path/'after'),make_highlights=False,
        tactics=TacticsConfig(roster_evidence_filter=True),tactics_roster=RosterEvidenceConfig(use_teams=True),
        tactics_roster_evidence=evidence))
    assert raw==before
    assert result.shotchart==base.shotchart and result.players==base.players
    assert result.game['timeline']==base.game['timeline']
    assert result.tactics['available'] and not result.tactics['team_analysis_available']
    assert result.tactics['team_identity']['verified'] is False
    bad=copy.deepcopy(raw);bad.fps=24
    with pytest.raises(ValueError,match='does not match'):
        run_pipeline(bad,PipelineConfig(out_dir=str(tmp_path/'mismatch'),make_highlights=False,
            tactics_roster=RosterEvidenceConfig(use_teams=True),tactics_roster_evidence=evidence))
    assert not (tmp_path/'mismatch').exists()
    with pytest.raises(ValueError,match='configuration mismatch'):
        run_pipeline(raw,PipelineConfig(out_dir=str(tmp_path/'mismatch-config'),make_highlights=False,
            tactics_roster=RosterEvidenceConfig(use_teams=True,team_min_votes=5),tactics_roster_evidence=evidence))
