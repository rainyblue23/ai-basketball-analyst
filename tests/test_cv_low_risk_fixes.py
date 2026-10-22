import copy

import cv2
import numpy as np

from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.settings import resolve_detect
from aihoop.legacy_shots.stream import LegacyShotStream, ball_visibility, replay_trace
from aihoop.sources import stitch_player_tracks
from aihoop.tactics import PlayerSample


def test_small_real_candidates_are_not_discarded_by_hd_frame_width():
    stream = LegacyShotStream(30, 1920, height=1080)
    for size in (4, 6, 8, 11, 12):
        ball = Det('basketball', .9, (500, 500, 500+size, 500+size))
        picked, _ = stream.preview_ball(0, [ball])
        assert picked is ball
    tiny = Det('basketball', .9, (500, 500, 503, 503))
    assert stream.preview_ball(0, [tiny])[0] is None


def test_small_candidate_gate_can_restore_old_ratio_for_ablation():
    config = resolve_detect({'ball_min_side_px': None})
    stream = LegacyShotStream(30, 1920, config={'detect': config})
    ball = Det('basketball', .9, (500, 500, 508, 508))
    assert stream.preview_ball(0, [ball])[0] is None


def test_motion_blob_cannot_refresh_detector_anchor_or_create_shot():
    stream = LegacyShotStream(30, 640)
    rim = Det('rim', .9, (280, 190, 360, 210))
    stream.update(0, 0, [rim, Det('basketball', .8, (310, 130, 326, 146))])
    for index in range(1, 25):
        blob = Det('motion_ball', .99, (312, 200, 328, 216))
        stream.update(index, index/30, [rim, blob])
    assert stream.last_frame == 0 or stream.last_ball is None
    assert stream.real_seen == 1
    assert stream.events == []
    assert any(c['selection_reason'] == 'motion_only' for f in stream.frames for c in f['ball_candidates'])


def test_old_motion_trace_is_not_reclassified_as_measured_when_replayed():
    stream = LegacyShotStream(30, 640)
    rim = Det('rim', .9, (280, 190, 360, 210))
    for index, y in enumerate((130, 140, 160, 190, 220, 240)):
        stream.update(index, index/30, [rim])
        stream.frames[-1]['ball'] = {'cls':'motion_ball', 'conf':.9,
            'xyxy':[312, y, 328, y+16], 'predicted':False}
    trace = stream.to_dict()
    assert ball_visibility(trace['frames'], 30)['observed_frames'] == 0
    assert replay_trace(trace) == []


def sample(t, pid, team='home', x=0):
    return PlayerSample(t=t, player_id=pid, team=team, x=x, y=0)


def test_stitch_never_changes_team_or_crosses_camera_cut():
    for rows, cuts in (([sample(1,'A'),sample(2,'B','away',.2)],()),
                       ([sample(1,'A'),sample(2,'B',x=.2)],(1.5,))):
        original = copy.deepcopy(rows)
        joined, meta = stitch_player_tracks(rows, cuts=cuts)
        assert {x.player_id for x in joined} == {'A','B'}
        assert rows == original
        assert meta['raw_tracks'] == 2


def test_stitch_unique_same_team_records_alias_without_mutating_input():
    rows = [sample(1,'A'),sample(2,'B',x=.2)]
    original = copy.deepcopy(rows)
    joined, meta = stitch_player_tracks(rows)
    assert {x.player_id for x in joined} == {'A'}
    assert meta['raw_tracks'] == 2 and meta['merged_tracks'] == 1
    assert meta['aliases'] == {'B':'A'}
    assert rows == original


def test_stitch_ambiguous_or_unknown_players_keep_separate_ids():
    for rows in ([sample(1,'A'),sample(2,'B',x=.2),sample(2,'C',x=.3)],
                 [sample(1,'A','unknown'),sample(2,'B','unknown',.2)]):
        joined, _ = stitch_player_tracks(rows)
        assert len({x.player_id for x in joined}) == len(rows)


def test_region_refinement_needs_pixel_evidence_and_preserves_parent_coordinates():
    from aihoop.hoop import refine_rim_candidate
    image = np.zeros((180,260,3),np.uint8)
    cv2.ellipse(image,(130,65),(20,5),0,0,360,(0,140,255),2)
    coarse = Det('hoop', .9, (108,60,152,110))
    refined, audit = refine_rim_candidate(image, coarse)
    assert refined is not None
    assert abs(refined.cx-130)<=2 and abs(refined.cy-65)<=2
    assert refined.w/refined.h>=1.8
    assert coarse.xyxy == (108,60,152,110)
    assert audit['parent_box'] == [108,60,152,110]
    empty, _ = refine_rim_candidate(np.zeros_like(image),coarse)
    assert empty is None


def test_refinement_does_not_accept_solid_or_ambiguous_orange_patches():
    from aihoop.hoop import refine_rim_candidate
    coarse = Det('hoop', .9, (108,60,152,110))
    image=np.zeros((180,260,3),np.uint8)
    cv2.rectangle(image,(110,60),(150,71),(0,140,255),-1)
    assert refine_rim_candidate(image,coarse)[0] is None
    image[:]=0
    for y in (50,75):cv2.ellipse(image,(130,y),(20,5),0,0,360,(0,140,255),2)
    assert refine_rim_candidate(image,coarse)[0] is None


def test_rim_roi_requires_current_rim_not_merely_initialized_state():
    from aihoop.ball_recovery import rim_recovery_region
    stream=LegacyShotStream(30,640)
    for index in (0,1):stream.update(index,index/30,[Det('rim',.9,(280,190,360,210))])
    assert rim_recovery_region(stream,2,640,360) is not None
    assert rim_recovery_region(stream,100,640,360) is None


def test_refinement_config_can_be_disabled_and_rejects_inverted_ranges():
    import pytest
    from pydantic import ValidationError
    from aihoop.legacy_shots.settings import LegacyDetectOptions
    assert resolve_detect({'rim_refinement':False})['rim_refinement'] is False
    with pytest.raises(ValidationError):
        LegacyDetectOptions(rim_refinement_options={'min_width_ratio':1.5,'max_width_ratio':.5})


def test_native_rim_and_manual_seed_are_not_refined_as_coarse_regions():
    stream=LegacyShotStream(30,640)
    image=np.zeros((360,640,3),np.uint8)
    rim=Det('rim',.9,(280,190,360,210))
    stream.update(0,0,[rim],image=image)
    stream.update(1,1/30,[rim],image=image)
    assert stream.frames[-1]['rim_refinement']==[]
    assert stream.engine.rim.fresh(1/30,1.5)


def test_opt_in_refinement_requires_temporal_confirmation():
    image=np.zeros((180,260,3),np.uint8)
    cv2.ellipse(image,(130,65),(20,5),0,0,360,(0,140,255),2)
    coarse=Det('hoop',.9,(108,60,152,110))
    stream=LegacyShotStream(30,260,height=180)
    stream.update(0,0,[coarse],image=image)
    assert not stream.engine.rim.initialized
    stream.update(1,1/30,[coarse],image=image)
    assert stream.engine.rim.initialized
    assert abs(stream.engine.rim.cy-65)<=2
    assert stream.events==[]


def test_decoded_duration_does_not_trust_incorrect_frame_count(tmp_path, monkeypatch):
    import aihoop.sources as sources
    from aihoop.court import Calibration
    path=tmp_path/'short.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),30,(64,48))
    for _ in range(8):writer.write(np.zeros((48,64,3),np.uint8))
    writer.release()
    real_capture=cv2.VideoCapture
    class WrongCount:
        def __init__(self,*args,**kwargs):self.cap=real_capture(*args,**kwargs)
        def get(self,key):
            value=self.cap.get(key)
            return value+10 if key==cv2.CAP_PROP_FRAME_COUNT else value
        def __getattr__(self,key):return getattr(self.cap,key)
    monkeypatch.setattr(cv2,'VideoCapture',WrongCount)
    src=sources.VideoSource(str(path),Calibration(method='unavailable'),
        detect_players=False,scoreboard=False,auto_sliding=False,device='cpu')
    raw=src.run()
    assert abs(raw.duration-8/30)<1e-6
    assert raw.detections_meta['video_decode']['reported_frames']==18
    assert raw.detections_meta['video_decode']['decoded_frames']==8
    assert raw.detections_meta['video_decode']['frame_count_mismatch']
    assert not raw.detections_meta['video_decode']['vfr_pts_verified']
