"""Loopback-only human annotation workspace, independent of the analysis API."""
import argparse
import json
import math
import mimetypes
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

LOCK=threading.Lock()

def validate(data, item):
    if not isinstance(data,dict):raise ValueError('标注格式不正确')
    for key in ('shots','frames'):
        if not isinstance(data.get(key),list):raise ValueError('缺少标注列表')
    if len(data['shots'])>500 or len(data['frames'])>500:raise ValueError('标注条数过多')
    def number(value):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('时间和坐标必须是有效数字')
        return value
    for shot in data['shots']:
        if not item['start_s']<=number(shot['release_s'])<item['end_s']:raise ValueError('出手时间不在本段范围内')
        if shot['result'] not in ('made','missed','unknown'):raise ValueError('请选择进球结果')
        if shot['value'] not in (None,1,2,3):raise ValueError('分值不正确')
        if not isinstance(shot.get('is_replay',False),bool):raise ValueError('回放标记不正确')
    seen=set()
    for frame in data['frames']:
        name=frame['image']
        if name not in item['images'] or name in seen:raise ValueError('核对帧不存在或重复')
        seen.add(name)
        if frame['visibility'] not in ('visible','not_visible','unclear','pending'):raise ValueError('请选择球的状态')
        boxes=frame.get('boxes',[])
        if len(boxes)>20:raise ValueError('框选数量过多')
        for box in boxes:
            if box['kind'] not in ('ball','decoy','rim','person'):raise ValueError('框类型不正确')
            if box.get('role','UNKNOWN') not in ('PLAYER','REFEREE','SPECTATOR','UNKNOWN'):raise ValueError('人员角色不正确')
            coords=box['xyxy']
            if len(coords)!=4 or any(not 0<=number(v)<=1 for v in coords):raise ValueError('框坐标超出画面')
            if coords[2]<=coords[0] or coords[3]<=coords[1]:raise ValueError('框选范围无效')
        if frame['visibility']=='visible' and not any(b['kind']=='ball' for b in boxes):raise ValueError('球可见时请框出篮球')
        if frame['visibility'] in ('not_visible','unclear') and any(b['kind']=='ball' for b in boxes):raise ValueError('看不见或看不清时请删除篮球框')
    if data.get('frames_complete') and (len(seen)!=len(item['images']) or any(f['visibility']=='pending' for f in data['frames'])):
        raise ValueError('还有核对帧未标注')
    review=data.get('review')
    if review is not None:
        if not isinstance(review,dict):raise ValueError('审核字段不正确')
        if review.get('status') not in ('pending','in_progress','completed'):raise ValueError('审核状态不正确')
        for key in ('is_shot','is_replay'):
            if review.get(key) not in ('pending','yes','no','unknown'):raise ValueError('请明确出手和回放状态')
        if review.get('result') not in ('pending','made','missed','unknown','not_applicable'):raise ValueError('结果不正确')
        interval=review.get('release_interval')
        if interval is not None:
            if not isinstance(interval,list) or len(interval)!=2 or not item['start_s']<=number(interval[0])<=number(interval[1])<item['end_s']:
                raise ValueError('离手区间超出原片审核范围')
        if review.get('is_shot')=='no' and (data['shots'] or review.get('result') in ('made','missed')):
            raise ValueError('无出手不能同时记录出手或命中结果')
        if review.get('status')=='completed':
            if not str(review.get('reviewer','')).strip() or not data.get('shots_complete'):
                raise ValueError('完成审核需填写审核人并确认出手记录完整')
            if any(review.get(k)=='pending' for k in ('is_shot','is_replay','result')):
                raise ValueError('请先完成出手、结果和回放判断；看不清选未知')
            if review.get('is_shot')=='yes' and not data['shots']:raise ValueError('请添加已确认的出手记录')
        if any(len(str(v))>4000 for v in review.values()):raise ValueError('审核说明过长')
    data['training_approved']=False
    data['review_status']='human_completed' if (review or {}).get('status')=='completed' else 'pending_human_review'
    return data

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True);p.add_argument('--port',type=int,default=8127)
    args=p.parse_args();batch=args.batch.resolve()
    rows=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
    items={r['id']:{**r,'images':[f.name for f in sorted((batch/r['id']).glob('frame_*.jpg'))]} for r in rows}
    web=Path(__file__).resolve().parents[1]/'web'/'match-labeling.html'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data):
            body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def file(self,path):
            if not path.is_file():return self.reply(404,{'error':'文件不存在'})
            size=path.stat().st_size;start=0;end=size-1;status=200
            raw=self.headers.get('Range')
            if raw:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',raw)
                if not match:return self.reply(416,{'error':'无效的视频范围'})
                start=int(match[1]);end=min(int(match[2]) if match[2] else end,end);status=206
                if start>end:return self.reply(416,{'error':'视频范围越界'})
            self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
            if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with path.open('rb') as f:
                    f.seek(start);left=end-start+1
                    while left:
                        chunk=f.read(min(left,256*1024))
                        if not chunk:break
                        self.wfile.write(chunk);left-=len(chunk)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def do_GET(self):
            parts=unquote(urlparse(self.path).path).strip('/').split('/')
            if parts==['']:return self.file(web)
            if parts==['manifest']:return self.reply(200,list(items.values()))
            if len(parts)<2 or parts[1] not in items:return self.reply(404,{'error':'标注任务不存在'})
            item=items[parts[1]];folder=batch/item['id']
            if parts[0]=='video' and len(parts)==2:return self.file(Path(item['video']))
            if parts[0]=='original' and len(parts)==2:return self.file(Path(item.get('original_video',item['video'])))
            if parts[0]=='evidence' and len(parts)==2:
                target=folder/'evidence.json'
                return self.reply(200,json.loads(target.read_text()) if target.exists() else {})
            if parts[0]=='evidence' and len(parts)==3 and parts[2] in ('640','1280'):
                target=folder/f'evidence{parts[2]}.json'
                return self.reply(200,json.loads(target.read_text()) if target.exists() else {})
            if parts[0]=='image' and len(parts)==3 and parts[2] in item['images']:return self.file(folder/parts[2])
            if parts[0]=='annotations' and len(parts)==2:
                with LOCK:
                    target=folder/'annotations.json'
                    return self.reply(200,json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'shots':[],'frames':[],'shots_complete':False,'frames_complete':False})
            return self.reply(404,{'error':'页面不存在'})
        def do_POST(self):
            expected=f'http://127.0.0.1:{args.port}'
            if self.headers.get('Origin')!=expected:return self.reply(403,{'error':'请从本机标注页保存'})
            parts=urlparse(self.path).path.strip('/').split('/')
            if len(parts)!=2 or parts[0]!='annotations' or parts[1] not in items:return self.reply(404,{'error':'任务不存在'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:raise ValueError('请求大小不正确')
                data=validate(json.loads(self.rfile.read(size)),items[parts[1]])
                data['source']='human_user';data['video']=items[parts[1]]['video']
                data['coordinate_units']='normalized_original_frame';data['time_basis']='original_video_seconds'
                data['video_sha256']=items[parts[1]].get('video_sha256')
                data['original_sha256']=items[parts[1]].get('original_sha256')
                data['source_match_id']=items[parts[1]].get('source_match_id')
                for row in data['frames']:
                    row['image_sha256']=items[parts[1]].get('frame_sha256',{}).get(row['image'])
                    row['timestamp']=items[parts[1]].get('frame_times',{}).get(row['image'])
                data['saved_at']=datetime.now(timezone.utc).isoformat()
                target=batch/parts[1]/'annotations.json'
                with LOCK:
                    temp=target.with_suffix('.json.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,target)
                self.reply(200,{'saved':True})
            except (ValueError,KeyError,TypeError) as e:self.reply(400,{'error':str(e)})
            except OSError:self.reply(500,{'error':'保存失败，请保留页面并重试'})
    print(f'http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()

if __name__=='__main__':main()
