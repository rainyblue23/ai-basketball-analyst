"""Offline, additive tactical reprojection from cached measured person boxes.

Original positions, events, team assignments and job files are immutable.
Recovery never reads annotations or assigns a shot/player from ground truth.
"""
import argparse
import copy
import json
import math
import shutil
import time
from dataclasses import asdict
from pathlib import Path

import cv2

from collect_cv_baseline import ROOT, freeze, sha256, write_json
from compare_tactics_population import collect
from aihoop.marked_projection import MarkedProjector, RegistrationOptions
from aihoop.model import Player
from aihoop.sources import RawTrack
from aihoop.tactics import PlayerSample, TacticsConfig, build_tactics, build_tactics_frames
from aihoop.tactics_roster import RosterEvidenceConfig, apply_roster_evidence, roster_signature, validate_roster_evidence


def cached_person_observations(raw, stride):
    """Replay detector measurement frames, never held odd-frame context."""
    if not isinstance(stride, int) or isinstance(stride, bool) or stride < 1:
        raise ValueError('Measured person stride must be explicitly provided')
    seen=set()
    for row in raw.detections_meta.get('legacy_shots',{}).get('frames',[]):
        if row['frame'] % stride:
            continue
        if abs(row['t']-row['frame']/raw.fps) > .002:
            raise ValueError('Cached frame/time identity mismatch')
        for person in row.get('head_context',row.get('persons',[])):
            if (person.get('cls')!='person' or person.get('predicted')
                    or person.get('measurement') is not True or not person.get('track_id')):
                continue
            box=person.get('xyxy',[])
            if len(box)!=4 or not all(math.isfinite(float(v)) for v in box) or box[2]<=box[0] or box[3]<=box[1]:
                continue
            t=round(float(row['t']),3);pid=str(person['track_id']);key=(t,pid)
            if key in seen:continue
            seen.add(key);x1,y1,x2,y2=box
            yield dict(t=t,player_id=pid,team=getattr(raw.players.get(pid),'team','unknown'),
                foot_x=round((x1+x2)/2,1),foot_y=round(y2,1),cx=round((x1+x2)/2,1),
                cy=round((y1+y2)/2,1),box=[round(v,1) for v in box],conf=round(person['conf'],3),
                source_frame=row['frame'],measurement=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--job-dir',type=Path,required=True)
    ap.add_argument('--calibration',type=Path,required=True)
    ap.add_argument('--evidence',type=Path,required=True)
    ap.add_argument('--person-stride',type=int,required=True)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--weights',type=Path,default=ROOT/'models/BODD_yolov8n_0001.pt')
    ap.add_argument('--device',default='0')
    ap.add_argument('--max-anchor-gap',type=float,default=.75)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False);revision=freeze(a.out)
    protected={str(p.resolve()):sha256(p) for p in a.job_dir.iterdir() if p.is_file()}
    raw=RawTrack.load(str(a.job_dir/'raw_track.json'));e=json.loads(a.evidence.read_text())
    cfg=RosterEvidenceConfig(use_roles=True,use_teams=True)
    validate_roster_evidence(raw,e,cfg)
    if e['video_sha256']!=sha256(raw.video_path):raise ValueError('Video/evidence mismatch')
    options=RegistrationOptions(local_recovery=True,max_anchor_gap_s=a.max_anchor_gap)
    cuts=tuple(r['t'] for r in raw.detections_meta['legacy_shots']['frames'] if r.get('cut'))
    marked={round(r['t'],3):r for r in raw.detections_meta['marked_projection']['frames']}
    projector=MarkedProjector(raw.video_path,a.calibration,raw.width,raw.height,options=options,camera_cuts=cuts)
    recovered={};audits=[];started=time.perf_counter()
    try:
        for t,row in sorted(marked.items()):
            if row['matched']:continue
            cv2.setRNGSeed(1)
            cal=projector.at(t);detail=copy.deepcopy(projector.audit[-1])
            if cal is not None:
                recovered[t]=cal;detail.update(H=cal.H,dst_m=cal.dst_m)
            audits.append(detail)
            print(f'registration {t:.2f}s: {detail["source"]}',flush=True)
    finally:projector.close()
    geometry_seconds=time.perf_counter()-started
    write_json(a.out/'registration_audit.json',dict(config=asdict(options),frames=audits,
        geometry_wall_seconds=geometry_seconds,calibration_sha256=sha256(a.calibration),
        video_sha256=e['video_sha256'],prediction=False,position_accuracy=None))
    shadow=copy.deepcopy(raw);old_keys={(o['t'],o['player_id']) for o in raw.player_obs};added=[]
    for obs in cached_person_observations(raw,a.person_stride):
        query=round(obs['t']*4)/4
        cal=recovered.get(query)
        if cal is None or (obs['t'],obs['player_id']) in old_keys:continue
        x,y=cal.to_court(obs['foot_x'],obs['foot_y'])
        if not math.isfinite(x+y) or not cal.in_court(x,y,tol=.12):continue
        shadow.player_obs.append(obs)
        shadow.player_track.append(PlayerSample(obs['t'],obs['player_id'],obs['team'],round(x,3),round(y,3),obs['conf']))
        shadow.players.setdefault(obs['player_id'],Player(obs['player_id'],obs['player_id'],'unknown'))
        added.append(dict(obs,registration_query_s=query,registration_time_offset_s=round(query-obs['t'],3)))
    shadow.player_obs.sort(key=lambda o:(o['t'],o['player_id']))
    shadow.player_track.sort(key=lambda o:(o.t,o.player_id))
    shadow.detections_meta['marked_projection_recovery']=dict(config=asdict(options),
        added_measured_positions=len(added),review_status='pending_geometry_review',
        person_stride=a.person_stride,video_sha256=e['video_sha256'],
        original_raw_sha256=sha256(a.job_dir/'raw_track.json'))
    # Recovery uses the pre-filter detector cache, not a synthesized location.
    shadow.save(str(a.out/'shadow_raw_track.json'))
    write_json(a.out/'added_observations.json',added)
    # Reuse the role classifier/collector. Preserve every old role and team
    # assignment; only fresh observations receive fresh role evidence.
    fresh=collect(shadow,a.weights,1280,a.device,cfg)
    merged=copy.deepcopy(e);old_roles={(r['t'],r['player_id']) for r in e['observations']}
    merged['observations'] += [r for r in fresh['observations'] if (r['t'],r['player_id']) not in old_roles]
    merged.update(input_signature=roster_signature(shadow),raw_sha256=sha256(a.out/'shadow_raw_track.json'),
        fresh_role_timing=fresh['timing'],appearance_policy='Original assignments frozen; new identities stay UNKNOWN')
    write_json(a.out/'shadow_evidence.json',merged)
    tc=TacticsConfig(roster_evidence_filter=True,spacing_observed_subset=True,camera_cuts_s=cuts)
    variants={};summary={}
    for name,rt,evidence in [('saved',raw,e),('evidence',shadow,e),('subset',shadow,merged)]:
        track,_=apply_roster_evidence(rt.player_track,evidence,cfg)
        frames=build_tactics_frames(track,rt.ball_track,rt.duration,tc)
        for frame in frames:
            if (not frame['players'] and frame.get('position_quality')
                    and not marked.get(frame['t'],{}).get('matched') and frame['t'] not in recovered):
                frame['position_quality']['reason']='court_registration_unavailable'
        tac=build_tactics(track,rt.ball_track,rt.players,raw.attempts,duration=rt.duration,cfg=tc)
        tac.update(team_identity={'verified':False,'labels':{'team_a':'分组A（主客未核实）','team_b':'分组B（主客未核实）'}},
            position_unverified=True,position_note='恢复位置由邻近多帧几何支持，尚待独立人工核对。')
        variants[name]=(frames,tac)
        summary[name]=dict(displayed=sum(bool(f['players']) for f in frames),frames=len(frames),
            population_rejected=sum(f.get('population_quality',{}).get('valid') is False for f in frames),
            spacing_times=len({r['t'] for r in tac['spacing']['timeline']}),accuracy=None)
    preview=a.out/'preview';preview.mkdir()
    for f in ('data.js','court.js','components.js','styles.css'):
        shutil.copy2(ROOT/'web'/f,preview/f)
    for f in ('tactics.js','overview.js'):shutil.copy2(ROOT/'web/pages'/f,preview/f)
    shutil.copytree(ROOT/'web/vendor',preview/'vendor')
    html=(ROOT/'web/tactics-coverage-preview.html').read_text().replace('战术覆盖修复对照','球场配准恢复对照')
    html=html.replace('原任务结果','上一轮位置修复').replace('角色与分队修复','新增几何位置').replace('修复＋可见球员空间曲线','新增位置＋角色检查')
    (preview/'index.html').write_text(html)
    for f in ('game.json','players.json','shotchart.json','report.json'):
        shutil.copy2(a.job_dir/f,preview/f)
    for name,(frames,tac) in variants.items():
        write_json(preview/(name+'_frames.json'),frames);write_json(preview/(name+'_tactics.json'),tac)
    write_json(preview/'meta.json',dict(job_id=a.job_dir.name,video_sha256=e['video_sha256']))
    assert [a.to_dict() for a in shadow.attempts]==[a.to_dict() for a in raw.attempts]
    for p,digest in protected.items():assert sha256(p)==digest,p
    write_json(a.out/'comparison.json',dict(revision=revision,variants=summary,
        geometry_wall_seconds=geometry_seconds,new_role_timing=fresh['timing'],
        recovered_quarter_seconds=sorted(recovered),added_measured_positions=len(added),
        old_positions_unchanged=True,shot_events_unchanged=True,original_files_unchanged=protected,
        saved_shots_in_preview=True,production_updated=False,human_truth=False,
        split='Development',video_sha256=e['video_sha256'],raw_sha256=sha256(a.job_dir/'raw_track.json')))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
