from types import SimpleNamespace

import cv2
import numpy as np

from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.stream import LegacyShotStream


def test_roi_candidates_keep_original_frame_coordinates_and_provenance():
    from aihoop.ball_recovery import measured_detections, deduplicate_candidates
    result=SimpleNamespace(names={0:'basketball'},boxes=[SimpleNamespace(cls=[0],conf=[.8],xyxy=[(10,20,30,40)])])
    roi=measured_detections(result,(100,200),source='rim_roi',region=(100,200,300,400))
    full=Det('basketball',.9,(110,220,130,240),source='full_frame')
    candidates=deduplicate_candidates([full,*roi])
    assert len(candidates)==1
    assert candidates[0].xyxy==(110,220,130,240)
    assert set(candidates[0].support_sources)=={'full_frame','rim_roi'}
    assert full.support_sources==()
    assert roi[0].region==(100,200,300,400)


def test_candidate_dedup_does_not_merge_different_balls_or_change_confidence():
    from aihoop.ball_recovery import deduplicate_candidates
    a=Det('basketball',.4,(100,100,116,116),source='full_frame')
    b=Det('basketball',.3,(101,101,117,117),source='ball_roi')
    c=Det('basketball',.5,(300,300,316,316),source='full_frame')
    rim=Det('rim',.9,(100,100,130,116))
    rows=deduplicate_candidates([a,b,c,rim])
    assert len(rows)==3
    assert next(r for r in rows if r.xyxy==a.xyxy).conf==.4
    assert rim in rows and c.xyxy in [r.xyxy for r in rows]


def test_low_confidence_observations_require_independent_motion_and_context():
    from aihoop.legacy_shots.settings import resolve_detect
    options=resolve_detect({'ball_candidate_conf':.15,'ball_low_conf_confirm':True})
    stream=LegacyShotStream(30,640,height=360,config={'detect':options})
    rim=Det('rim',.9,(280,190,360,210))
    for index in (0,1):stream.update(index,index/30,[rim])
    for index,x in ((2,270),(3,278),(4,286)):
        stream.update(index,index/30,[rim,Det('basketball',.2,(x,144,x+12,156))])
    assert stream.frames[2]['ball'] is None
    assert stream.frames[3]['ball'] is None
    assert stream.frames[4]['ball']['measurement'] is True
    assert stream.frames[4]['ball']['conf']==.2
    assert stream.real_seen==1


def test_repeated_previews_or_stationary_low_confidence_boxes_cannot_confirm():
    from aihoop.legacy_shots.settings import resolve_detect
    stream=LegacyShotStream(30,640,height=360,config={'detect':resolve_detect({
        'ball_candidate_conf':.15,'ball_low_conf_confirm':True})})
    rim=Det('rim',.9,(280,190,360,210));ball=Det('basketball',.2,(290,144,302,156))
    for index in (0,1):stream.update(index,index/30,[rim])
    for _ in range(10):assert stream.preview_ball(2,[ball])[0] is None
    assert stream.low_conf_history==[]
    for index in range(2,10):stream.update(index,index/30,[rim,ball])
    assert stream.real_seen==0


def test_low_confidence_confirmation_cannot_bridge_cut_or_missing_context():
    from aihoop.legacy_shots.settings import resolve_detect
    config={'detect':resolve_detect({'ball_candidate_conf':.15,'ball_low_conf_confirm':True})}
    stream=LegacyShotStream(30,640,height=360,config=config)
    for index in range(5):
        stream.update(index,index/30,[Det('basketball',.2,(200+index*8,140,212+index*8,152))])
    assert stream.real_seen==0
    assert stream.events==[]


def test_cut_preview_does_not_confirm_with_the_previous_shot_history():
    from aihoop.legacy_shots.settings import resolve_detect
    stream=LegacyShotStream(30,640,height=360,config={'detect':resolve_detect({
        'ball_candidate_conf':.15,'ball_low_conf_confirm':True})})
    rim=Det('rim',.9,(280,190,360,210))
    for index in (0,1):stream.update(index,index/30,[rim])
    for index,x in ((2,270),(3,278)):
        stream.update(index,index/30,[rim,Det('basketball',.2,(x,144,x+12,156))])
    next_ball=Det('basketball',.2,(286,144,298,156))
    assert stream.preview_ball(4,[next_ball],cut=True)[0] is None
    stream.update(4,4/30,[rim,next_ball],cut=True)
    assert stream.real_seen==0


def test_a_head_false_positive_cannot_prevent_roi_retry(tmp_path,monkeypatch):
    import sys
    import aihoop.screen_graphics as graphics
    import aihoop.ball_recovery as recovery
    import aihoop.legacy_shots.stream as stream_module
    from aihoop.sources import VideoSource
    from aihoop.court import Calibration
    path=tmp_path/'head.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30,(640,360))
    for _ in range(8):writer.write(np.zeros((360,640,3),np.uint8))
    writer.release()
    person=SimpleNamespace(cls=[0],conf=[.9],id=[1],xyxy=[(200,80,260,300)])
    class PersonBoxes(list):
        id=np.array([1])
    p_result=SimpleNamespace(names={0:'person'},boxes=PersonBoxes([person]))
    b_result=SimpleNamespace(names={0:'basketball'},boxes=[SimpleNamespace(cls=[0],conf=[.99],xyxy=[(224,104,236,116)])])
    def model(weights):
        return SimpleNamespace(track=lambda *a,**k:[p_result],predict=lambda *a,**k:[b_result])
    monkeypatch.setitem(sys.modules,'ultralytics',SimpleNamespace(YOLO=model))
    monkeypatch.setattr(graphics,'probe',lambda *a,**k:{'graphics':[]})
    real_stream=stream_module.LegacyShotStream
    def seeded(*args,**kwargs):
        stream=real_stream(*args,**kwargs)
        rim=Det('rim',.9,(290,190,350,210))
        stream.engine.rim.update(rim,-2/30,-2,60,2,1.5)
        stream.engine.rim.update(rim,-1/30,-1,60,2,1.5)
        return stream
    monkeypatch.setattr(stream_module,'LegacyShotStream',seeded)
    calls=[]
    def recover(*args):
        calls.append(True)
        return [Det('basketball',.8,(320,164,332,176))],{'ran':True,'candidates':[]}
    monkeypatch.setattr(recovery,'recover_rim',recover)
    source=VideoSource(str(path),Calibration(method='unavailable'),weights='person',ball_weights='ball',
        device='cpu',scoreboard=False,auto_sliding=False,legacy_detect={'ball_rim_recovery':True})
    raw=source.run()
    assert calls,'an easy head false positive suppressed ROI recovery'
    first=raw.detections_meta['legacy_shots']['frames'][0]
    assert first['ball']['xyxy']==[320,164,332,176]
    assert any(c['selection_reason']=='person_head' for c in first['ball_candidates'])


def test_camera_motion_guard_keeps_pan_but_not_an_unrelated_cut():
    from aihoop.frame_motion import estimate_frame_motion
    rng=np.random.default_rng(28)
    first=rng.integers(0,255,(360,640),dtype=np.uint8)
    first=cv2.GaussianBlur(first,(3,3),0)
    moved=cv2.warpAffine(first,np.float32([[1,0,35],[0,1,-12]]),(640,360))
    result=estimate_frame_motion(first,moved,min_matches=20,ok_ratio=.45)
    assert result['ok'] and result['grid_cells']>=3
    other=cv2.GaussianBlur(rng.integers(0,255,(360,640),dtype=np.uint8),(3,3),0)
    assert not estimate_frame_motion(first,other,min_matches=20,ok_ratio=.45)['ok']


def test_static_broadcast_graphics_alone_cannot_hide_a_cut():
    from aihoop.frame_motion import estimate_frame_motion
    rng=np.random.default_rng(29)
    first=np.zeros((360,640),np.uint8);second=np.full_like(first,180)
    logo=rng.integers(0,255,(75,140),dtype=np.uint8)
    for image in (first,second):
        image[10:85,10:150]=logo
        image[275:350,490:630]=logo
    result=estimate_frame_motion(first,second,min_matches=20,ok_ratio=.45)
    assert not result['ok']


def test_missing_specialist_model_preserves_existing_coco_ball_fallback(tmp_path,monkeypatch):
    import sys
    import aihoop.screen_graphics as graphics
    from aihoop.sources import VideoSource
    from aihoop.court import Calibration
    path=tmp_path/'fallback.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30,(640,360))
    for _ in range(8):writer.write(np.zeros((360,640,3),np.uint8))
    writer.release()
    class Boxes(list):
        id=np.array([1])
    result=SimpleNamespace(names={32:'sports ball'},boxes=Boxes([
        SimpleNamespace(cls=[32],conf=[.8],id=[1],xyxy=[(250,210,266,226)])]))
    monkeypatch.setitem(sys.modules,'ultralytics',SimpleNamespace(
        YOLO=lambda _:SimpleNamespace(track=lambda *a,**k:[result])))
    monkeypatch.setattr(graphics,'probe',lambda *a,**k:{'graphics':[]})
    raw=VideoSource(str(path),Calibration(method='unavailable'),weights='person',
        ball_weights=None,device='cpu',scoreboard=False,auto_sliding=False).run()
    assert raw.detections_meta['ball']['candidates']>0
