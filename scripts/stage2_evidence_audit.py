"""Read-only source-identity and event-error audit; never edits truth or algorithms."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import subprocess
import cv2

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT.parent / 'aihoop_assets'
OUT = ROOT / 'out/stage2_audit_20261020'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def probe(path):
    data = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)], encoding='utf-8'))
    stream = next(s for s in data['streams'] if s['codec_type']=='video')
    n,d = stream.get('avg_frame_rate','0/1').split('/')
    return dict(duration_s=float(data['format']['duration']), fps=float(n)/float(d),
        width=stream['width'], height=stream['height'], codec=stream['codec_name'],
        encoder=stream.get('tags',{}).get('encoder', data['format'].get('tags',{}).get('encoder')),
        nb_frames=stream.get('nb_frames'), start_time=stream.get('start_time'))


def identity():
    files = list((ASSETS/'samples').rglob('*'))
    videos = [p for p in files if p.suffix.lower() in ('.mp4','.mov','.mkv','.webm','.avi')]
    hashes = {str(p):sha(p) for p in videos}
    groups = {}
    for p,h in hashes.items():
        groups.setdefault(h,[]).append(p)
    rows = []
    truth_paths = [ROOT/'eval/ground_truth/shots_split2_20261011.json', ROOT/'eval/ground_truth/match_testset_20261011.json']
    for path in truth_paths:
        data=read(path)
        for s in data['samples']:
            p=Path(s['video']); actual=hashes.get(str(p))
            metadata=probe(p) if p.exists() else {}
            test=s['id'].startswith('match_')
            rows.append(dict(id=s['id'], truth_file=str(path), truth_sha256=sha(path),
                source_match_id=s.get('source_match_id'), source_match_id_status='pending' if not s.get('source_match_id') else 'declared',
                source_group_key='local_asset:'+p.stem, source_group_status='provisional_not_verified_match_identity',
                video=str(p), expected_sha256=s.get('source_sha256'), actual_sha256=actual,
                sha_matches=actual==s.get('source_sha256'), expected_sha_found_at=groups.get(s.get('source_sha256'),[]),
                review_start_s=s['start_s'], review_end_s=s['end_s'], complete_declared=s.get('shots_complete'),
                time_basis=data.get('time_basis'), full_source_offset_s=None, offset_status='pending',
                annotation_count=len(s.get('shots',[])), times_valid=all(s['start_s']<=x['release_s']<s['end_s'] for x in s.get('shots',[])),
                dataset_split=('Quarantined' if test else ('Validation_exposed' if 'game03' in s['id'] else 'Development')),
                prior_use=('training' if s['id'] in ('match_01','match_02') else 'validation_and_diagnostics') if test else 'baseline_evaluated',
                mismatch_cause='UNKNOWN_original_bytes_and_decode_reference_missing' if test else None,
                metadata=metadata))
    imported=ROOT/'eval/annotation_imports/three_bili_20261020/annotations.normalized.json'
    if imported.exists():
        for s in read(imported)['samples']:
            rows.append(dict(id=s['id'], truth_file=str(imported), source_match_id=None,
                source_group_key='bilibili:'+s['source_id'], source_group_status='same_BV_group_all_replays',
                source_match_id_status='pending_full_match_identity', video=s['video'],
                expected_sha256=s['source_sha256'],actual_sha256=hashes.get(s['video']),
                sha_matches=hashes.get(s['video'])==s['source_sha256'],
                review_start_s=0,review_end_s=s['duration_s'],complete_declared=s['shots_complete'],
                time_basis=s['time_basis'], full_source_offset_s=None,offset_status='pending',
                annotation_count=len(s['shots']),dataset_split='Development', prior_use='curated_examples',
                replay_count=sum(x['is_replay'] for x in s['shots']), metadata=probe(Path(s['video']))))
    dump(OUT/'identity_manifest.json',dict(samples=rows, exact_duplicate_video_groups=[v for v in groups.values() if len(v)>1],
        scanned_video_count=len(videos), policy='No expected hashes changed. Same match must remain in one source group; unverified groups cannot enter Independent Test.'))
    lines=['# DATASET IDENTITY AUDIT','', '日期：2026-10-20。只读核查，未修改预期SHA或真值。','',
        '|样本|SHA一致|条目|用途|来源身份|','|---|---|---:|---|---|']
    for r in rows:
        lines.append(f"|{r['id']}|{r['sha_matches']}|{r['annotation_count']}|{r['dataset_split']}|{r['source_match_id_status']}|")
    lines += ['', '## 四段历史测试集', '',
        '4段均存在但字节哈希不符；对samples下所有视频按SHA搜索，匹配位置见identity_manifest.json。纯重命名不会改变SHA，不能单独解释差异。',
        '当前没有旧文件、旧解码帧摘要或逐包摘要，不能判定是转码、重封装、裁剪、替换错误源还是内容变化。全部继续隔离。',
        '本地_videofind/finalize_pro.ps1记录过ACB重编码及素材重命名；pro_sources.json的早期WNBA来源指向后来被README纠正的错误节目。它们证明历史有变更风险，不能证明本次SHA差异的具体原因。',
        'eval/ball_feedback_validation.md明确：match_01/02用于训练，match_03/04用于验证和诊断。因此恢复旧SHA也不能使这四段成为独立测试。', '',
        '## 来源与时间', '',
        '原标注没有source_match_id。manifest另存provisional source_group_key，不能把文件名或不同BV号直接当作不同比赛的证据。',
        '同一源字节重复件已分组；同比赛的不同转码/剪辑不能靠SHA自动证明，需比赛日期/对阵/场次及原片出处确认后合并来源组。',
        '31条真值的时间指向当前4分钟素材或训练短片，不是已恢复的整场原片时间。原片剪辑偏移保持pending。审核完整性仅有用户声明，未重新标注。',
        'game03已经在历史报告公开评估过，记Validation_exposed；只能做跨来源回归，不能当未见过的锁定测试。',
        '三段Bili为Development，59次画面出现、57次去回放出手；全部有视频SHA，来源分组采用BV号，完整比赛身份仍pending。', '',
        '## 恢复条件', '',
        '找回冻结原文件或带哈希的备份；比较解码帧/音频时间对应，建立可复现的时间映射。若确认内容或裁剪改变，则新建数据版本并重新人工审核，禁止改旧预期SHA。',
        '新Independent Test需按真实比赛来源隔离、未训练未诊断、完整审核区间、锁定视频SHA/时间偏移/回放关系。当前锁定Independent Test为0。', '',
        '[逐视频SHA、媒体元数据与来源清单](out/stage2_audit_20261020/identity_manifest.json)']
    (ROOT/'DATASET_IDENTITY_AUDIT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return rows


def metrics(rows):
    tp=sum(r['event_class']=='TP' for r in rows); fp=sum(r['event_class']=='FP_unmatched' for r in rows); fn=sum(r['event_class']=='FN_unmatched' for r in rows)
    mtp=sum(r['made_class']=='TP' for r in rows); mfp=sum(r['made_class']=='FP' for r in rows); mfn=sum(r['made_class']=='FN' for r in rows)
    def calc(a,b,c):
        p=a/(a+b) if a+b else None; r=a/(a+c) if a+c else None
        return dict(tp=a,fp=b,fn=c,precision=p,recall=r,f1=2*p*r/(p+r) if p and r else 0)
    return dict(event=calc(tp,fp,fn),made=calc(mtp,mfp,mfn),unknown=sum(r.get('model_result')=='unknown' for r in rows))


def analyze(identity_rows, baseline_path):
    truth=read(ROOT/'eval/ground_truth/shots_split2_20261011.json')
    base=read(baseline_path)
    if base['truth_sha256'] != sha(ROOT/'eval/ground_truth/shots_split2_20261011.json'):
        raise ValueError('Baseline truth hash mismatch')
    manifest={r['id']:r for r in identity_rows}
    all_rows=[]
    for s in base['samples']:
        sample=next(x for x in truth['samples'] if x['id']==s['id']); ident=manifest[s['id']]
        if not ident['sha_matches']:
            raise ValueError('31-shot source identity mismatch')
        rawpath=Path(baseline_path).parent/sample['id']/'raw_track.json'
        legacy=read(rawpath)['detections_meta']['legacy_shots'] if rawpath.exists() else {}
        frames=legacy.get('frames',[])
        pairs={p['truth_index']:p for p in s['pairs']}; used={p['event_index'] for p in s['pairs']}
        tuples=[(i,pairs[i]['event_index'] if i in pairs else None) for i in range(len(s['truth']))]+[(None,j) for j in range(len(s['events'])) if j not in used]
        cap=cv2.VideoCapture(sample['video'])
        for seq,(ti,ei) in enumerate(tuples):
            tr=s['truth'][ti] if ti is not None else None; ev=s['events'][ei] if ei is not None else None
            full_ev=legacy.get('events',[])[ei] if legacy and ei is not None else None
            t=tr['release_s'] if tr else ev['release_s']
            end=max(t+2.0, ev.get('decision_s',t) if ev else t+2.0)
            window=[f for f in frames if t-0.5<=f['t']+sample['start_s']<=end+0.5]
            real=[f for f in window if f.get('ball') and not f['ball'].get('predicted')]
            rim=[f for f in window if f.get('tracked_rim') and f['tracked_rim'].get('fresh')]
            crossing=full_ev.get('crossing_t') if full_ev else None
            reason=(full_ev or {}).get('review_reason') or (full_ev or {}).get('evidence') or (ev or {}).get('evidence')
            hypotheses=[]
            if window and len(real)/len(window)<0.3: hypotheses.append('ball_observation_sparse')
            if window and len(rim)/len(window)<0.5: hypotheses.append('rim_tracking_sparse')
            if any(f.get('cut') for f in window): hypotheses.append('camera_cut_in_window')
            if not hypotheses: hypotheses.append('requires_frame_and_state_review')
            event_class='TP' if tr and ev else ('FN_unmatched' if tr else 'FP_unmatched')
            made_class='TP' if tr and tr['result']=='made' and ev and ev['result']=='made' else ('FP' if ev and ev['result']=='made' else ('FN' if tr and tr['result']=='made' else None))
            candidate_times=[dict(index=j,time=e['release_s'],delta_s=abs(t-e['release_s'])) for j,e in enumerate(s['events']) if abs(t-e['release_s'])<=3]
            row=dict(case_id=f"{s['id']}_{seq:03}", sample=sample['id'],video=sample['video'],
                source_match_id=ident.get('source_match_id'),source_group_key=ident['source_group_key'],source_sha256=ident['actual_sha256'],
                original_full_game_time_s=None, video_time_s=t,
                frame_index_estimate=round(t*ident['metadata']['fps']), frame_index_basis='round(time*avg_fps); diagnostic decode index must be verified',
                truth_index=ti,event_index=ei,human_truth=tr,model_output=ev,full_event=full_ev,
                model_result=ev['result'] if ev else None,event_class=event_class,made_class=made_class,
                match_reason='maximum chronological one-to-one matching; tolerance 1.5s; minimum total error',
                matched_delta_s=abs(tr['release_s']-ev['release_s']) if tr and ev else None,
                nearby_predictions=candidate_times,
                unknown_reason=reason if ev and ev['result']=='unknown' else None,
                player_attribution_status='NOT_EVALUABLE_players_disabled_and_no_identity_truth',
                evidence_window_s=[t-0.5,end+0.5],sampled_frames=len(window),real_ball_frames=len(real),fresh_rim_frames=len(rim),
                cuts=sum(bool(f.get('cut')) for f in window),crossing_t=crossing,
                possible_failure_modules=hypotheses, diagnosis_status='hypothesis_not_proven_cause',
                fp_semantics='unmatched event within reviewed interval; non-shot identity requires visual review' if not tr else None,
                raw_evidence_path=str(rawpath) if rawpath.exists() else None)
            pic=OUT/'keyframes'/f"{row['case_id']}.jpg";pic.parent.mkdir(exist_ok=True)
            target=(ev.get('crossing_s') or ev.get('decision_s')) if ev else t
            cap.set(cv2.CAP_PROP_POS_MSEC,max(0,target)*1000);ok,img=cap.read()
            if ok:
                decoded_next=cap.get(cv2.CAP_PROP_POS_FRAMES)
                row['keyframe_decoded_index']=int(decoded_next)-1
                row['keyframe_target_s']=target
                cv2.putText(img,f"{row['case_id']} t={target:.3f} GT={tr['result'] if tr else '-'} model={ev['result'] if ev else '-'}",(12,25),cv2.FONT_HERSHEY_SIMPLEX,0.55,(0,255,255),2)
                if frames:
                    nearest=min(frames,key=lambda f:abs(f['t']+sample['start_s']-target))
                    row['keyframe_overlay_trace_t']=nearest['t']+sample['start_s']
                    for field,color in [('ball',(0,255,255)),('rim',(0,180,0))]:
                        obj=nearest.get(field)
                        if obj and obj.get('xyxy'):
                            box=[int(v) for v in obj['xyxy']];cv2.rectangle(img,tuple(box[:2]),tuple(box[2:]),color,2)
                cv2.imwrite(str(pic),img,[cv2.IMWRITE_JPEG_QUALITY,78]);row['keyframe']=str(pic)
            all_rows.append(row)
        cap.release()
    dump(OUT/'event_cases.json',dict(baseline=str(baseline_path),baseline_sha256=sha(baseline_path),metrics=metrics(all_rows),cases=all_rows))
    fields=['case_id','sample','video_time_s','frame_index_estimate','event_class','made_class','model_result','unknown_reason','real_ball_frames','fresh_rim_frames','sampled_frames','cuts','player_attribution_status']
    for name,subset in [('all_event_cases.csv',all_rows),('fp_fn_made_errors.csv',[r for r in all_rows if r['event_class']!='TP' or r['made_class'] in ('FP','FN')])]:
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(subset)
    body=['<!doctype html><meta charset="utf-8"><title>事件诊断索引</title><h1>事件诊断索引</h1><p>黄框=球，绿框=检测筐。帧仅为诊断证据，不自动证明因果。原片整场偏移未知。播放器定位使用本地视频秒。</p>']
    for r in all_rows:
        video=Path(r['video']).as_uri()+f"#t={max(0,r['video_time_s']-2):.3f}"
        body.append(f"<section><h2>{r['case_id']} / {r['event_class']} / made:{r['made_class']}</h2><p>{html.escape(str(r['human_truth']))}<br>{html.escape(str(r['model_output']))}</p><a href='{video}'>打开本地视频</a><br><video controls preload='none' width='640' src='{video}'></video>")
        if r.get('keyframe'):body.append(f"<a href='{Path(r['keyframe']).as_uri()}'><img width='640' src='{Path(r['keyframe']).as_uri()}'></a>")
        sheet=OUT/'keyframes'/f"{r['case_id']}_sheet.jpg"
        if sheet.exists():body.append(f"<a href='{sheet.as_uri()}'>查看8帧时序拼图</a>")
        body.append('</section>')
    (OUT/'diagnostic_index.html').write_text('\n'.join(body),encoding='utf-8')
    return all_rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path);p.add_argument('--identity-only',action='store_true');a=p.parse_args()
    OUT.mkdir(exist_ok=True,parents=True)
    rows=identity()
    if not a.identity_only:
        cases=analyze(rows,a.baseline or ROOT/'eval/baselines/events_players_off_split2_20261011.json')
        print(json.dumps(metrics(cases),ensure_ascii=False))


if __name__=='__main__':main()
