"""Same-source full pipeline camera descriptor reuse/demand experiment, offline."""
import argparse,json,time,gc
from pathlib import Path
from collections import Counter
import cv2,torch
from collect_cv_baseline import freeze,write_json,sha256,environment_model_paths,inventory
from aihoop.sources import VideoSource
from aihoop.court import Calibration
from aihoop import frame_motion


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--videos',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 revision=freeze(a.out);inv=inventory(a.out,environment_model_paths());write_json(a.out/'inventory.json',inv)
 original_features=frame_motion.motion_features;original_estimate=frame_motion.estimate_frame_motion;features_ms=[];geometry_ms=[]
 def timed_features(*args,**kwargs):
  t=time.perf_counter();r=original_features(*args,**kwargs);features_ms.append((time.perf_counter()-t)*1000);return r
 def timed_estimate(*args,**kwargs):
  t=time.perf_counter();r=original_estimate(*args,**kwargs);geometry_ms.append((time.perf_counter()-t)*1000);return r
 frame_motion.motion_features=timed_features;frame_motion.estimate_frame_motion=timed_estimate
 runs=[]
 try:
  for vi,video in enumerate(a.videos):
   results=[]
   for variant in ('original','cached','cached_demand'):
    general={'dynamic_rim':True,'camera_feature_cache':variant!='original','camera_demand_only':variant=='cached_demand'}
    source=VideoSource(str(video.resolve()),Calibration(method='unavailable'),weights=inv['selected_player_weights'],ball_weights=inv['selected_ball_weights'],hoop_weights=inv['selected_hoop_weights'],device='0',scoreboard=False,auto_sliding=False,detect_players=True,player_stride=2,legacy_detect={'general':general},score_policy='court')
    features_ms.clear();geometry_ms.clear();torch.cuda.synchronize();cpu=time.process_time();start=time.perf_counter();raw=source.run();torch.cuda.synchronize();seconds=time.perf_counter()-start;cpu=time.process_time()-cpu
    folder=a.out/f'{vi:02d}_{video.stem}_{variant}';folder.mkdir();raw.save(str(folder/'raw_track.json'));trace=raw.detections_meta['legacy_shots'];frames=trace['frames']
    row=dict(video=str(video),video_sha256=sha256(video),variant=variant,options=general,frames=len(frames),seconds=seconds,process_cpu_seconds=cpu,feature_calls=len(features_ms),feature_seconds=sum(features_ms)/1000,estimate_calls=len(geometry_ms),estimate_seconds=sum(geometry_ms)/1000,camera_wall_seconds=sum((f.get('camera_motion') or {}).get('geometry_wall_ms',0) for f in frames)/1000,descriptor_cache_hits=sum(bool((f.get('camera_motion') or {}).get('descriptor_cache_hit')) for f in frames),demand_skips=sum((f.get('camera_motion') or {}).get('reason')=='geometry_not_consumable' for f in frames),measured_rim_frames=[f['frame'] for f in frames if (f.get('tracked_rim') or {}).get('fresh')],rim_states=dict(Counter((f.get('tracked_rim') or {}).get('status') for f in frames)),cut_frames=[f['frame'] for f in frames if f.get('cut')],events=trace['events'],accuracy_truth_available=False,cv2_threads=cv2.getNumThreads(),torch_threads=torch.get_num_threads())
    # Full per-frame equality of observation/state geometry, not just counts.
    signature=[{k:f.get(k) for k in ('frame','t','ball','rim','tracked_rim','cut','tracker_reason')} for f in frames]
    if results:
     row['observation_geometry_events_equal_original']=(signature==results[0][0] and trace['events']==results[0][1])
    results.append((signature,trace['events']));runs.append(row);write_json(a.out/'comparison.json',{'revision':revision,'inventory':inv,'runs':runs,'scope':'Single run per variant; full VideoSource including player detection, decode, stream; excludes subsequent save/render; counters overlap (estimate includes feature extraction). No accuracy claim.'});print(json.dumps({k:v for k,v in row.items() if k not in ('measured_rim_frames','events')},ensure_ascii=False),flush=True)
    del raw,source;gc.collect()
 finally:frame_motion.motion_features=original_features;frame_motion.estimate_frame_motion=original_estimate

if __name__=='__main__':main()
