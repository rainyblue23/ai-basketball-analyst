"""A-F general-vision ablation on identical development videos; no labels in inference."""
import argparse
from collections import Counter
import gc
import json
from pathlib import Path
import time

from collect_cv_baseline import freeze,environment_model_paths,inventory,write_json,sha256
from aihoop.sources import VideoSource
from aihoop.court import Calibration

VARIANTS={
    'A':{},'B':{'adaptive_ball':True},'C':{'dynamic_rim':True},
    'D':{'release_shadow':True},'E':{'release_shadow':True,'dynamic_rim':True},
    'F':{'adaptive_ball':True,'dynamic_rim':True,'release_shadow':True,'role_shadow':True,'replay_shadow':True}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--videos',type=Path,nargs='+',required=True)
    p.add_argument('--variants',nargs='+',choices=list(VARIANTS),default=list(VARIANTS))
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('Choose a NEW output directory')
    if any(not v.is_file() for v in a.videos):p.error('Video missing')
    a.out.mkdir(parents=True);revision=freeze(a.out);inv=inventory(a.out,environment_model_paths())
    write_json(a.out/'inventory.json',inv)
    from ultralytics import YOLO
    import torch
    original_predict=YOLO.predict;timings=[]
    def measured_predict(self,*args,**kwargs):
        results=original_predict(self,*args,**kwargs)
        if isinstance(results,list):
            timings.extend(float((r.speed or {}).get('inference') or 0.) for r in results)
        return results
    YOLO.predict=measured_predict
    report={'revision':revision,'scope':'Development observations only; precision/recall need reviewed truth',
            'annotation_input_to_inference':False,'device':'0','gpu':torch.cuda.get_device_name(0),
            'torch':torch.__version__,'cuda':torch.version.cuda,'runs':[]}
    try:
        for vi,video in enumerate(a.videos):
            for variant in a.variants:
                folder=a.out/f'{vi:02d}_{video.stem}_{variant}';folder.mkdir()
                opts={'general':VARIANTS[variant]}
                source=VideoSource(str(video.resolve()),Calibration(method='unavailable'),
                    weights=inv['selected_player_weights'],ball_weights=inv['selected_ball_weights'],
                    hoop_weights=inv['selected_hoop_weights'],device='0',scoreboard=False,
                    auto_sliding=False,detect_players=True,player_stride=2,legacy_detect=opts,score_policy='court')
                timings.clear();torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
                raw=source.run();seconds=time.perf_counter()-start
                raw.save(str(folder/'raw_track.json'));trace=raw.detections_meta['legacy_shots'];frames=trace['frames']
                shadow=trace.get('release_shadow') or {};candidates=shadow.get('candidates',[])
                row=dict(video=str(video.resolve()),video_sha256=sha256(video),variant=variant,
                    general=source.legacy_detect['general'],frames=len(frames),seconds=seconds,
                    processing_fps=len(frames)/seconds,gpu_yolo_reported_inference_ms=sum(timings),
                    gpu_timing_note='Sum Ultralytics per-result inference timings, not total CUDA kernel busy time',
                    gpu_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                    ball_frames=trace['real_ball_frames'],rim_usable_frames=sum(bool((f.get('tracked_rim') or {}).get('fresh')) for f in frames),
                    rim_states=dict(Counter((f.get('tracked_rim') or {}).get('status','LOST') for f in frames)),
                    rim_jump_rejections=sum(f['tracker_reason']=='jump_rejected' for f in frames),
                    camera_verified_frames=sum(bool((f.get('camera_motion') or {}).get('ok')) for f in frames),
                    events=trace['events'],event_results=dict(Counter(e['result'] for e in trace['events'])),
                    shadow_candidates=len(candidates),shadow_states=dict(Counter(c['candidate_state'] for c in candidates)),
                    shadow_types=dict(Counter(c['shot_type'] for c in candidates)),
                    shadow_unknown_fraction=sum(c['candidate_state']=='UNKNOWN' for c in candidates)/len(candidates) if candidates else None,
                    candidate_player_assigned_fraction=sum(c['player_track_id'] not in (None,'UNKNOWN') for c in candidates)/len(candidates) if candidates else None,
                    role_counts=dict(Counter(p['role'] for f in frames for p in f.get('player_roles',[]))),
                    replay_links=shadow.get('replay_links',[]),
                    basketball_tp=None,basketball_fp=None,basketball_fn=None,rim_localization_quality=None,
                    shot_tp=None,shot_fp=None,shot_fn=None,pass_scramble_false_positives=None,
                    player_attribution_accuracy=None,truth_status='coarse claims only; exact truth pending',
                    raw_path=str(folder/'raw_track.json'))
                write_json(folder/'metrics.json',row);report['runs'].append(row);write_json(a.out/'comparison.json',report)
                print(json.dumps({k:row[k] for k in ('variant','video','seconds','gpu_yolo_reported_inference_ms','ball_frames','rim_usable_frames','rim_jump_rejections','event_results','shadow_candidates','shadow_states')},ensure_ascii=False),flush=True)
                del source,raw;gc.collect()
    finally:YOLO.predict=original_predict


if __name__=='__main__':main()
