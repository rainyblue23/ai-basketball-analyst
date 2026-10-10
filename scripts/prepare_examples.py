"""Build real, read-only local examples once; rerun to resume unfinished examples."""
from pathlib import Path
import json, shutil, time, uuid, os
import cv2
from aihoop import api
from aihoop.job_recovery import process_identity

ROOT=api.ROOT
SOURCE=Path('D:/dsh_folder/aihoop_assets/samples/bili')
specs=[('yang','BV1e8HS6HEv4','杨瀚森比赛片段','多机位集锦 · 约 1 分半'),('lillard','BV165YQ68E3C','利拉德绝杀片段','终场进攻与回放 · 约 3 分钟'),('harden','BV1sHYN6uEGd','哈登比赛集锦','多个进攻回合 · 约 6 分钟')]
manifest={'version':1,'examples':[]}
target=ROOT/'data/example_gallery.json'
previous = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
previous_items = {x['id']: x for x in previous.get('examples', [])}

def persist():
    tmp=target.with_suffix('.tmp'); tmp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(tmp,target)
for key,bv,title,description in specs:
    video=next(SOURCE.glob('*'+bv+'*.mp4'))
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS);duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps;cap.release()
    manifest['examples'].append(dict(id=key,title=title,description=description,video_path=str(video),duration=round(duration,3),source_url='https://www.bilibili.com/video/'+bv))
for item in manifest['examples']:
    old = previous_items.get(item['id'], {})
    for field in ('analysis_job_id', 'prepared_at'):
        if field in old: item[field] = old[field]
persist()
for item in manifest['examples']:
    directory=ROOT/'out/examples'/item['id']
    if (directory/'game.json').exists() and item.get('prepared_at'):
        print('Already prepared:',item['id'],flush=True);continue
    jid=uuid.uuid4().hex[:12]
    req=api.JobCreate(source='video',video_path=item['video_path'],allow_no_calibration=True,detect_players=True,player_stride=3,device='0',score_policy='court',shot_engine='legacy',auto_sliding=True,sliding_stride=30,make_highlights=True,highlight_limit=8)
    st=api.JobState(job_id=jid,source='video',video_path=item['video_path'],payload=req.model_dump())
    st.payload['_worker_owner']=process_identity();api._mem[jid]=st;api._persist(st)
    print('Analyzing',item['id'],'job',jid,flush=True);start=time.time()
    api._run_job(jid,req)
    if st.status!='done':
        print('FAILED',item['id'],st.error,flush=True);continue
    shutil.copytree(Path(st.out_dir),directory,dirs_exist_ok=True)
    cap=cv2.VideoCapture(item['video_path']);cap.set(cv2.CAP_PROP_POS_MSEC,min(3000,item['duration']*300));ok,frame=cap.read();cap.release()
    if ok:
        h,w=frame.shape[:2];frame=cv2.resize(frame,(640,round(h*640/w)));cv2.imwrite(str(directory/'poster.jpg'),frame)
    item['analysis_job_id']=jid;item['prepared_at']=time.strftime('%Y-%m-%d %H:%M:%S');persist()
    game=json.loads((directory/'game.json').read_text(encoding='utf-8'))
    tl=game.get('timeline',[])
    print('READY',item['id'],'elapsed',round(time.time()-start),'events',len(tl),'made',sum(x.get('result')=='made' for x in tl),flush=True)
print('Preparation finished',flush=True)
