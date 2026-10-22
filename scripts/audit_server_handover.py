"""Read-only Git, asset and running-source inventory. Writes only --out files.

Does not import the API, mutate Git, load weights, download, or restart services.
Sensitive environment values and database payloads are never included.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def command(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tracked = set(command('git', 'ls-files', '-z')['stdout'].rstrip('\0').split('\0'))
    status = command('git', 'status', '--short')
    (args.out/'git_status.txt').write_text(status['stdout'])
    (args.out/'diff_summary.txt').write_text(command('git','diff','--stat','HEAD')['stdout'])
    git = {name:command('git', *argv) for name,argv in {
        'head':['rev-parse','HEAD'], 'branch':['branch','-vv'],
        'remotes':['remote','-v'], 'upstream':['rev-parse','origin/main'],
        'divergence':['rev-list','--left-right','--count','HEAD...origin/main'],
        'contains_upstream':['merge-base','--is-ancestor','origin/main','HEAD'],
        'log':['log','-6','--format=%H %ci %s'], 'graph':['log','--graph','--oneline','-12','--all'],
        'head_show':['show','--stat','--oneline','HEAD'],
        'cached':['diff','--cached','--stat'], 'conflicts':['ls-files','-u'],
        'submodules':['submodule','status'], 'lfs':['lfs','version'],
        'reflog':['reflog','-8','--date=iso'],
        'untracked':['ls-files','--others','--exclude-standard'],
    }.items()}
    git['root'] = str(ROOT)
    git['lfs_attribute_files']=[str(p.relative_to(ROOT)) for p in ROOT.rglob('.gitattributes')
        if '.git' not in p.parts and 'filter=lfs' in p.read_text(errors='replace')]
    write(args.out/'git_identity.json', git)
    cache = {}

    def resource(path, role, required, source='server-local; external provenance not inferred'):
        path = Path(path).absolute()
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            rel = None
        exists = path.is_file()
        if exists:
            resolved = str(path.resolve())
            cache.setdefault(resolved, None)
            if cache[resolved] is None:
                cache[resolved] = sha(path)
        return dict(path=str(path), exists=exists, sha256=cache.get(str(path.resolve())) if exists else None,
            bytes=path.stat().st_size if exists else None, role=role, required_for=required,
            git_tracked=rel in tracked if rel else False,
            ignore_rule=command('git','check-ignore','-v','--no-index',rel)['stdout'].strip() if rel else 'outside repository',
            lfs_managed=False, source=source)

    resources=[]
    for rel in ['models/yolov8n.pt','models/BODD_yolov8n_0001.pt',
                'models/shottracker_best.pt','models/shottracker_before_best.pt',
                'runs/detect/ball/weights/best.pt','runs/detect/rim/weights/best.pt',
                'models/rim_ball_v6.pt','models/rim_ball.pt']:
        resources.append(resource(ROOT/rel,'model','role-specific inference / exact historical reproduction'))
    for name in ['craft_mlt_25k.pth','english_g2.pth','source.json']:
        resources.append(resource(ROOT.parent/'aihoop_assets/models/easyocr'/name,'OCR','offline EasyOCR'))
    videos=[]
    for base in [ROOT/'data/uploads', ROOT/'data/samples', ROOT.parent/'aihoop_assets/samples']:
        if base.exists():
            videos += [p for p in base.rglob('*') if p.is_file() and p.suffix.lower() in {'.mp4','.mov','.mkv','.avi'}]
    for p in sorted(set(videos)):
        resources.append(resource(p,'video','matching evaluation or analysis'))
    by_sha={}
    for r in resources:
        if r['role']=='video' and r['exists']:
            by_sha.setdefault(r['sha256'],[]).append(r['path'])
    annotations=[]
    for rel in ['eval/ground_truth/shots_split2_20261011.json',
                'eval/ground_truth/match_testset_20261011.json',
                'eval/annotation_imports/three_bili_20261020/annotations.normalized.json']:
        path=ROOT/rel
        resources.append(resource(path,'human annotations','evaluation',source='Git file; see annotator and review metadata'))
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        for sample in data['samples']:
            expected=sample.get('source_sha256')
            annotations.append(dict(manifest=rel,id=sample['id'],declared_video=sample['video'],
                declared_path_exists=Path(sample['video']).is_file(),expected_sha256=expected,
                hash_verified_local_paths=by_sha.get(expected,[]),shots=len(sample.get('shots',[])),
                unique_plays=len({s.get('play_id',i) for i,s in enumerate(sample.get('shots',[]))}),
                reviewed_range=sample.get('reviewed_range_declared',[sample.get('start_s'),sample.get('end_s')]),
                time_basis=sample.get('time_basis',data.get('time_basis')),
                shots_complete=sample.get('shots_complete'),dataset_split=sample.get('dataset_split'),
                full_game_offset_s=sample.get('original_full_game_offset_s'),
                pending=[dict(id=s.get('id'),reasons=s.get('pending_reasons')) for s in sample.get('shots',[]) if s.get('pending_reasons')]))
    for rel in ['三个视频出手记录.txt','eval/annotation_imports/three_bili_20261020/三个视频出手记录.txt',
                'eval/annotation_imports/three_bili_20261020/human_confirmation.json',
                'eval/baselines/events_players_off_split2_20261011.json',
                'out/crossing_evidence_20261020/review/tasks.json',
                'out/crossing_evidence_20261020/baseline/results.json',
                'out/crossing_evidence_20261020/event_errors.json',
                'out/stage2_audit_20261020/current_baseline/results.json',
                'out/crossing_window_20261020/predeclared_plan.json',
                'out/stage2_review_20261018_194735/review/manifest.json']:
        resources.append(resource(ROOT/rel,'annotations or evidence','historical audit / review recovery'))
    source_manifest={}
    for folder in ['src','scripts','tests','web','eval','docs/audits']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix in {'.py','.js','.html','.json','.md','.yaml','.yml','.csv'} and '__pycache__' not in p.parts:
                source_manifest[str(p.relative_to(ROOT))]=sha(p)
    write(args.out/'source_manifest.before.json',source_manifest)
    write(args.out/'resources.json',resources)
    write(args.out/'annotation_identity.json',annotations)
    # Store only approved path/flag settings. Never copy .env or the entire process environment.
    names={'AIHOOP_MODELS','AIHOOP_PLAYER_WEIGHTS','AIHOOP_JERSEY_MODEL',
           'AIHOOP_SCOREBOARD_OCR_MODELS','AIHOOP_DISABLE_SCOREBOARD_FUSION'}
    settings={}
    if (ROOT/'.env').exists():
        for line in (ROOT/'.env').read_text().splitlines():
            key,sep,val=line.partition('=')
            if sep and key.strip() in names:
                settings[key.strip()]=val.strip().strip('\"\'')
    write(args.out/'safe_path_settings.json',settings)
    pid=int(command('systemctl','--user','show','ai-basketball-analyst.service','-p','MainPID','--value')['stdout'])
    env=dict(part.split(b'=',1) for part in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0') if b'=' in part)
    whitelist=names|{'PYTHONPATH','AIHOOP_RUNTIME_ID','AIHOOP_DATA_DIR','AIHOOP_OUT_DIR'}
    runtime=dict(pid=pid,cmdline=(Path('/proc')/str(pid)/'cmdline').read_bytes().replace(b'\0',b' ').decode(),
        cwd=str((Path('/proc')/str(pid)/'cwd').resolve()),
        environment={k.decode():v.decode() for k,v in env.items() if k.decode() in whitelist},
        systemd=command('systemctl','--user','show','ai-basketball-analyst.service','-p','ActiveState','-p','ActiveEnterTimestamp'),
        health=None)
    import urllib.request
    request=urllib.request.Request('http://127.0.0.1:8018/api/health',headers={
        'X-Internal-Token':env.get(b'AIHOOP_INTERNAL_TOKEN',b'').decode()})
    try:
        with urllib.request.urlopen(request,timeout=10) as response:
            payload=json.load(response)
            runtime['health']=dict(http_status=response.status,ok=payload.get('ok'))
    except Exception as exc:
        runtime['health']=dict(error=type(exc).__name__)
    snapshot=Path(env[b'PYTHONPATH'].decode()).parent
    manifest=json.loads((snapshot/'manifest.json').read_text())
    runtime['snapshot_path']=str(snapshot)
    runtime['snapshot_manifest_sha256']=sha(snapshot/'manifest.json')
    runtime['snapshot_mismatches']=[name for name,digest in manifest.items() if not (snapshot/name).is_file() or sha(snapshot/name)!=digest]
    runtime['snapshot_src_vs_worktree']=[name for name,digest in manifest.items() if name.startswith('src/') and (not (ROOT/name).exists() or sha(ROOT/name)!=digest)]
    write(args.out/'runtime_identity.json',runtime)
    # DB content changes during ordinary user activity; inventory schema/counts only.
    db=ROOT/'data/jobs.sqlite'
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as connection:
        database=dict(path=str(db),read_only=True,
            columns=[r[1] for r in connection.execute('pragma table_info(jobs)')],
            counts=[list(r) for r in connection.execute('select status,count(*) from jobs group by status')],
            busy=[list(r) for r in connection.execute("select job_id,status from jobs where status in ('queued','running')")])
    database['historical_version_limit']='HEAD is not per-job provenance; use each raw_track/run manifest. Older jobs may not store a reconstructible code identity.'
    write(args.out/'database_inventory.json',database)
    report_paths=['LOCAL_HANDOVER_REPORT.md','DATASET_IDENTITY_AUDIT.md','EVENT_ERROR_ANALYSIS.md',
        'REPORT.md','docs/CROSSING_EVIDENCE_DESIGN_20261020.md',
        'out/crossing_evidence_20261020/REPORT.md','out/crossing_window_20261020/REPORT.md']
    write(args.out/'report_inventory.json',[resource(ROOT/p,'report','handover') for p in report_paths])
    write(args.out/'collection.json',dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        root=str(ROOT),resources=len(resources),annotations=len(annotations),
        no_git_mutation=True,no_service_mutation=True))
    print(json.dumps(dict(out=str(args.out),head=git['head']['stdout'].strip(),
        divergence=git['divergence']['stdout'].strip(),resources=len(resources),
        manifest_verified_video_samples=sum(bool(r['hash_verified_local_paths']) for r in annotations),
        runtime_pid=pid,snapshot=str(snapshot)),ensure_ascii=False))


if __name__=='__main__':
    main()
