import copy
import pytest
from aihoop.score_guided_recovery import RecoveryOptions,investigate_score_changes


def readings(pairs):
    return {'video_sha256':'synthetic-test-only','readings':[
        {'t':i*.5,'pair':pair,'confidence':.96} for i,pair in enumerate(pairs)]}


def investigate(ref,events=(),**kw):
    return investigate_score_changes(ref,events,options=RecoveryOptions(enabled=True),**kw)


def test_default_cannot_enable_online_fusion():
    assert investigate_score_changes(readings([[88,86]]*3+[[90,86]]*3))['enabled'] is False


@pytest.mark.parametrize('delta',[1,2,3])
def test_stable_change_is_display_fact_not_made_shot(delta):
    r=investigate(readings([[88,86]]*3+[[88+delta,86]]*3))
    assert len(r['facts'])==1 and r['facts'][0]['delta']==delta
    assert r['facts'][0]['physical_score_verified'] is False
    assert r['associations'][0]['shot_result']=='UNKNOWN'
    assert r['associations'][0]['shooter_track_id']=='UNKNOWN'
    assert len(r['windows'])==(0 if delta==1 else 1)


def test_single_bad_read_and_low_conf_stable_reads_do_not_create_change():
    ref=readings([[88,86]]*3+[[90,86]]+[[88,86]]*3)
    assert not investigate(ref)['facts']
    ref=readings([[88,86]]*3+[[90,86]]*3)
    for r in ref['readings'][3:]:r['confidence']=.6
    assert not investigate(ref)['facts']


def test_replay_regression_cannot_recreate_original_points():
    ref=readings([[90,86]]*3+[[88,86]]*3+[[90,86]]*3+[[92,86]]*3)
    result=investigate(ref)
    assert [f['score'] for f in result['facts']]==[[92,86]]
    assert any(r.get('reason')=='score_regression_quarantine' for r in result['rejected'])


@pytest.mark.parametrize('extra',[{'cuts':[1.5]},
    {'excluded_intervals':[{'start_s':1.,'end_s':2.,'reason':'replay'}]}])
def test_cut_or_known_replay_prevents_link(extra):
    assert not investigate(readings([[88,86]]*3+[[90,86]]*3),**extra)['facts']


def test_large_jump_and_both_teams_changed_not_single_basket():
    assert not investigate(readings([[88,86]]*3+[[93,86]]*3))['facts']
    assert not investigate(readings([[88,86]]*3+[[90,88]]*3))['facts']


def test_final_display_is_excluded():
    ref=readings([[115,115]]*3+[[115,118]]*3)
    for row in ref['readings']:row['period']='FINAL'
    assert not investigate(ref)['facts']


def test_unique_known_team_association_reuses_event_without_mutation():
    events=[{'event_id':'existing','start_t':1.,'team':'home','result':'unknown'}]
    original=copy.deepcopy(events)
    result=investigate(readings([[88,86]]*3+[[90,86]]*3),events,team_map={'left':'home','right':'away'})
    assert result['associations'][0]['forward_event_id']=='existing'
    assert result['associations'][0]['shot_result']=='UNKNOWN' and events==original


def test_two_shots_are_ambiguous_and_unknown_team_cannot_be_assigned():
    ref=readings([[88,86]]*3+[[90,86]]*3)
    events=[{'start_t':.1,'team':'home'},{'start_t':1.,'team':'home'}]
    assert investigate(ref,events,team_map={'left':'home','right':'away'})['associations'][0]['forward_event_index'] is None
    assert investigate(ref,events[:1])['associations'][0]['forward_event_index'] is None


def test_missing_scoreboard_reading_not_false_negative_miss():
    ref=readings([[88,86]]*3+[[90,86]]*3)
    for row in ref['readings'][3:]:row['t']+=5
    result=investigate(ref)
    assert not result['facts'] and result['discontinuities']


def test_invalid_inputs_and_bounded_windows():
    ref=readings([[88,86]]*3+[[90,86]]*3)
    ref['readings'].extend([{'t':float('nan'),'pair':[90,86],'confidence':.96},
                            {'t':5,'pair':[True,86],'confidence':.99}])
    result=investigate(ref)
    assert len(result['facts'])==1
    assert result['windows'][0]['start_s']==0
    with pytest.raises(ValueError):RecoveryOptions(lookback_max_s=2)


def test_failed_ocr_samples_remain_auditable_in_diagnostic_mode(monkeypatch):
    import numpy as np
    import aihoop.logo_scoreboard as board
    class Capture:
        def get(self,key):return {5:2,7:3}.get(key,0)
        def release(self):pass
    class Frames:
        def __init__(self,cap):pass
        def read(self,index):return True,np.zeros((50,100,3),np.uint8)
    class Reader:
        def readtext(self,*a,**kw):return [([[0,0],[10,0],[10,10],[0,10]],'118',.4)]
    monkeypatch.setattr(board.cv2,'VideoCapture',lambda *a:Capture())
    monkeypatch.setattr(board,'FrameReader',Frames)
    result=board.scan('test',Reader(),[0,0,50,20],diagnostic=True)
    assert result['usable'] is False and result['screen_start'] is None
    assert len(result['samples'])==3 and result['samples'][0]['raw_words'][0]['confidence']==.4
    with pytest.raises(ValueError):board.scan('test',Reader(),[0,0,50,20])
