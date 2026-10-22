"""Local jersey digit OCR. Track IDs remain keys; numbers need temporal agreement."""
import json,re,shutil,subprocess,tempfile,os,hashlib
from pathlib import Path
from collections import defaultdict,Counter
import cv2
import math

def select_observations(items, limit=12):
    """Retain the old five large-box samples, then cover other parts of the track."""
    picked=[]
    def add(o):
        if all(abs(float(o['t'])-float(p['t']))>=.25 for p in picked):
            picked.append(o)
    for o in sorted(items,key=lambda o:-(o['box'][3]-o['box'][1])):
        add(o)
        if len(picked)>=min(5,limit):break
    remaining=sorted(items,key=lambda o:float(o['t']))
    while len(picked)<limit:
        eligible=[o for o in remaining if all(abs(float(o['t'])-float(p['t']))>=.25 for p in picked)]
        if not eligible:break
        # Farthest-time sampling avoids spending all reads on one close-up.
        add(max(eligible,key=lambda o:min(abs(float(o['t'])-float(p['t'])) for p in picked)))
    return picked

def torso_bounds(observation, width, height):
    """Use reliable COCO shoulders/hips when supplied, otherwise the box crop.

    This does not start a pose model or infer visibility from pose confidence.
    """
    x,y,X,Y=map(float,observation['box']);w=X-x;h=Y-y
    bounds=(x+.18*w,y+.20*h,X-.18*w,y+.68*h);source='box_torso'
    kp=observation.get('keypoints')
    if isinstance(kp,(list,tuple)) and len(kp)>=17:
        try:
            pts=[kp[i] for i in (5,6,11,12)]
            if all(len(p)>=3 and float(p[2])>=.5 and all(math.isfinite(float(z)) for z in p[:3]) for p in pts):
                xs=[float(p[0]) for p in pts];ys=[float(p[1]) for p in pts]
                a,b,c,d=min(xs),min(ys),max(xs),max(ys)
                if .15*w<c-a<=w and .15*h<d-b<=.7*h and x<=a<c<=X and y<=b<d<=Y:
                    bounds=(a-.12*w,b-.04*h,c+.12*w,d+.04*h);source='pose_torso'
        except (TypeError,ValueError,IndexError):pass
    a,b,c,d=bounds
    return (max(0,int(a)),max(0,int(b)),min(width,int(c)),min(height,int(d))),source

def crop_quality(crop):
    """Rank native crops; only reject empty/tiny or virtually uniform images.

    Sharpness is NOT a trained number-legibility classifier. Text recognition
    and temporal agreement are still required before assigning a number.
    """
    if crop is None or not crop.size or min(crop.shape[:2])<12:
        return {'usable':False,'reason':'crop_too_small','score':0.0}
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    contrast=float(gray.std());sharpness=float(cv2.Laplacian(gray,cv2.CV_64F).var())
    return {'usable':contrast>=2.0,'reason':None if contrast>=2.0 else 'uniform_crop',
            'contrast':round(contrast,3),'sharpness':round(sharpness,3),
            'score':round(math.log1p(sharpness)*math.log1p(contrast),4)}

def number_from_words(words,width,height):
    found=[]
    for w in words or []:
        text=str(w.get('text','')).strip()
        if not re.fullmatch(r'[0-9]{1,2}',text):continue
        x,y,bw,bh=(float(w.get(k,0)) for k in ('x','y','w','h'))
        if height*.12<=bh<=height*.9 and width*.06<=bw<=width*.9 and .1*width< x+bw/2 <.9*width:
            found.append(text)
    return found[0] if len(found)==1 else None

def consensus(readings):
    # Independent times, not repeated OCR variants of one image.
    by_time=defaultdict(list)
    for r in readings:
        if r.get('number') is not None:by_time[round(float(r['t']),3)].append(r)
    # Conflicting crops at one time must never become an arbitrary vote.
    unique={t:rs[0] for t,rs in by_time.items() if len({r['number'] for r in rs})==1}
    votes=Counter(r['number'] for r in unique.values())
    if not votes:return None
    number,count=votes.most_common(1)[0]
    ts=[r['t'] for r in unique.values() if r['number']==number]
    if count<3 or count/len(unique)<.8 or max(ts)-min(ts)<.5:return None
    return {'number':number,'observations':count,'agreement':count/len(unique),'source':'jersey_ocr_multiframe'}

def model_path():
    """Only use provisioned local OCR weights; never download during analysis."""
    value=os.environ.get('AIHOOP_JERSEY_MODEL')
    if value is not None and value.lower() in ('off','none',''):return None
    from .ocr_assets import ocr_model_directory
    path=ocr_model_directory(env_name='AIHOOP_JERSEY_MODEL')
    return path if all((path/n).is_file() for n in ('craft_mlt_25k.pth','english_g2.pth')) else None


def model_read(folder,records,path,device):
    import easyocr
    if device is None:
        import torch
        gpu=bool(torch.cuda.is_available())
    else:
        gpu=False if str(device).lower()=='cpu' else ('cuda:'+str(device) if str(device).isdigit() else str(device))
    reader=easyocr.Reader(['en'],gpu=gpu,model_storage_directory=str(path),download_enabled=False,verbose=False)
    rows=[]
    for name in records:
        words=[]
        # Keep the full alphabet: forcing digits can turn team text into numbers.
        for polygon,text,confidence in reader.readtext(str(folder/name),detail=1,paragraph=False):
            if float(confidence)<.7:continue
            xs=[float(p[0]) for p in polygon];ys=[float(p[1]) for p in polygon]
            words.append({'text':str(text),'x':min(xs),'y':min(ys),'w':max(xs)-min(xs),'h':max(ys)-min(ys),'confidence':float(confidence)})
        rows.append({'file':name,'words':words})
    return rows

def recognize(video, observations, players, max_tracks=120, max_crops=600, cuts=(), device=None):
    ps=shutil.which('powershell.exe') or shutil.which('powershell')
    script=Path(__file__).resolve().parents[2]/'scripts/ocr_images.ps1'
    dedicated=model_path()
    if dedicated is None and (not ps or not script.exists()):return {'available':False,'reason':'本机球衣号码识别不可用','per_player':{}}
    grouped=defaultdict(list)
    for o in observations:
        b=o.get('box')
        if b and len(b)==4 and b[3]-b[1]>=90 and b[2]-b[0]>=30:grouped[str(o['player_id'])].append(o)
    # A detector track spanning a cut is not sufficient identity evidence.
    grouped={pid:items for pid,items in grouped.items() if not any(min(o['t'] for o in items)<t<=max(o['t'] for o in items) for t in cuts)}
    ranked=sorted(grouped,key=lambda p: max(o['box'][3]-o['box'][1] for o in grouped[p]),reverse=True)[:max_tracks]
    selections={}
    for pid in ranked:
        picked=select_observations(grouped[pid])
        if len(picked)>=3:selections[pid]=picked
    # Allocate complete three-frame groups first, then round-robin extras.
    chosen=[];active=list(selections)[:max(0,max_crops//3)]
    for pid in active:chosen.extend(selections[pid][:3])
    for offset in range(3,12):
        for pid in active:
            if len(chosen)>=max_crops:break
            if len(selections[pid])>offset:chosen.append(selections[pid][offset])
    chosen=sorted(chosen,key=lambda o:o['t']);cap=cv2.VideoCapture(str(video));records={};last_index=-1;image=None
    quality_rejections=Counter();sample_audit=defaultdict(list)
    try:
      with tempfile.TemporaryDirectory(prefix='aihoop_jersey_') as folder:
        folder=Path(folder)
        for i,o in enumerate(chosen):
            index=round(o['t']*(cap.get(cv2.CAP_PROP_FPS) or 30))
            if index!=last_index:
                # Sorted samples: avoid seeking/redecoding the same GOP for
                # every torso crop. A distant gap can still use a seek.
                if index-last_index > 120 or index<last_index:
                    cap.set(cv2.CAP_PROP_POS_FRAMES,index)
                else:
                    for _ in range(max(0,index-last_index-1)):
                        if not cap.grab(): break
                ok,image=cap.read();last_index=index
                if not ok:image=None
            if image is None:continue
            ih,iw=image.shape[:2]
            (a,b,c,d),crop_source=torso_bounds(o,iw,ih)
            crop=image[b:d,a:c]
            quality=crop_quality(crop);pid=str(o['player_id'])
            sample_audit[pid].append({'t':o['t'],'crop_source':crop_source,'quality':quality})
            if not quality['usable']:
                quality_rejections[quality['reason']]+=1;continue
            scale=min(4.,max(1.,180/crop.shape[0]));crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
            name=f'jersey_{i:05d}.png';cv2.imwrite(str(folder/name),crop)
            records[name]={'player_id':pid,'t':o['t'],'box':o['box'],'width':crop.shape[1],'height':crop.shape[0],
                           'crop_box':[a,b,c,d],'crop_source':crop_source,'quality':quality}
        # Keep the five old sample times when usable, plus up to three best
        # additional crops. New sampling cannot evict old independent evidence.
        keep=set()
        for pid in active:
            names=[n for n,r in records.items() if r['player_id']==pid]
            original_times={o['t'] for o in selections[pid][:5]}
            old=[n for n in names if records[n]['t'] in original_times]
            extra=sorted([n for n in names if n not in old],key=lambda n:-records[n]['quality']['score'])
            keep.update(old+extra[:max(0,8-len(old))])
        for name in list(records):
            if name not in keep:
                (folder/name).unlink();del records[name]
        if not records:return {'available':True,'sampled_crops':0,'per_player':{},'quality_rejections':dict(quality_rejections),'sample_audit':dict(sample_audit),'reason':'没有可用的多帧球衣画面'}
        if dedicated is not None:
            rows=model_read(folder,records,dedicated,device)
        else:
            out=folder/'result.json'
            result=subprocess.run([ps,'-NoProfile','-File',str(script),'-ImageDir',str(folder),'-Pattern','jersey_*.png','-OutJson',str(out)],capture_output=True,timeout=300)
            if result.returncode or not out.exists():return {'available':False,'reason':'球衣号码 OCR 读取失败','per_player':{}}
            rows=json.loads(out.read_text(encoding='utf-8-sig'));rows=[rows] if isinstance(rows,dict) else rows
        readings=defaultdict(list)
        for row in rows:
            r=records.get(row.get('file'))
            if r:
                r=dict(r,number=number_from_words(row.get('words'),r['width'],r['height']),words=row.get('words',[]));readings[r['player_id']].append(r)
        per_player={}
        for pid,items in readings.items():
            got=consensus(items)
            per_player[pid]={'confirmed':bool(got),'readings':items,'observed_crops':len(items),
                             'number_reads':sum(r['number'] is not None for r in items),
                             'reason':None if got else ('number_unreadable' if not any(r['number'] is not None for r in items) else 'insufficient_temporal_agreement'),**(got or {})}
            if got and pid in players:
                p=players[pid];number=got['number'];p.jersey=number if number=='00' else int(number)
                if p.name in (p.player_id,'号码待确认'):p.name=number+'号'
        return {'available':True,'reader':'easyocr' if dedicated else 'windows_ocr', 'model_sha256':{n:hashlib.sha256((dedicated/n).read_bytes()).hexdigest() for n in ('craft_mlt_25k.pth','english_g2.pth')} if dedicated else None,'sampled_crops':len(records),'confirmed_tracks':sum(x['confirmed'] for x in per_player.values()),
                'sampling_version':2,'quality_rejections':dict(quality_rejections),'sample_audit':dict(sample_audit),
                'per_player':per_player,'note':'最多八个不同时间画面；号码须至少三帧一致；清晰度仅用于选帧，不代表号码可读；不跨镜头自动合并球员身份。'}
    except (subprocess.TimeoutExpired,OSError,ValueError,RuntimeError,ImportError) as e:
        return {'available':False,'reason':f'球衣号码识别未完成：{type(e).__name__}','per_player':{}}
    finally:cap.release()
