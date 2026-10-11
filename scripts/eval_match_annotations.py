"""Current automatic engine versus frozen human event labels; no corrections."""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
from aihoop.highlight import ffmpeg_path
from aihoop.sources import VideoSource
from aihoop.court import Calibration

def match_times(truth,pred,tolerance=1.5):
    """Maximum chronological one-to-one matches, then minimum total time error."""
    t=sorted(enumerate(truth),key=lambda x:x[1]);p=sorted(enumerate(pred),key=lambda x:x[1])
    @lru_cache(None)
    def solve(i,j):
        if i==len(t) or j==len(p):return (0,0.,())
        choices=[solve(i+1,j),solve(i,j+1)]
        error=abs(t[i][1]-p[j][1])
        if error<=tolerance:
            count,cost,pairs=solve(i+1,j+1)
            choices.append((count+1,cost+error,((t[i][0],p[j][0],error),)+pairs))
        return max(choices,key=lambda a:(a[0],-a[1]))
    return list(solve(0,0)[2])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--truth',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--device',default='0')
    # 默认**关**球员检测（原速度优先配置）；加 --players 就按产品默认
    # （VideoSource.detect_players=True、player_stride=2）跑一遍。
    # 为什么要这个开关：离手时刻 release_t 的估算要回溯"谁在持球"（scorer._bind_shooter），
    # 没有球员检测时它只能退化成"球飞到篮筐附近的那一刻"，会**系统性偏晚**（实测中位数 +0.78s）。
    ap.add_argument('--players',action='store_true',
                    help='开球员检测（产品默认配置），用于对比离手时刻的估算')
    # 球"丢了再找回来"（legacy_shots.settings.LegacyDetectOptions.ball_roi_recovery，默认 False）。
    # 为什么要有这个开关：逐帧诊断发现两次真漏检都是球检测的问题 ——
    # 一次是检测框钉在静止误检上（真球从没靠近篮筐）、一次是该段完全没有球检测。
    ap.add_argument('--ball-recovery',action='store_true',
                    help='开球 ROI 恢复（球丢失后再找回来）')
    # 推理分辨率：逐帧诊断发现两次真漏检那一段里，球**压根没被检测到**（原始候选经常是 0~1 个），
    # 而裁判"中/不中"要用球相对筐口的观测，所以感知这一层是瓶颈。产品里 standard=640 / night=960。
    ap.add_argument('--imgsz',type=int,default=None,choices=[320,448,640,768,960,1280],
                    help='检测推理分辨率（默认 640）')
    # 筐周围高分辨率复检（第五轮）：诊断显示两次真漏检是"球没被看见"，
    # 而出手必须在筐附近被看见 —— 所以把复检窗口开在筐上（详见 ball_recovery.recover_rim）。
    ap.add_argument('--rim-recovery',action='store_true',
                    help='开「筐周围高分辨率复检球」')
    # 静止锁换锚（第四轮实现，默认关）：连续 N 秒几乎不动就允许换一次锚。
    # 单独跑它没用（实测），但和 --rim-recovery 组合才有意义：
    # 复检**提供**筐附近的真球候选，换锚**让**它顶掉那条锁在静止物上的轨迹。
    ap.add_argument('--static-lock-s',type=float,default=0.,
                    help='静止锁换锚阈值秒数（0=关；建议 1.0 与 --rim-recovery 一起用）')
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];raw_truth=args.truth.read_bytes();truth=json.loads(raw_truth)
    args.out.mkdir(parents=True,exist_ok=True);rows=[]
    for sample in truth['samples']:
        folder=args.out/sample['id'];folder.mkdir(exist_ok=True)
        clip=folder/'evaluation_segment.mp4'
        # Re-encode to get an exact 60s interval rather than GOP-dependent copy.
        subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-ss',str(sample['start_s']),
            '-i',sample['video'],'-t',str(sample['end_s']-sample['start_s']),'-an','-c:v','libx264',
            '-preset','ultrafast','-crf','18',str(clip)],check=True)
        src=VideoSource(str(clip),Calibration(method='unavailable'),detect_players=bool(args.players),scoreboard=False,
            auto_sliding=False,device=args.device,ball_weights=str(root/'runs/detect/ball/weights/best.pt'),
            hoop_weights=str(root/'runs/detect/rim/weights/best.pt'),
            legacy_detect={'ball_roi_recovery':bool(args.ball_recovery),'ball_rim_recovery':bool(args.rim_recovery),
                           'ball_static_lock_s':float(args.static_lock_s or 0.),
                           **({'imgsz':args.imgsz} if args.imgsz else {})})
        raw=src.run();raw.save(folder/'raw_track.json')
        events=raw.detections_meta['legacy_shots']['events']
        predicted=[dict(release_s=e.get('release_t',e['t'])+sample['start_s'],result=e['result'],
                        decision_s=e['t']+sample['start_s'],crossing_s=(e['crossing_t']+sample['start_s']) if e.get('crossing_t') is not None else None,
                        evidence=e.get('evidence'),points=e.get('points'),points_verified=e.get('points_verified')) for e in events]
        actual=sample['shots'];pairs=match_times([x['release_s'] for x in actual],[x['release_s'] for x in predicted])
        row=dict(id=sample['id'],truth_shots=len(actual),engine_events=len(predicted),confirmed_made=sum(e['result']=='made' for e in predicted),
            matched=len(pairs),missed=len(actual)-len(pairs),extra=len(predicted)-len(pairs),
            matched_result_correct=sum(actual[i]['result']==predicted[j]['result'] for i,j,_ in pairs),
            pairs=[dict(truth_index=i,event_index=j,delta_s=dt) for i,j,dt in pairs],truth=actual,events=predicted)
        rows.append(row)
        print(json.dumps({k:row[k] for k in ('id','truth_shots','engine_events','confirmed_made','matched','missed','extra')},ensure_ascii=False),flush=True)
        (args.out/'results.json').write_text(json.dumps(dict(truth_sha256=hashlib.sha256(raw_truth).hexdigest(),tolerance_s=1.5,
            parameters=dict(detect_players=bool(args.players),scoreboard=False,auto_sliding=False,profile='standard',roi=False,ball_roi_recovery=bool(args.ball_recovery),ball_rim_recovery=bool(args.rim_recovery),imgsz=args.imgsz or 640),
            limits=['时段被精确重编码为CRF18，检测可能与原片有轻微差异','全自动结果，无人工回填','无球员检测，未评测出手人关联','不根据此结果自动改参数'],samples=rows),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
