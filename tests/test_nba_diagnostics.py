import importlib.util
from pathlib import Path
import sys
import pytest
from aihoop.legacy_shots.settings import resolve_detect
from aihoop.legacy_shots.stream import LegacyShotStream
from aihoop.legacy_shots.detector import Det


def test_size_experiment_is_opt_in_and_records_actual_gate():
    box=Det('basketball',.95,(200,200,265,265))
    old=LegacyShotStream(30,1280,height=720,config={'detect':resolve_detect()})
    new=LegacyShotStream(30,1280,height=720,config={'detect':resolve_detect({
        'ball_max_reference_ratio':.16,'ball_filter_diagnostics':True})})
    assert old.preview_ball(0,[box])[0] is None
    selected,audits=new.preview_ball(0,[box])
    assert selected is box and audits[0]['size_limits_px']==[4.,153.6]
    assert resolve_detect()['ball_max_reference_ratio']==.06
    assert old.preview_ball(0,[box])[1][0]['selection_reason']=='size_rejected'
    with pytest.raises(ValueError):resolve_detect({'ball_max_reference_ratio':0})
    # Larger admissible size still cannot manufacture an event without a rim.
    new.update(0,0,[box]);assert new.finish(1,1/30)==[]


def test_diagnostic_distinguishes_prediction_and_missing_rim():
    scripts=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(scripts))
    try:
        spec=importlib.util.spec_from_file_location('nba_diag',scripts/'diagnose_nba_clip.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        stream=LegacyShotStream(30,1280,height=720)
        row={'frame':5,'t':5/30,'ball':{'predicted':True,'measurement':False,'xyxy':[1,2,3,4]},
             'tracked_rim':{'fresh':False}}
        result=module.blocking_evidence(row,stream.config)
        assert result['blocking_reasons']==['no_selected_model_measurement','rim_unavailable']
    finally:sys.path.remove(str(scripts))


def test_rim_contour_audit_explains_failure_without_inventing_geometry():
    import numpy as np
    import cv2
    from aihoop.hoop import refine_rim_candidate
    image=np.zeros((200,300,3),np.uint8)
    cv2.rectangle(image,(140,65),(147,80),(0,140,255),-1)
    rim,audit=refine_rim_candidate(image,Det('hoop',.9,(120,60,170,110)),contour_diagnostics=True)
    assert rim is None and audit['pixel_contours']
    assert all(c['reason']=='pixel_size_rejected' for c in audit['pixel_contours'])


def test_review_validator_accepts_rim_without_claiming_it_is_ball_truth():
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    spec=importlib.util.spec_from_file_location('review',scripts/'serve_match_labeling.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    item={'start_s':0,'end_s':3,'images':['frame_000000.jpg']}
    data={'shots':[],'frames':[{'image':'frame_000000.jpg','visibility':'unclear',
          'boxes':[{'kind':'rim','xyxy':[.1,.1,.3,.2]}]}]}
    assert module.validate(data,item)==data


def test_dense_window_keeps_original_frame_ids_and_rounded_end_frame(tmp_path):
    import cv2
    import numpy as np
    from types import SimpleNamespace
    scripts=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(scripts))
    try:
        spec=importlib.util.spec_from_file_location('score_experiment',scripts/'experiment_score_recovery.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        video=tmp_path/'window.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),30,(64,48))
        for _ in range(10):writer.write(np.zeros((48,64,3),np.uint8))
        writer.release()
        model=SimpleNamespace(predict=lambda *a,**kw:[SimpleNamespace(boxes=[],names={0:'basketball'})])
        cache={};context={i:{} for i in range(10)};window={'start_s':0,'end_s':.0999}
        result=module.reanalyze(video,window,model,{},context,cache)
        assert [r['frame'] for r in result['frames']]==[0,1,2,3]
        assert result['frames'][-1]['t']==.1 and result['events']==[]
        repeated=module.reanalyze(video,window,model,{},context,cache)
        assert repeated['full_frame_cache_hits']==4 and repeated['inference_calls']==0
    finally:sys.path.remove(str(scripts))
