import asyncio
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from aihoop import api
from aihoop.calibcheck import frame_fit_detail
from aihoop.court import Calibration, fold_to_analysis, unfold_from_analysis


def test_b_baseline_roundtrip_preserves_its_end():
    x, y = fold_to_analysis(3.0, -14.0, 'full')
    assert y == 0.0 and math.copysign(1.0, y) == -1.0
    assert unfold_from_analysis(x, y, 'full') == (3.0, -14.0)
    assert unfold_from_analysis(3.0, 0.0, 'full') == (3.0, 14.0)


@pytest.mark.parametrize('sign', [-1, 1])
def test_line_check_uses_the_marked_half_and_baseline(sign):
    # Same visible floor for A and B, with independent full-court coordinates.
    src = [[50,20], [350,20], [350,300], [50,300]]
    dst = [[-7.5,sign*14], [7.5,sign*14], [7.5,0], [-7.5,0]]
    cal = Calibration(src_px=src, dst_m=dst, frame='full', frame_size=[400,330]).fit()
    image = np.full((330,400,3), 80, dtype=np.uint8)
    cv2.rectangle(image, (50,20), (350,300), (230,230,230), 2)
    lane = np.array([[151,20],[151,136],[249,136],[249,20]], dtype=np.int32)
    cv2.polylines(image, [lane], False, (230,230,230), 2)
    score = frame_fit_detail(image, cal)
    assert score['n_on_line'] > 100
    assert score['ratio'] > 10, score


def test_preview_returns_a_h_and_explains_b_collinear_points(monkeypatch):
    a_names = ['corner_far_right','lane_far_right','lane_far_left','ft_far','arc_far']
    b_names = ['lane_near_left','lane_near_right','ft_near','arc_near']
    frames = {
        55.5: {'t':55.5, 'px':[[1093.42,582.54],[635.31,781.73],[826.52,976.92],
                             [714.98,865.38],[284.76,909.20]],
               'dst':[api.COURT_LANDMARKS[n] for n in a_names], 'names':a_names},
        0.5: {'t':0.5, 'px':[[1236.44,701.62],[1057.59,870.15],[1147.01,784.16],
                            [1583.81,763.53]],
              'dst':[api.COURT_LANDMARKS[n] for n in b_names], 'names':b_names},
    }
    monkeypatch.setattr(api, '_frame_bgr', lambda *args: np.zeros((10,10,3),dtype=np.uint8))
    import aihoop.calibcheck as checker
    monkeypatch.setattr(checker, 'frame_fit_detail', lambda *args: {'ratio':2.0})
    result = api._preview_marked_frames(Path('sample.mp4'), frames, 1920,1080)
    a, b = result['per_frame_fit']
    assert a['H'] and a['ok']
    assert b['H'] is None and not b['ok']
    assert '同一条线' in b['note'] and '再标' in b['note']
    assert result['preview_only'] and not result['saved']
    assert not result['ok']


def test_quick_preview_never_scans_shot_boundaries(tmp_path, monkeypatch):
    video = tmp_path / 'sample.mp4'
    video.write_bytes(b'')
    class Capture:
        def __init__(self, *args): pass
        def get(self, prop):
            return 1920 if prop == cv2.CAP_PROP_FRAME_WIDTH else 1080
        def release(self): pass
    monkeypatch.setattr(cv2, 'VideoCapture', Capture)
    def scan(*args):
        raise AssertionError('A preview must not scan the whole video')
    monkeypatch.setattr(api, '_split_marks_by_shot', scan)
    captured = []
    def preview(vp, frames, w, h):
        captured.append((frames,w,h))
        return {'ok':False, 'preview_only':True, 'saved':False}
    monkeypatch.setattr(api, '_preview_marked_frames', preview)
    frames = [{'t':55.5,'landmarks':{'lane_far_right':[0.3,0.7]}},
              {'t':0.5,'landmarks':{'lane_near_left':[0.6,0.7]}}]
    result = asyncio.run(api.post_calibrate_multi(api.MultiCalibRequest(
        video_path=str(video),frames=frames,compensate=False,confirm=False)))
    assert result['preview_only']
    assert set(captured[0][0]) == {55.5,0.5}


def test_quality_scope_uses_exact_selected_frame_even_with_no_saved_segments(tmp_path):
    assert api._applies_to_times(tmp_path / 'new.mp4', 37.25) == [37.25]
    assert api._applies_to_times(tmp_path / 'new.mp4', None) is None


def test_line_quality_decodes_only_requested_frames_without_whole_video_conversion(monkeypatch):
    from aihoop import calibcheck, video_compat
    def forbidden(*_a, **_k):
        raise AssertionError('Do not convert an entire video to check one screenshot')
    monkeypatch.setattr(video_compat, 'ensure_cv2_decodable', forbidden)
    observed=[]
    def frame(vp,t):
        observed.append(t)
        return np.zeros((10,10,3),dtype=np.uint8)
    monkeypatch.setattr(api, '_frame_bgr', frame)
    monkeypatch.setattr(calibcheck, 'frame_fit_detail',lambda *_a: {'ratio':2.0})
    score=calibcheck.court_fit_score('av1.mp4',Calibration(),times=[37.25])
    assert observed==[37.25]
    assert score['ok'] and score['frames'][0]['t']==37.25


def test_manual_save_preserves_passing_preview_matrices_and_scores(tmp_path, monkeypatch):
    import json
    video=tmp_path/'video.mp4';video.write_bytes(b'placeholder')
    output=tmp_path/'calibration.json'
    class Capture:
        def __init__(self,*_a): pass
        def get(self,prop): return 1920 if prop==cv2.CAP_PROP_FRAME_WIDTH else 1080
        def release(self): pass
    monkeypatch.setattr(cv2,'VideoCapture',Capture)
    monkeypatch.setattr(api,'_calibration_path_for',lambda _v: output)
    monkeypatch.setattr(api,'_video_duration',lambda _v: 90)
    monkeypatch.setattr(api,'_split_marks_by_shot',lambda *_a: ([[1],[11.25]],[5]))
    h_a=[[.01,0,-5],[0,.01,2],[0,0,1]]
    h_b=[[.02,0,-6],[0,-.02,-1],[0,0,1]]
    def preview(*_a):
        return {'ok':True,'per_frame_fit':[
            {'t':1.,'n':4,'ok':True,'H':h_a,'rmse_m':.1176,'ratio':1.6},
            {'t':11.25,'n':4,'ok':True,'H':h_b,'rmse_m':.1629,'ratio':2.2}],
            'calibration_fit':{'ratio':1.6,'weak_segments':[]}}
    monkeypatch.setattr(api,'_preview_marked_frames',preview)
    a=['paint_base_far_left','paint_base_far_right','lane_far_left','lane_far_right']
    b=['paint_base_near_left','paint_base_near_right','lane_near_left','lane_near_right']
    req=api.MultiCalibRequest(video_path=str(video),confirm=True,compensate=False,
        frames=[{'t':1.,'landmarks':{n:[.2,.3] for n in a}},
                {'t':11.25,'landmarks':{n:[.5,.6] for n in b}}])
    result=asyncio.run(api.post_calibrate_multi(req))
    saved=json.loads(output.read_text())
    assert result['saved'] and saved['revision']==1
    assert [s['H'] for s in saved['segments']]==[h_a,h_b]
    assert [s['ratio'] for s in saved['segments']]==[1.6,2.2]


def test_saved_ground_calibration_does_not_require_airborne_hoop(tmp_path, monkeypatch):
    import json
    from aihoop.multical import MultiCal, Segment
    segments=[]
    for sign in [1,-1]:
        src=[[100,50],[500,50],[500,400],[100,400]]
        dst=[[-7.5,sign*14],[7.5,sign*14],[7.5,0],[-7.5,0]]
        cal=Calibration(src_px=src,dst_m=dst,frame='full',frame_size=[640,480]).fit()
        segments.append(Segment(t_start=0 if sign==1 else 5,t_end=5 if sign==1 else 10,
            src_px=src,dst_m=dst,H=cal.H,ratio=2.0,rmse_m=0.,n_points=4))
    output=tmp_path/'verified.json'
    output.write_text(json.dumps(MultiCal(segments,for_video='sample.mp4',frame_size=[640,480]).to_dict()))
    monkeypatch.setattr(api,'_calibration_path_for',lambda _v: output)
    result=asyncio.run(api.get_calibration('sample.mp4'))
    assert result['calibration_ok'] and not result['position_unverified']
    assert not result['hoop_checked']
