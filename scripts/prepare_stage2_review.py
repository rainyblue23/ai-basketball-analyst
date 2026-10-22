"""Build pending human review tasks and source-level dataset inventory, offline.

Reuses match-labeling and its normalized frame schema. Algorithm evidence is
stored separately; no inference reads these task definitions or human labels.
"""
import argparse
from pathlib import Path
import json, math, os, subprocess
import cv2
try:
    from .collect_cv_baseline import ROOT, sha256, write_json
except ImportError:
    from collect_cv_baseline import ROOT, sha256, write_json

STAGE1=ROOT/'out/general_stage1_20261016_213026'
CURRENT=ROOT/'out/current_job_a099_20261017_161414'
WINDOWS=[('lillard_first','利拉德：首次投篮',0.,4.),
         ('lillard_block','利拉德：上篮、盖帽与回抛',19.5,23.5),
         ('yang_rim','杨瀚森：穿筐与真实球队',5.6,7.),
         ('lillard_dribble','负例待核对：运球',12.,15.),
         ('lillard_scramble','负例待核对：争球',24.,27.),
         ('lillard_pass','负例待核对：传球',27.,30.)]

def audit_source_splits(sources):
    """Known same-match clips or identical bytes must never cross partitions."""
    groups={};hashes={};errors=[]
    for row in sources:
        match=row.get('source_match_id');split=row['split']
        if match:
            if match in groups and groups[match]!=split:errors.append('match_cross_split:'+match)
            groups[match]=split
        for asset in row.get('assets',[]):
            digest=asset.get('sha256')
            if digest and digest in hashes and hashes[digest]!=split:errors.append('sha_cross_split:'+digest)
            if digest:hashes[digest]=split
        if split!='Development' and (not match or row.get('leakage_review_status')!='approved'):
            errors.append('unapproved_source:'+str(match))
    return errors

def video_info(path):
    # ffprobe can read AV1 metadata even if this OpenCV build cannot decode it.
    cmd=['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_frames,duration:format=duration','-of','json',str(path)]
    d=json.loads(subprocess.check_output(cmd));s=d['streams'][0];n,den=s['avg_frame_rate'].split('/')
    return dict(width=s['width'],height=s['height'],fps=float(n)/float(den),duration_s=float(s.get('duration') or d['format']['duration']),frames=s.get('nb_frames'))


def legacy_annotation_inventory():
    rows=[]
    for path in sorted((ROOT/'eval/ground_truth').glob('*.json')):
        data=json.loads(path.read_text())
        rows.append(dict(path=str(path),sha256=sha256(path),split='Development',
            status='previously_used_not_independent',schema_keys=list(data) if isinstance(data,dict) else None))
    old=json.loads((ROOT/'eval/ground_truth/match_testset_20261011.json').read_text())
    missing=[dict(id=s['id'],legacy_video_path=s['video'],expected_original_video_sha256=s.get('source_sha256'),verified_original_video_sha256=None,
        legacy_source_sha256=s.get('source_sha256'),legacy_source_file=s.get('source_file'),
        note='Imported expected video SHA; original file unavailable here, so byte identity remains unverified',
        frames=len(s['frames']),shots=len(s['shots']),status='original_video_and_images_need_hash_verified_migration',
        split='Development',source_match_id=None) for s in old['samples']]
    return dict(files=rows,missing_originals=missing,
        reuse_requires='Restore exact video/images and verify hashes/time mapping; never substitute a similarly named match')

def prepare(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    assets=json.loads((STAGE1/'assets.json').read_text())['assets'];identity=json.loads((CURRENT/'input_identity.json').read_text())
    original_yang=ROOT/'data/uploads/yang-retry2_8828aea2e1.mp4'
    sources={
      'lillard':dict(video=assets['compatible_full']['path'],original_video=assets['original_full']['path'],raw=STAGE1/'ablation/00_lillard_first30_lossless_F/raw_track.json',source_match_id='lillard-buzzer-beater',mapping_note='原片00:00起；已有H264转码，PTS最大误差0.000058秒；不是原AV1像素无损'),
      'yang':dict(video=identity['video_path'],original_video=str(original_yang),raw=identity['raw_path'],source_match_id='yang-retry2',mapping_note='原片00:00起；已有H264兼容副本，保留原片帧号；精确原片PTS映射需补审核')}
    for r in sources.values():
        r.update(video_info(r['video']));r['video_sha256']=sha256(r['video']);r['original_sha256']=sha256(r['original_video']);r['raw_sha256']=sha256(r['raw'])
        r['trace']=json.loads(Path(r['raw']).read_text())['detections_meta']['legacy_shots']['frames']
    tasks=[]
    for task_id,title,start,end in WINDOWS:
        r=sources['yang' if task_id.startswith('yang') else 'lillard'];folder=out/task_id;folder.mkdir();fps=r['fps']
        first=math.ceil(start*fps);stop=math.ceil(end*fps);frame_times={};frame_hashes={};evidence={}
        cap=cv2.VideoCapture(r['video']);cap.set(cv2.CAP_PROP_POS_FRAMES,first)
        byid={f['frame']:f for f in r['trace']}
        for index in range(first,stop):
            ok,im=cap.read()
            if not ok:raise ValueError('Video truncated before review window')
            name=f'frame_{index:06d}.jpg';cv2.imwrite(str(folder/name),im,[cv2.IMWRITE_JPEG_QUALITY,94]);frame_times[name]=index/fps;frame_hashes[name]=sha256(folder/name)
            f=byid[index];evidence[name]={k:f.get(k) for k in ('frame','t','ball','ball_candidates','rim_candidates','persons','tracked_rim','cut')}
        cap.release()
        task={k:v for k,v in r.items() if k not in ('trace','raw')};task.update(id=task_id,title=title,start_s=start,end_s=end,view_start_s=max(0,start-1),view_end_s=min(r['duration_s'],end+1),frame_times=frame_times,review_status='pending',training_approved=False,split='Development',time_basis='original_video_seconds',frame_time_basis='compatible_decoded_frame/fps',candidate_evidence='algorithm_only_not_truth',raw_path=str(r['raw']),questions=['是否出手/离手区间','命中、未中或未知及分值','原比赛还是回放；同play_id关联','盖帽与随后回抛分开','真实队名/球员/号码；未知留空'])
        task['frame_sha256']=frame_hashes
        task['candidate_stage']='post_YOLO_threshold_and_NMS_not_logits'
        tasks.append(task);write_json(folder/'evidence.json',evidence)
    write_json(out/'manifest.json',tasks)
    registry=json.loads((STAGE1/'stage2_source_registry.json').read_text())
    source_urls={'lillard-buzzer-beater':'https://www.bilibili.com/video/BV165YQ68E3C/','yang-retry2':'https://www.bilibili.com/video/BV1e8HS6HEv4/','harden-58pts':'https://www.bilibili.com/video/BV1sHYN6uEGd/','shottracker-dairycourts':'https://github.com/AggieSportsAnalytics/ShotTracker','shottracker-nathan':'https://github.com/AggieSportsAnalytics/ShotTracker'}
    extras={'harden-58pts':[ROOT/'data/uploads/harden-58pts-BV1sHYN6uEGd_1383973ee3.mp4'], 'yang-retry2':[original_yang,Path(identity['video_path'])], 'shottracker-nathan':[ROOT/'data/samples/shottracker/NathanBBall.mov']}
    for row in registry['sources']:
        sid=row['source_match_id'];row.update(league='NBA' if sid in ('lillard-buzzer-beater','yang-retry2','harden-58pts') else 'UNKNOWN',match_date=None,teams=None,broadcast_style='pending_human_confirmation',source_url=source_urls[sid],leakage_review_status='development_previously_used',annotation_status='coarse_or_ordinal_only; precise_review_pending')
        row.setdefault('assets',[])
        for path in extras.get(sid,[]):
            if path.exists():row['assets'].append(dict(path=str(path.resolve()),sha256=sha256(path)))
        for asset in row['assets']:
            path=Path(asset['path']);asset['exists']=path.exists()
            if path.exists():
                actual=sha256(path)
                if actual!=asset['sha256']:raise ValueError('Source SHA changed:'+str(path))
                asset.update(video_info(path))
    # Inventory aliases that could otherwise masquerade as new matches. Unknown
    # videos are quarantined Development, never invented Validation/Test sources.
    known={a['sha256'] for r in registry['sources'] for a in r.get('assets',[])}
    unassigned=[]
    for folder in [ROOT/'data/uploads',ROOT/'data/samples/bili',ROOT/'data/samples/archive']:
        for path in sorted(folder.glob('*.mp4')):
            h=sha256(path)
            if h not in known:unassigned.append(dict(path=str(path),sha256=h,split='Development',source_match_id=None,status='quarantine_unresolved_match_or_transcode_alias',reason='Historical samples/uploads may share matches with known development sources; no independent eligibility',**video_info(path)))
    registry['unresolved_assets']=unassigned
    registry['split_audit']={'cross_split_errors':audit_source_splits(registry['sources']),'new_validation_count':0,'new_independent_test_count':0,'near_duplicate_and_training_overlap_audit_complete':False,'training_data_provenance_of_models':'not_fully_known','source_grouping_is_conservative':True}
    for row in registry['pending_new_sources']:
        row.update(match_date=None,teams=None,broadcast_style=None,duration_s=None,annotations=None,training_overlap_checked=False)
    write_json(out/'source_registry.json',registry)
    write_json(out/'legacy_annotation_inventory.json',legacy_annotation_inventory())
    write_json(out/'missing_materials.json',{'new_sources':registry['pending_new_sources'],'human_required':['先审核三个关键事件和三段负例；填离手区间/结果/分值/回放play_id/真实球队','每个新比赛提供原视频或本机路径、联赛、比赛日期、对阵双方、来源链接与转播台/样式','说明是否参与过调参/训练/旧样例；同场所有剪辑/回放/转码列出','8个不同新比赛：NBA4+CBA4；各2Validation与2Independent Test','提供连续比赛上下文和负例，避免只给进球集锦；无法识别的字段保留UNKNOWN'],'sha_and_duration_computed_by_tool':True,'can_start_formal_cross_match_evaluation':False})
    return tasks

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();tasks=prepare(a.out);print(json.dumps({'tasks':len(tasks),'frames':sum(len(t['frame_times']) for t in tasks),'out':str(a.out)},ensure_ascii=False))
