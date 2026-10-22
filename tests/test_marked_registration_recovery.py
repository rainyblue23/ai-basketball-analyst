from collections import OrderedDict
from unittest.mock import Mock, patch

import cv2
import numpy as np
import pytest

from aihoop.court import Calibration
from aihoop.marked_projection import (MarkedProjector, RegistrationOptions, registration_consistent,
                                      floor_photometric_support)


def calibration(dx=0):
    return Calibration(H=[[.03, 0, -14.4+dx], [0, .06, -16.2], [0, 0, 1]],
                       dst_m=[[-5, -12], [5, -12], [-5, -3], [5, -3]], frame='full')


def projector(options, valid_anchors):
    p = MarkedProjector.__new__(MarkedProjector)
    p.options = options
    p.width, p.height = 960, 540
    p.cache, p.audit, p.camera_cuts = {}, [], ()
    p._local_features = OrderedDict()
    image = np.random.default_rng(21).integers(0, 256, (540, 960, 3), dtype=np.uint8)
    orb = cv2.ORB_create(nfeatures=1000)
    p.features = lambda frame: orb.detectAndCompute(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), None)
    p.frame = Mock(return_value=image)
    p.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    p._direct_at = Mock(side_effect=lambda t: (calibration() if t in valid_anchors else None,
                                               dict(t=t, matched=t in valid_anchors, reference_t=0)))
    return p


def test_default_off_and_invalid_bounds():
    assert not RegistrationOptions().local_recovery
    with pytest.raises(ValueError):
        RegistrationOptions(max_anchor_gap_s=3)
    p = projector(RegistrationOptions(), {9.75, 9.5, 9.25})
    assert p.at(10) is None
    assert p._direct_at.call_count == 1


@patch('aihoop.calibcheck.frame_fit_detail', return_value={'ratio': 2., 'n_on_line': 60})
def test_three_real_anchors_recover_but_one_does_not_and_cache_is_stable(_):
    p = projector(RegistrationOptions(local_recovery=True), {9.75, 9.5, 9.25})
    cal = p.at(10)
    assert cal is not None
    assert p.audit[-1]['source'] == 'local_registered'
    assert p.audit[-1]['local_recovery']['prediction'] is False
    assert len(p.audit[-1]['local_recovery']['anchor_times']) == 3
    calls = p._direct_at.call_count
    assert p.at(10) is cal and p._direct_at.call_count == calls
    p = projector(RegistrationOptions(local_recovery=True), {9.75})
    assert p.at(10) is None


def test_geometry_disagreement_and_offscreen_support_rejected():
    opts = RegistrationOptions()
    assert registration_consistent(calibration(), calibration(), (960, 540), opts)
    assert not registration_consistent(calibration(), calibration(7), (960, 540), opts)
    assert not registration_consistent(calibration(500), calibration(500), (960, 540), opts)


@patch('aihoop.calibcheck.frame_fit_detail', return_value={'ratio': 2., 'n_on_line': 60})
def test_cut_blocked_and_recovered_cache_cannot_seed_new_anchors(_):
    p = projector(RegistrationOptions(local_recovery=True), {9.75, 9.5, 9.25, 10.25, 10.5, 10.75})
    p.camera_cuts = (9.9, 10.1)
    assert p.at(10) is None
    assert p._direct_at.call_count == 1  # only current frame; no cut crossing
    p = projector(RegistrationOptions(local_recovery=True), set())
    p.cache.update({9.75: calibration(), 9.5: calibration(), 9.25: calibration()})
    assert p.at(10) is None


@patch('aihoop.calibcheck.frame_fit_detail', return_value={'ratio': 1.1})
def test_floor_fit_failure_cannot_be_rescued_by_many_anchors(_):
    p = projector(RegistrationOptions(local_recovery=True), {9.75, 9.5, 9.25})
    assert p.at(10) is None


def test_direct_cache_metadata_not_polluted_by_recovery():
    p = MarkedProjector.__new__(MarkedProjector)
    p._direct_cache = {10: (None, {'t': 10, 'matched': False})}
    _, detail = p._direct_at(10)
    detail['matched'] = True
    assert not p._direct_cache[10][1]['matched']


def test_floor_photometric_gate_allows_exposure_offset_but_rejects_superposition():
    rng=np.random.default_rng(11)
    floor=rng.integers(140,170,(540,960,1),dtype=np.uint8)
    reference=np.repeat(floor,3,axis=2)
    shifted=(reference.astype(int)+20).astype(np.uint8)
    options=RegistrationOptions()
    assert floor_photometric_support(shifted,reference,np.eye(3),calibration(),options)['ok']
    # Broad double exposure cannot be established by a few matching patches.
    superposition=rng.integers(0,256,reference.shape,dtype=np.uint8)
    assert not floor_photometric_support(superposition,reference,np.eye(3),calibration(),options)['ok']


def test_cached_context_parser_excludes_prediction_and_held_stride_frames():
    from recover_marked_calibration import cached_person_observations
    from aihoop.sources import RawTrack
    import copy
    person=dict(cls='person',conf=.8,xyxy=[10,20,30,60],track_id='T1',measurement=True,predicted=False)
    raw=RawTrack(fps=30)
    predicted=dict(person,track_id='T2',predicted=True)
    raw.detections_meta['legacy_shots']={'frames':[
        dict(frame=0,t=0,head_context=[person,predicted]),
        dict(frame=1,t=1/30,head_context=[person]),
        dict(frame=2,t=2/30,head_context=[dict(person,measurement=False)])]}
    old=copy.deepcopy(raw)
    rows=list(cached_person_observations(raw,2))
    assert len(rows)==1 and rows[0]['source_frame']==0 and rows[0]['foot_y']==60
    assert raw==old
    raw.detections_meta['legacy_shots']['frames'][0]['t']=1
    with pytest.raises(ValueError):list(cached_person_observations(raw,2))
