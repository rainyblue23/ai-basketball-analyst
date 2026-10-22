import json
from pathlib import Path
import sqlite3

from aihoop.model import OutcomeSource, Shot
from aihoop.rules import build_shots, fuse_outcome
from aihoop.sources import synthetic_game
from audit_history_integrity import audit


def test_no_outcome_evidence_is_not_synthetic():
    assert fuse_outcome([]) == (None, 0.0, OutcomeSource.UNKNOWN.value)
    candidate = dict(t=1, team='unknown', player_id='UNASSIGNED', x=0, y=0,
                     made=None, source='legacy_ball_rim')
    shot, = build_shots([candidate])
    assert shot.result == 'unknown'
    assert shot.outcome_source == 'unknown'
    assert shot.score_points == 0
    assert Shot(t=1, team='unknown', player_id='UNASSIGNED').outcome_source == 'unknown'


def test_synthetic_requires_explicit_provenance():
    raw = synthetic_game(seed=7, duration=180)
    assert raw.attempts
    assert all(a.source == 'synthetic' for a in raw.attempts)
    shots = build_shots([a.to_dict() for a in raw.attempts])
    assert all(s.outcome_source == 'synthetic' for s in shots)
    prior = dict(t=1, team='home', player_id='T1', x=0, y=0, made=True, conf=.8)
    assert build_shots([prior])[0].outcome_source == 'unknown'
    prior['source'] = 'legacy_ball_rim'
    assert build_shots([prior])[0].outcome_source == 'ball_through_rim'


def test_api_test_storage_is_detached_from_project_storage():
    from aihoop import api
    assert api.DB_PATH.parent != api.ROOT / 'data'
    assert api.OUT_ROOT != api.ROOT / 'out'
    assert api.DB_PATH.parent == api.DATA
    assert api.UPLOAD_DIR.parent == api.DATA


def test_history_filters_demo_and_exposes_video_name_without_full_path(tmp_path, monkeypatch):
    import asyncio
    from aihoop import api
    monkeypatch.setattr(api, 'DB_PATH', tmp_path / 'jobs.sqlite')
    api.init_db()
    api._persist(api.JobState(job_id='real-history', source='video',
                             video_path='/private/uploads/game.mp4'))
    api._persist(api.JobState(job_id='demo-history', source='synthetic'))
    rows = asyncio.run(api.list_jobs())
    assert len(rows) == 1
    assert rows[0]['source'] == 'video'
    assert rows[0]['video_name'] == 'game.mp4'
    assert 'video_path' not in rows[0]
    assert len(asyncio.run(api.list_jobs(include_synthetic=True))) == 2


def test_readonly_inventory_distinguishes_job_source_from_outcome_source(tmp_path):
    database = tmp_path / 'jobs.sqlite'
    output = tmp_path / 'real-job'
    output.mkdir()
    (output / 'raw_track.json').write_text(json.dumps(dict(
        detections_meta=dict(source='video', legacy_shots=dict(frames=[{'frame': 0}])),
        attempts=[dict(t=1, player_id='T1', source='legacy_ball_rim', made=None)])))
    (output / 'game.json').write_text(json.dumps(dict(meta=dict(source='video'),
        timeline=[dict(t=1, player_id='T1', result='unknown', made=None, source='synthetic')])))
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE jobs(job_id,source,status,out_dir,video_path,created,payload)')
        connection.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', [
            ('real', 'video', 'done', str(output), 'missing.mp4', 2, '{}'),
            ('fake', 'synthetic', 'done', None, None, 1, '{}')])
    before = database.read_bytes()
    report = audit(database)
    assert database.read_bytes() == before
    assert report['default_history_ids'] == ['real']
    assert report['ownership_column_present'] is False
    assert report['accuracy_verified'] is False
    label, = report['jobs'][0]['synthetic_outcome_labels_in_video']
    assert label['classification'] == 'missing_outcome_evidence_mislabeled_synthetic'
    assert report['jobs'][0]['original_video_exists'] is False
