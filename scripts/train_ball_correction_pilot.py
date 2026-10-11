"""Small internal pilot, split by source video; never deploys its weights."""
import argparse,hashlib,json,shutil
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True);p.add_argument('--weights',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--train-samples',nargs='+',required=True);p.add_argument('--val-samples',nargs='+',required=True);p.add_argument('--epochs',type=int,default=30);p.add_argument('--device',default='0');a=p.parse_args()
 train,val=set(a.train_samples),set(a.val_samples)
 if train&val:raise ValueError('同一比赛不能同时用于训练和验证')
 if a.out.exists():raise ValueError('输出目录已存在，请选一个新目录，避免覆盖实验')
 from ultralytics import YOLO
 model=YOLO(str(a.weights));names=model.names;ball=[k for k,v in names.items() if 'ball' in str(v).lower()]
 if len(ball)!=1:raise ValueError('模型必须有且只有一个篮球类别')
 manifest=json.loads((a.batch/'manifest.json').read_text(encoding='utf-8'));records=[];counts={};hashes={'train':set(),'val':set()}
 if not (train | val) <= {v['id'] for v in manifest}:raise ValueError('指定的比赛不存在')
 for item in manifest:
  if item['id'] not in train|val:continue
  split='train' if item['id'] in train else 'val'
  path=a.batch/item['id']/'annotations.json';labels=json.loads(path.read_text(encoding='utf-8'))
  for frame in labels['frames']:
   if frame['visibility'] not in ('visible','not_visible'):continue
   image=path.parent/frame['image'];sha=hashlib.sha256(image.read_bytes()).hexdigest();hashes[split].add(sha);boxes=[b for b in frame['boxes'] if b['kind']=='ball']
   if frame['visibility']=='visible' and not boxes:raise ValueError('有球画面缺少框')
   records.append({'split':split,'sample':item['id'],'image':str(image),'sha256':sha,'boxes':boxes,'annotation_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
   counts.setdefault(split,{'images':0,'positive':0});counts[split]['images']+=1;counts[split]['positive']+=bool(boxes)
 if hashes['train']&hashes['val']:raise ValueError('训练和验证存在完全相同的画面')
 if any(not counts.get(s,{}).get('positive',0) for s in ('train','val')):raise ValueError('训练和验证都需要有球画面')
 a.out.mkdir(parents=True)
 for r in records:
  image=Path(r['image']);name=r['sample']+'_'+image.stem;dst=a.out/r['split'];(dst/'images').mkdir(parents=True,exist_ok=True);(dst/'labels').mkdir(exist_ok=True);shutil.copyfile(image,dst/'images'/f'{name}.jpg');lines=[]
  for b in r['boxes']:
   x1,y1,x2,y2=b['xyxy'];lines.append(f'{ball[0]} {(x1+x2)/2} {(y1+y2)/2} {x2-x1} {y2-y1}')
  (dst/'labels'/f'{name}.txt').write_text('\n'.join(lines))
 # Keep every original class: changing nc resets classification layers.
 yaml=f'path: {a.out.resolve().as_posix()}\ntrain: train/images\nval: val/images\nnames:\n'+''.join(f'  {k}: {json.dumps(v)}\n' for k,v in names.items());(a.out/'data.yaml').write_text(yaml,encoding='utf-8')
 (a.out/'split.json').write_text(json.dumps({'counts':counts,'records':records,'weights_sha256':hashlib.sha256(a.weights.read_bytes()).hexdigest(),'limitation':'Development pilot only; train sources must not subsequently be reported as held out.'},ensure_ascii=False,indent=2),encoding='utf-8')
 print(counts,flush=True)
 model.train(data=str(a.out/'data.yaml'),epochs=a.epochs,imgsz=640,batch=4,device=a.device,workers=0,freeze=10,lr0=.0001,optimizer='AdamW',patience=10,amp=False,plots=False,seed=42,project=str(a.out),name='train',exist_ok=False,verbose=False,mosaic=0,fliplr=0,translate=.05,scale=.1)
if __name__=='__main__':main()
