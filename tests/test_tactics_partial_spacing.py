"""Observed subsets must never invent a team, lineup or complete formation."""
import copy
from dataclasses import replace

from aihoop.tactics import PlayerSample, TacticsConfig, build_tactics, build_tactics_frames


def observations():
    return [PlayerSample(t, pid, team, x, y) for t in range(5)
            for pid, team, x, y in [('a', 'team_a', 0, 3), ('b', 'team_a', 3, 3),
                                     ('c', 'team_b', 0, 7), ('d', 'team_b', 4, 7),
                                     ('u', 'unknown', 7, 10)]]


def test_unknown_person_does_not_delete_known_teammate_measurements_when_opted_in():
    samples = observations()
    original = copy.deepcopy(samples)
    cfg = TacticsConfig(roster_evidence_filter=True)
    old = build_tactics(samples, [], duration=4, cfg=cfg)
    assert old['spacing']['timeline'] == []  # default preserves conservative policy
    cfg = replace(cfg, spacing_observed_subset=True)
    new = build_tactics(samples, [], duration=4, cfg=cfg)
    rows = new['spacing']['timeline']
    assert len(rows) == 10
    assert {r['team'] for r in rows} == {'team_a', 'team_b'}
    for row in rows:
        assert row['n'] == 2 and row['scope'] == 'observed_team_subset'
        assert row['unassigned_present'] is True
        assert row['mean_dist'] == (3 if row['team'] == 'team_a' else 4)
    assert new['formation']['summary'] == old['formation']['summary']
    assert new['passes'] == old['passes'] and new['possession'] == old['possession']
    assert new['spacing']['teams']['team_a']['n_min'] == 2
    assert new['spacing']['teams']['team_a']['samples'] == 5
    assert build_tactics_frames(samples, [], 4, cfg) == build_tactics_frames(samples, [], 4, replace(cfg, spacing_observed_subset=False))
    assert samples == original


def test_unknown_only_and_one_known_person_never_make_spacing_or_team_stats():
    samples = observations()
    for subset in ([s for s in samples if s.team == 'unknown'],
                   [s for s in samples if s.player_id in ('a', 'u')]):
        tac = build_tactics(subset * 3, [], duration=4, cfg=TacticsConfig(spacing_observed_subset=True))
        assert tac.get('spacing', {}).get('timeline', []) == []


def test_population_gate_is_not_bypassed_and_cut_segments_are_preserved():
    samples = observations()
    cfg = TacticsConfig(roster_evidence_filter=True, spacing_observed_subset=True, camera_cuts_s=(1.5,))
    tac = build_tactics(samples, [], duration=4, cfg=cfg)
    assert all(r['segment'] == (0 if r['t'] < 1.5 else 1) for r in tac['spacing']['timeline'])
    overcrowded = [PlayerSample(t, f'x{i}', 'team_a', i, 5) for t in range(5) for i in range(6)]
    assert build_tactics(overcrowded, [], duration=4, cfg=cfg)['spacing']['timeline'] == []


def test_formation_segment_cannot_bridge_missing_observations_or_cuts():
    from aihoop.tactics import _segments
    rows = [dict(t=t, shape='双塔', confidence=.8) for t in [0, 1, 2, 40, 41, 42]]
    segments = _segments(rows, 't0', 't1', 'shape', 3, max_gap=1.5)
    assert [(s['t0'], s['t1'], s['n']) for s in segments] == [(0, 2, 3), (40, 42, 3)]
    contiguous = [dict(t=t, shape='双塔') for t in range(6)]
    segments = _segments(contiguous, 't0', 't1', 'shape', 3, max_gap=1.5, cuts=(2.5,))
    assert [(s['t0'], s['t1']) for s in segments] == [(0, 2), (3, 5)]


def test_anonymous_group_insights_never_claim_home_or_away_or_jersey_name():
    from aihoop.tactics import _team_label
    from types import SimpleNamespace
    players = {'x': SimpleNamespace(team='team_a', name='号码待确认')}
    assert _team_label(players, 'team_a') == '分组A（主客未核实）'
    assert _team_label({'x': SimpleNamespace(team='home', name='号码待确认')}, 'home') == '主队'
