import copy
import pytest
from aihoop.made_shooter_recovery import MadeAttributionOptions, recover_made_shooter


def scene():
    person={'cls':'person','track_id':'A','xyxy':[70,100,130,300], 'on_court':True}
    frames=[]
    for i,(x,y) in enumerate([(100,170),(106,160),(180,80),(240,60),(280,80)]):
        ball=dict(cls='basketball',conf=.9,xyxy=[x-5,y-5,x+5,y+5],measurement=True)
        frames.append(dict(frame=i,t=i/30,ball=ball,persons=[dict(person)],evidence_segment=1))
    event=dict(type='make',result='made',crossing_t=4/30,rim_xy=[280,80],rim_w=30)
    return event,frames


def run(event,frames,**kw):
    return recover_made_shooter(event,frames,1920,
        options=MadeAttributionOptions(enabled=True),**kw)


def test_disabled_by_default_and_no_input_mutation():
    e,f=scene();before=copy.deepcopy((e,f))
    assert recover_made_shooter(e,f,1920)['status']=='DISABLED'
    r=run(e,f,players={'A':{'team':'home'}})
    assert r['status']=='ATTRIBUTION_PROPOSAL' and r['player_track_id']=='A'
    assert r['team']=='home' and r['release_t']==1/30
    assert r['counts_for_statistics'] is False and r['value'] is None
    assert (e,f)==before


@pytest.mark.parametrize('change', ['miss','unknown','suggestion'])
def test_only_existing_make_can_anchor_recovery(change):
    e,f=scene()
    if change=='suggestion':e['suggested_made']=True
    else:e['result']=change
    assert run(e,f)['reason']=='not_an_existing_confirmed_make'


@pytest.mark.parametrize('kind',['predicted','motion','head_rejected','off_court','referee'])
def test_untrusted_observations_or_roles_cannot_assign_player(kind):
    e,f=scene()
    for row in f:
        if kind=='predicted':row['ball']['predicted']=True
        if kind=='motion':row['ball'].update(cls='motion_ball',measurement=False)
        if kind=='head_rejected':
            row['ball_candidates']=[dict(row.pop('ball'),selection_reason='person_head')]
        if kind=='off_court':row['persons'][0]['on_court']=False
        if kind=='referee':row['persons'][0]['role']='REFEREE'
    assert run(e,f)['player_track_id'] is None


@pytest.mark.parametrize('kind',['cut','segment','long_gap','missing_people','overlap'])
def test_no_link_across_discontinuity_or_ambiguous_contact(kind):
    e,f=scene()
    if kind=='cut':f[2]['cut']=True
    if kind=='segment':
        for row in f[2:]:row['evidence_segment']=2
    if kind=='long_gap':
        for row in f[2:]:row['t']+=1
        e['crossing_t']+=1
    if kind=='missing_people':
        for row in f[2:]:row['persons']=[]
    if kind=='overlap':
        for row in f:row['persons'].append(dict(row['persons'][0],track_id='B'))
    assert run(e,f)['player_track_id'] is None


def test_unknown_team_is_not_forced_home():
    e,f=scene()
    assert run(e,f)['team'] is None


def test_release_feet_projected_at_release_time_for_two_and_three():
    e,f=scene();calls=[]
    class Cal:
        def __init__(self,y):self.y=y
        def to_court(self,x,y):return 0,self.y
        def in_court(self,x,y,tol):return True
    for y,value in [(-2,2),(9,3)]:
        def at(t):calls.append(t);return Cal(y)
        r=run(e,f,calibration_at=at)
        assert r['value']==value and r['release_t']==1/30
        assert all(t==1/30 for t in calls)
    # Being near the foul line alone cannot turn open play into a free throw.
    assert run(e,f,calibration_at=lambda t:Cal(5.8))['value']==2


def test_verified_ground_rechecks_stale_court_flag_but_rejects_spectator_feet():
    e,f=scene()
    for row in f:row['persons'][0]['on_court']=False
    class Cal:
        def __init__(self,valid):self.valid=valid
        def to_court(self,x,y):return 0,-2
        def in_court(self,*args,**kw):return self.valid
    assert run(e,f,calibration_at=lambda t:Cal(True))['player_track_id']=='A'
    r=run(e,f,calibration_at=lambda t:Cal(False))
    assert r['player_track_id'] is None
    assert any(x['reason']=='feet_outside_verified_court' for x in r['rejections'])


def test_budget_and_invalid_config():
    e,f=scene()
    r=recover_made_shooter(e,f,1920,options=MadeAttributionOptions(enabled=True,max_frames=2))
    assert r['reason']=='frame_budget_exceeded'
    with pytest.raises(ValueError):MadeAttributionOptions(max_gap_s=20)


def test_ball_flying_past_head_is_not_new_possession():
    e,f=scene();person=f[0]['persons'][0];f=[]
    points=[(300,120),(240,100),(180,90),(125,80),(110,80),(100,75),(180,40),(240,40)]
    for i,(x,y) in enumerate(points):
        f.append(dict(frame=i,t=i/30,evidence_segment=1,persons=[person],
            ball=dict(cls='basketball',measurement=True,conf=.9,xyxy=[x-5,y-5,x+5,y+5])))
    e.update(crossing_t=7/30,rim_xy=[240,40])
    r=run(e,f)
    assert r['player_track_id'] is None
    assert any(x['reason'] in ('brief_contact_after_free_flight','head_only_contact') for x in r['rejections'])


def test_reverse_reanalysis_restores_source_times_and_stops_at_cut(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sys
    import numpy as np
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts'))
    import experiment_score_recovery as experiment
    class Capture:
        def get(self,key):return {5:30,3:1920,4:1080}.get(key,0)
        def release(self):pass
    class Reader:
        def __init__(self,cap):pass
        def read(self,index):return True,np.zeros((10,10,3),dtype=np.uint8)
    class Model:
        def predict(self,*args,**kw):return [None]
    class Stream:
        def __init__(self,*args,**kw):self.frames=[]
        def preview_ball(self,*args,**kw):return None,None
        def update(self,step,t,dets,persons,**kw):
            self.frames.append(dict(ball=dets[0].as_dict(),ball_candidates=[dict(dets[0].as_dict())]))
    from aihoop.legacy_shots.detector import Det
    monkeypatch.setattr(experiment.cv2,'VideoCapture',lambda *a:Capture())
    monkeypatch.setattr(experiment,'FrameReader',Reader)
    monkeypatch.setattr(experiment,'LegacyShotStream',Stream)
    monkeypatch.setattr(experiment,'measured_detections',lambda result:[Det('basketball',.9,(100,100,110,110))])
    context={i:dict(frame=i,t=i/30,evidence_segment=1,cut=i==6,
        ball=dict(cls='basketball',conf=.9,xyxy=[100,100,110,110]),
        persons=[dict(cls='person',conf=.8,track_id='A',xyxy=[50,50,150,300],on_court=False)])
        for i in range(5,9)}
    original=copy.deepcopy(context)
    result=experiment.reanalyze_reverse('fixture.mp4',{'start_s':0},{'crossing_t':8/30},
        Model(),{},context)
    assert [r['frame'] for r in result['frames']]==[6,7,8]
    for row in result['frames']:
        assert row['t']==row['frame']/30
        assert row['persons'][0]['on_court'] is False
        assert row['ball_candidates'][0]['frame_id']==row['frame']
    assert result['outcomes_discarded'] is True and 'events' not in result
    assert context==original
