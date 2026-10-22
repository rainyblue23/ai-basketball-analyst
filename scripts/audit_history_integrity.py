"""Read-only provenance inventory; source evidence is not accuracy validation."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit(database):
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = [r['name'] for r in connection.execute('PRAGMA table_info(jobs)')]
        rows = connection.execute(
            'SELECT job_id,source,status,out_dir,video_path,created,payload '
            'FROM jobs ORDER BY created DESC').fetchall()
    finally:
        connection.close()
    groups = Counter((r['source'], r['status']) for r in rows)
    result = {
        'database': str(database.resolve()), 'read_only': True,
        'source_counts': [dict(source=k[0], status=k[1], count=n) for k, n in sorted(groups.items())],
        'ownership_column_present': any(k in columns for k in ('username', 'owner', 'owner_id', 'user_id')),
        'account_attribution_verified': False, 'accuracy_verified': False,
        'default_history_ids': [r['job_id'] for r in rows if r['source'] != 'synthetic'][:20],
        'jobs': [],
    }
    for row in rows:
        if row['source'] == 'synthetic':
            continue
        root = Path(row['out_dir']) if row['out_dir'] else None
        entry = {k: row[k] for k in ('job_id', 'source', 'status', 'created', 'video_path')}
        entry['original_video_exists'] = bool(row['video_path'] and Path(row['video_path']).is_file())
        payload = json.loads(row['payload'] or '{}')
        # _worker_owner describes a process, never an account.
        entry['account_attribution_recorded'] = any(k in payload for k in ('username', 'user_id', 'owner_id'))
        entry['files'] = {}
        loaded = {}
        if root is not None:
            for name in ('raw_track.json', 'game.json', 'players.json', 'tactics.json',
                         'corrections.json', 'manual_attempts.json'):
                path = root / name
                if path.is_file():
                    entry['files'][name] = {'path': str(path.resolve()), 'sha256': digest(path)}
                    if name in ('raw_track.json', 'game.json'):
                        loaded[name] = json.loads(path.read_text())
        raw = loaded.get('raw_track.json', {})
        game = loaded.get('game.json', {})
        metadata = raw.get('detections_meta') or {}
        timeline = game.get('timeline') or []
        attempts = raw.get('attempts') or []
        entry.update(raw_source=metadata.get('source'), game_source=(game.get('meta') or {}).get('source'),
                     measured_trace_frames=len((metadata.get('legacy_shots') or {}).get('frames', [])),
                     raw_attempts=len(attempts), timeline_events=len(timeline),
                     timeline_sources=dict(Counter(e.get('source') for e in timeline)), score=game.get('score'))
        suspicious = []
        for event in timeline:
            if event.get('source') != 'synthetic':
                continue
            matching = [a for a in attempts if abs(float(a['t']) - float(event['t'])) < 1e-6
                        and a.get('player_id') == event.get('player_id')]
            suspicious.append(dict(t=event['t'], result=event.get('result'), made=event.get('made'),
                raw_sources=[a.get('source') for a in matching],
                raw_made=[a.get('made') for a in matching],
                classification=('missing_outcome_evidence_mislabeled_synthetic'
                    if metadata.get('source') == 'video' and matching
                    and all(a.get('made') is None for a in matching)
                    and event.get('result') == 'unknown'
                    else 'needs_provenance_review')))
        entry['synthetic_outcome_labels_in_video'] = suspicious
        result['jobs'].append(entry)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/jobs.sqlite')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.database)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ('jobs', 'default_history_ids')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
