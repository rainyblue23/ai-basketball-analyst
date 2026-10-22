from unittest.mock import Mock

from aihoop.marked_projection import MarkedProjector, multical_fit
from aihoop.multical import MultiCal, Segment
from aihoop.pipeline import PipelineConfig, _tactics_population_drop
from aihoop.sources import RawTrack
from aihoop.tactics import PlayerSample, build_tactics_frames


def test_multical_keeps_each_camera_score_and_rejects_bad_side():
    mc = MultiCal(segments=[
        Segment(0, 10, H=[[1,0,0],[0,1,0],[0,0,1]], rmse_m=.15, ratio=3.09, n_points=7),
        Segment(10, 90, H=[[1,0,0],[0,1,0],[0,0,1]], rmse_m=.23, ratio=3.4, n_points=7)])
    assert multical_fit(mc)['ratio'] == 3.09
    assert multical_fit(mc)['ok']
    mc.segments[1].ratio = .5
    assert not multical_fit(mc)['ok']


def test_unmatched_camera_never_reuses_previous_matrix():
    projector = MarkedProjector.__new__(MarkedProjector)
    projector.cache = {}; projector.audit = []
    projector.frame = Mock(return_value=None)
    assert projector.at(42) is None
    assert projector.audit[-1]['matched'] is False
    assert projector.at(42) is None
    projector.frame.assert_called_once()


def test_bad_times_do_not_hide_valid_tactics_and_missing_times_clear_positions():
    rt = RawTrack(duration=10)
    for t in range(8):
        count = 5 if t < 2 else 6
        rt.player_track += [PlayerSample(t, str(i), 'home', -6 + i*2, 3+i)
                            for i in range(count)]
    cfg = PipelineConfig(out_dir='/tmp/unused', make_highlights=False)
    assert _tactics_population_drop(rt, cfg) is None
    frames = build_tactics_frames(rt.player_track, [], duration=10)
    assert any(f['players'] for f in frames)
    assert any(f.get('population_quality', {}).get('valid') is False for f in frames)
    assert frames[-1]['players'] == []
    assert frames[-1]['position_quality']['valid'] is False
