"""Bounded high-resolution visual recheck; never rewrites an existing job.

Unknown is not silently converted to a miss. Outputs remain review evidence.
"""
import argparse,json,time
from pathlib import Path
from collect_cv_baseline import freeze,write_json,sha256
from experiment_score_recovery import reanalyze
from aihoop.legacy_shots.settings import LegacyDetectOptions


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--max-windows',type=int,default=8);a=p.parse_args()
 if not 1<=a.max_windows<=12:p.error('max-windows must be 1..12')
 a.out.mkdir(parents=True,exist_ok=False);revision=freeze(a.out);original_sha=sha256(a.raw);raw=json.loads(a.raw.read_text());trace=raw['detections_meta']['legacy_shots'];context={f['frame']:f for f in trace['frames']};video=Path(raw['video_path']);modelpath=Path('models/BODD_yolov8n_0001.pt')
 from ultralytics import YOLO
 import torch
 model=YOLO(str(modelpath));cache={};rows=[];start=time.perf_counter()
 options={k:v for k,v in trace['config']['detect'].items() if k in LegacyDetectOptions.model_fields};options.update(imgsz=1280,ball_roi_recovery=False,ball_rim_recovery=False)
 for i,e in enumerate([e for e in trace['events'] if e['result']=='unknown'][:a.max_windows]):
  release=e.get('release_t',e['t']);window={'start_s':max(0,release-2),'end_s':min(raw['duration'],max(e['t'],release)+2)};torch.cuda.synchronize();t=time.perf_counter();r=reanalyze(video,window,model,options,context,cache);torch.cuda.synchronize();elapsed=time.perf_counter()-t;write_json(a.out/f'window_{i:02d}.json',r)
  row={'original_event':e,'window':window,'seconds':elapsed,'new_visual_events':r['events'],'formal_result_changed':False,'association_status':'not_automatically_merged; overlapping plays require trajectory review','truth_status':'pending_human_review'};rows.append(row);write_json(a.out/'comparison.json',{'revision':revision,'raw_sha256':original_sha,'video_sha256':sha256(video),'weights_sha256':sha256(modelpath),'options':options,'runs':rows,'total_seconds':time.perf_counter()-start,'live_fusion_touched':False,'original_result_write':False});print(json.dumps({'window':i,'original_release':release,'new_results':[(x.get('release_t'),x['result']) for x in r['events']]},ensure_ascii=False),flush=True)
 assert sha256(a.raw)==original_sha

if __name__=='__main__':main()
