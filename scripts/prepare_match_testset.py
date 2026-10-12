"""Prepare unlabelled match evaluation material, never manufacture truth.

These are proposed evaluation clips. Prior use must be checked before calling
them an independent holdout. No reviewed sample outputs are used as labels.
"""
import argparse
import csv
import json
from pathlib import Path
import cv2

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--samples',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True)
 args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 names=['01_nba_2025finals_okc_vs_indiana_4min.mp4',
        '06_acb_spain_realmadrid_vs_baskonia_4min.mp4',
        '07_wnba_game_4min.mp4','08_ncaa_kansas_vs_northcarolina_4min.mp4']
 manifest=[]
 for n,name in enumerate(names,1):
  video=args.samples/'proleagues'/name
  if not video.exists():continue
  cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS)
  duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps if fps else 0
  start=30.;end=min(90.,duration)
  if end<=start:cap.release();continue
  sid=f'match_{n:02d}';folder=args.out/sid;folder.mkdir(exist_ok=True)
  for i in range(8):
   t=start+(end-start)*i/8
   cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read()
   if ok:cv2.imwrite(str(folder/f'frame_{t:07.2f}.jpg'),frame)
  cap.release()
  for filename,fields in [
   ('shots_truth.csv',['event_id','release_s','rim_s','result','value','is_replay','play_id','note']),
   ('ball_truth.csv',['frame_s','visibility','x1','y1','x2','y2','decoy_x1','decoy_y1','decoy_x2','decoy_y2','note'])]:
   target=folder/filename
   if not target.exists():
    with target.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerow(fields)
  manifest.append(dict(id=sid,video=str(video),start_s=start,end_s=end,
    annotation_status='pending_human',prior_use_status='unverified',split='proposed_holdout',
    license_status='unverified_do_not_redistribute',preview_frames=8))
 (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 (args.out/'README.md').write_text('''# 比赛测试集待标注包

四段各约60秒，原片时间30–90秒；所有标注时间均用原片秒数。
当前不是已完成的独立测试集：先确认未用于调参，再锁定测试用途。
只包含本机路径与核对帧；素材授权待核，不随项目发布。

## 需要人工填写
逐段完整观看：shots_truth.csv每次实际出手一行，罚球单列value=1；
结果made/missed/unknown；重复回放标is_replay并填写相同play_id。
球框表按给出的帧时刻填写：可见球的像素框；看不清写unclear，
不可见写not_visible，不能用检测器漏检推断球不可见。
队标等干扰物可填decoy框。空表不作为零出手或零篮球的真值。

## 验收
出手用时间容差内一对一匹配，报告精确率/召回率/F1；
命中正确性和未知率分别报告；球检测单列漏检与干扰物误检。
测试标签锁定后禁止按测试结果反复调参；不比较A版。
''',encoding='utf-8')
 print(json.dumps({'clips':len(manifest),'seconds':sum(x['end_s']-x['start_s'] for x in manifest),'status':'pending_human'},ensure_ascii=False))

if __name__=='__main__':main()
