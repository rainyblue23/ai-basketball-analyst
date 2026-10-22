import copy
from pathlib import Path
import sys
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from audit_recovery_pair import compare_traces,proximity_context
from aihoop.legacy_shots.stream import DEFAULT_CONFIG


def raw(ball):
    return dict(fps=30,width=1280,height=720,detections_meta={'legacy_shots':dict(
        config=copy.deepcopy(DEFAULT_CONFIG),events=[],frames=[dict(
            frame=3,t=.1,ball=ball,tracked_rim=None,ball_candidates=[])] )})


def test_audit_excludes_predictions_and_does_not_turn_changes_into_truth():
    prediction=dict(cls='basketball',xyxy=[10,10,20,20],predicted=True,measurement=False)
    observation={**prediction,'predicted':False,'measurement':True,'source':'rim_roi'}
    a=raw(prediction);b=raw(observation);frozen=copy.deepcopy((a,b))
    rows,s=compare_traces(a,b)
    assert rows[0]['change']=='observation_added'
    assert rows[0]['basketball_truth']=='UNKNOWN' and not rows[0]['counts_as_accuracy']
    assert s['tp'] is None and s['fp'] is None and s['fn'] is None
    assert s['before_model_observation_frames']==0 and s['after_model_observation_frames']==1
    assert (a,b)==frozen


@pytest.mark.parametrize('change',['time','frame','count','fps','duplicate'])
def test_audit_rejects_incompatible_frame_identity(change):
    a=raw(None);b=raw(None)
    af=a['detections_meta']['legacy_shots']['frames'];bf=b['detections_meta']['legacy_shots']['frames']
    if change=='time':bf[0]['t']+=.01
    if change=='frame':bf[0]['frame']+=1
    if change=='count':bf.append(copy.deepcopy(bf[0]))
    if change=='fps':b['fps']=25
    if change=='duplicate':af.append(copy.deepcopy(af[0]));bf.append(copy.deepcopy(bf[0]))
    with pytest.raises(ValueError):compare_traces(a,b)


def test_proximity_is_not_shooter_identity_and_ignores_predicted_people():
    row=dict(ball=dict(cls='basketball',xyxy=[18,18,22,22],measurement=True),persons=[
        dict(track_id='A',xyxy=[10,10,30,60]),dict(track_id='B',xyxy=[10,10,30,60]),
        dict(track_id='C',xyxy=[10,10,30,60],predicted=True)])
    result=proximity_context(row,dict(x_pad=.25,top=-.2,bottom=.55))
    assert result['status']=='ambiguous_overlap'
    assert {r['track_id'] for r in result['contacts']}=={'A','B'}
    assert not result['confirms_player_identity'] and not result['confirms_hand_contact']


def test_roi_interior_boundary_guard_preserves_source_audit_and_full_frame_support():
    from aihoop.legacy_shots.detector import Det
    from aihoop.legacy_shots.stream import LegacyShotStream
    from aihoop.legacy_shots.settings import resolve_detect
    from aihoop.ball_recovery import deduplicate_candidates,unconfirmed_crop_boundary
    crop=Det('basketball',.8,(290,180,299.8,198),source='rim_roi',region=(100,100,300,300))
    assert unconfirmed_crop_boundary(crop,640,360)
    assert not unconfirmed_crop_boundary(Det('basketball',.9,(630,180,640,198),source='ball_roi',region=(400,100,640,300)),640,360)
    def select(enabled,dets):
        s=LegacyShotStream(30,640,height=360,config={'detect':resolve_detect({'ball_roi_edge_guard':enabled})})
        return s.preview_ball(0,dets)
    assert select(False,[crop])[0] is crop
    chosen,audit=select(True,[crop]);assert chosen is None
    assert audit[0]['selection_reason']=='roi_boundary_unconfirmed' and audit[0]['xyxy']==list(crop.xyxy)
    full=Det('basketball',.5,crop.xyxy,source='full_frame')
    corroborated=deduplicate_candidates([crop,full])
    assert select(True,corroborated)[0] is not None
    interior=Det('basketball',.8,(250,180,270,200),source='ball_roi',region=(100,100,300,300))
    assert select(True,[interior])[0] is interior
