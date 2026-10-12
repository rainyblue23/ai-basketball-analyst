"""Evaluate frozen human box annotations without changing model or thresholds."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import cv2
from ultralytics import YOLO

def overlap(a,b):
    w=max(0,min(a[2],b[2])-max(a[0],b[0]));h=max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=w*h;union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union>0 else 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--device',default='0');args=p.parse_args()
    manifest=json.loads((args.batch/'manifest.json').read_text(encoding='utf-8'))
    model=YOLO(str(args.weights));rows=[];snapshots={}
    for item in manifest:
        path=args.batch/item['id']/'annotations.json'
        if not path.exists():continue
        source=path.read_bytes();labels=json.loads(source);snapshots[item['id']]=dict(sha256=hashlib.sha256(source).hexdigest(),annotations=labels)
        for annotation in labels['frames']:
            if annotation['visibility']=='pending':continue
            image=cv2.imread(str(path.parent/annotation['image']))
            if image is None:raise RuntimeError(f"无法读取核对帧: {annotation['image']}")
            h,w=image.shape[:2]
            truth=[[v*(w if i%2==0 else h) for i,v in enumerate(b['xyxy'])] for b in annotation['boxes'] if b['kind']=='ball']
            scales={}
            for size in (640,960):
                result=model.predict(image,imgsz=size,conf=.25,iou=.5,device=args.device,verbose=False)[0]
                detections=[]
                for b in result.boxes:
                    if 'ball' not in str(result.names.get(int(b.cls[0]),'')).lower():continue
                    detections.append(dict(box=[float(x) for x in b.xyxy[0]],conf=float(b.conf[0])))
                scales[str(size)]=detections
            row=dict(sample=item['id'],image=annotation['image'],visibility=annotation['visibility'],truth=truth,scales=scales,metrics={})
            for scale,preds in [*scales.items(),('union',scales['640']+scales['960'])]:
                # The union is diagnostic only: duplicates are NOT precision counts.
                ious=[max((overlap(gt,p['box']) for p in preds),default=0.) for gt in truth]
                center_hits=sum(any(gt[0]<=(p['box'][0]+p['box'][2])/2<=gt[2] and gt[1]<=(p['box'][1]+p['box'][3])/2<=gt[3] for p in preds) for gt in truth)
                row['metrics'][scale]=dict(truth_boxes=len(truth),matched_iou50=sum(i>=.5 for i in ious),matched_iou30=sum(i>=.3 for i in ious),center_in_annotation=center_hits,best_ious=ious,detections=len(preds))
            rows.append(row);print(item['id'],annotation['image'],annotation['visibility'],{k:v['center_in_annotation'] for k,v in row['metrics'].items()},flush=True)
    summary={};visibility=dict(Counter(r['visibility'] for r in rows))
    for scale in ('640','960','union'):
        visible=[r for r in rows if r['visibility']=='visible'];negative=[r for r in rows if r['visibility']=='not_visible']
        summary[scale]=dict(truth_boxes=sum(r['metrics'][scale]['truth_boxes'] for r in visible),
            matched_iou50=sum(r['metrics'][scale]['matched_iou50'] for r in visible),
            matched_iou30=sum(r['metrics'][scale]['matched_iou30'] for r in visible),
            center_in_annotation=sum(r['metrics'][scale]['center_in_annotation'] for r in visible),
            not_visible_frames=len(negative),not_visible_frames_with_detections=sum(r['metrics'][scale]['detections']>0 for r in negative))
    report=dict(weights=str(args.weights),weights_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),conf=.25,nms_iou=.5,
        visibility=visibility,summary=summary,annotation_snapshots=snapshots,rows=rows,
        limits=['仅32张稀疏核对帧，不代表整段视频准确率','看不清帧不计入检出或负例分母','中心落框是宽松定位检查，不等于IoU匹配','union是多尺度并集诊断，非现有级联时序策略','无队标真值框，不能计算队标专项误检率','prior_use尚未核实，不能宣称独立测试集'])
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(visibility=visibility,summary=summary),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
