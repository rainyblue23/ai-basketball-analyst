"""Rebuild curated examples from explicit human truth; never modify detector evidence.

Run with --write-truth to save the two supplied annotation tables, then rebuild.
Raw tracks and automatic attempts remain byte-for-byte unchanged.
"""
from pathlib import Path
import argparse, copy, csv, hashlib, json, subprocess, time
from aihoop.sources import RawTrack
from aihoop.pipeline import PipelineConfig, run_pipeline
from aihoop.highlight import ffmpeg_path

ROOT = Path(__file__).resolve().parents[1]

def supplied_truth():
    # (release second, outcome, explicitly confirmed value, note)
    lillard = [(2,1,None,''),(15,0,None,''),(21,0,None,'上篮被盖'),
        (41,0,1,'罚球'),(47,0,None,''),(57,1,2,'上篮'),(67,1,None,''),
        (76,0,None,''),(104,1,3,''),(111,1,None,''),(120,1,2,'上篮'),
        (130,0,2,'上篮'),(141,1,3,'绝杀首次播放'),
        (159,1,3,'同一次绝杀回放'),(171,1,3,'同一次绝杀回放')]
    harden = [(5,1,3,''),(14,1,3,''),(25,1,None,''),(33,0,None,''),
        (37,1,3,''),(50,1,2,'上篮'),(58,1,3,''),(67,1,2,'上篮'),
        (76,1,None,''),(86,1,2,'上篮'),(97,1,2,'上篮'),(106,1,3,''),
        (115,0,2,'上篮未中'),(116,1,2,'随后补扣；时刻为近似值，需核对离手帧'),
        (125,1,3,''),(136.5,1,2,'空接'),(145,1,2,'篮下'),(154,1,3,''),
        (164,1,2,'篮下'),(173,1,None,''),(181,1,3,''),(193,1,3,''),
        (202,1,3,''),(212,1,3,''),(221,1,2,'篮下'),(231,1,3,''),
        (238,1,None,''),(250,1,2,'上篮'),(260,1,2,'上篮'),(283,1,2,'上篮'),
        (288,1,2,'空接'),(303,1,None,''),(313,1,None,''),(325,0,None,'')]
    result = {}
    for key, rows in [('lillard',lillard),('harden',harden)]:
        shots=[]
        for i,(t,m,v,note) in enumerate(rows,1):
            row=dict(id=f'{key}_{i:02}',release_t=t,result='made' if m else 'missed',
                value=v,is_free_throw=v==1,note=note)
            if key=='lillard' and t in (141,159,171):
                row['play_id']='lillard_buzzer';row['is_replay']=t!=141
            shots.append(row)
        result[key]=dict(sample=key,source='human_user',confirmed_date='2026-10-11',
            scope='all_players_entire_video',time_basis='approximate_release_seconds',
            free_throws_separate=True,shots=shots)
    return result

def counts(shots):
    field=[s for s in shots if not s['is_free_throw']]
    free=[s for s in shots if s['is_free_throw']]
    unique=[s for s in field if not s.get('is_replay')]
    return dict(field_attempts=len(field),field_made=sum(s['result']=='made' for s in field),
        free_throw_attempts=len(free),free_throw_made=sum(s['result']=='made' for s in free),
        attempts=len(shots),made=sum(s['result']=='made' for s in shots),unknown=0,
        unique_field_attempts=len(unique),unique_field_made=sum(s['result']=='made' for s in unique),
        replay_count=sum(bool(s.get('is_replay')) for s in shots))

def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def rebuild(key, truth, clips=True):
    directory=ROOT/'out/examples'/key
    raw_path=directory/'raw_track.json'
    digest=hashlib.sha256(raw_path.read_bytes()).hexdigest()
    rt=RawTrack.load(str(raw_path)); automatic=copy.deepcopy(rt.attempts)
    rt.attempts=[];rt.scoreboard_events=[];rt.base_score={}
    extra=[]
    for s in truth['shots']:
        extra.append(dict(t=s['release_t'],team='',player_id='',x=0,y=-1.575,
            is_free_throw=s['is_free_throw'],forced_value=s['value'],made=s['result']=='made',
            manual=True,conf=1,source='manual',location_source='rim_placeholder',
            counts_for_score=False,value_assumed=s['value'] is None,
            tags=['human_review','team_unknown','player_unknown']+(['replay'] if s.get('is_replay') else []),
            evidence='human_review',release_source='manual',clip_end=s['release_t']+4))
    # Only the temporary in-memory attempt list changes; raw detector evidence stays intact.
    result=run_pipeline(rt,PipelineConfig(out_dir=str(directory),extra_attempts=extra,
        make_highlights=False,video_path=rt.video_path))
    game=result.game
    summary=counts(truth['shots'])
    summary.update(source='human_user',reviewed_at=truth['confirmed_date'],
        teams_verified=False,players_verified=False,time_basis=truth['time_basis'],
        automatic_attempts=len(automatic),automatic_made=sum(a.made is True for a in automatic),
        automatic_raw_sha256=digest,truth_sha256=hashlib.sha256(json.dumps(truth,sort_keys=True).encode()).hexdigest(),
        unknown_field_values=sum(s['value'] is None for s in truth['shots']),
        note='人工逐球复核；重复回放单列。队别、出手人及未说明的分值待确认。')
    game['meta']['sample_review']=summary
    game['judgement']=dict(state='human_review',note=summary['note'])
    timeline=game['timeline']
    assert len(timeline)==len(truth['shots'])
    for i,(e,s) in enumerate(zip(timeline,truth['shots'])):
        e.update(index=i,review_id=s['id'],shot_type='free_throw' if s['is_free_throw'] else 'field_goal',
            value_verified=s['value'] is not None,review_note=s['note'],
            is_replay=s.get('is_replay',False),play_id=s.get('play_id',s['id']))
    write_json(directory/'human_review.json',truth)
    write_json(directory/'automatic_attempts.json',[a.to_dict() for a in automatic])
    (directory/'highlights').mkdir(exist_ok=True)
    index=[];ff=ffmpeg_path()
    for i,s in enumerate(truth['shots'],1):
        start=max(0,s['release_t']-2);end=min(rt.duration,s['release_t']+4)
        path=f'highlights/review_{i:02}.mp4';target=directory/path
        available=False
        if clips and ff:
            completed=subprocess.run([ff,'-hide_banner','-loglevel','error','-y','-ss',str(start),
                '-i',rt.video_path,'-t',str(end-start),'-vf','scale=960:-2','-c:v','libx264',
                '-preset','ultrafast','-crf','24','-c:a','aac','-movflags','+faststart',str(target)],
                capture_output=True,timeout=90)
            available=completed.returncode==0 and target.exists()
            if not available: raise RuntimeError(completed.stderr.decode(errors='replace'))
        label=('罚球' if s['is_free_throw'] else '运动战')+' · '+('命中' if s['result']=='made' else '未中')
        if s.get('is_replay'):label+=' · 重复回放'
        index.append(dict(index=i,t=s['release_t'],start=start,end=end,path=path if available else None,
            made=s['result']=='made',result=s['result'],value=s['value'],value_assumed=s['value'] is None,
            team='',player_id='',label=label,available=available,source='manual',is_replay=s.get('is_replay',False)))
    game['highlights']=index
    write_json(directory/'highlights/index.json',dict(clips=index,source='human_review'))
    write_json(directory/'game.json',game)
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    report.update(sample_review=summary,final_score=None,winner=None,margin=None)
    write_json(directory/'report.json',report)
    lines=[f'# {key} · 人工逐球复核','',
        f"运动战（含回放）{summary['field_attempts']} 投 {summary['field_made']} 中；罚球 {summary['free_throw_attempts']} 投 {summary['free_throw_made']} 中。",
        f"去重后运动战 {summary['unique_field_attempts']} 投 {summary['unique_field_made']} 中；重复回放 {summary['replay_count']} 条。",'',
        '结果来自用户人工记录，不代表自动检测准确率。队别、球员、未说明的分值与出手位置未确认。','',
        '| 时间（秒） | 结果 | 分值 | 说明 |','|---|---|---|---|']
    for s in truth['shots']:lines.append(f"| {s['release_t']} | {'中' if s['result']=='made' else '未中'} | {s['value'] or '待确认'} | {s['note']} |")
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    report['markdown']='\n'.join(lines);write_json(directory/'report.json',report)
    with (directory/'review_shots.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['id','release_t','result','value','is_free_throw','is_replay','play_id','note'])
        writer.writeheader();writer.writerows(truth['shots'])
    assert digest==hashlib.sha256(raw_path.read_bytes()).hexdigest(), 'Automatic evidence was modified'
    assert all(e['points']==0 and e['source']=='manual' for e in timeline)
    print(key,json.dumps(summary,ensure_ascii=False),flush=True)
    return summary

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write-truth',action='store_true')
    parser.add_argument('--no-clips',action='store_true');args=parser.parse_args()
    for key,truth in supplied_truth().items():
        path=ROOT/'eval/ground_truth'/f'{key}_bili_timed.json'
        if args.write_truth:write_json(path,truth)
        rebuild(key,json.loads(path.read_text(encoding='utf-8')),not args.no_clips)
    manifest=ROOT/'data/example_gallery.json'
    data=json.loads(manifest.read_text(encoding='utf-8'))
    for item in data['examples']:
        if item['id'] in ('lillard','harden'):
            item['prepared_at']=time.strftime('%Y-%m-%d %H:%M:%S')
            item['review_provenance']='human_user_timed_truth_20261011'
    write_json(manifest,data)

if __name__=='__main__':main()
