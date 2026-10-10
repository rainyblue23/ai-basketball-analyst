"""Reject recurring screen graphics by fixed position AND current appearance.
No blanket corner mask: a live ball at the same position remains eligible.
"""
import math
import cv2
import numpy as np

def patch(frame, box):
    h,w=frame.shape[:2];x1,y1,x2,y2=[int(round(x)) for x in box]
    x1,y1,x2,y2=max(0,x1),max(0,y1),min(w,x2),min(h,y2)
    if x2-x1<4 or y2-y1<4:return None
    return cv2.resize(cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY),(24,24)).astype(np.float32)

def similar(a,b,mask=None):
    if a is None or b is None:return False
    if mask is not None:
        mask=np.asarray(mask,dtype=bool)
        if mask.shape!=a.shape or np.count_nonzero(mask)<.2*a.size:return False
        a=a[mask];b=b[mask]
    if np.std(a)<8 or np.std(b)<8:return False
    corr=np.corrcoef(a.ravel(),b.ravel())[0,1]
    if np.mean(np.abs(a-b))<=12 and corr>=.92:return True
    # Broadcast fades change brightness but preserve the logo's internal pattern.
    # Require stronger correlation; position alone still cannot reject a ball.
    normalized=np.mean(np.abs((a-a.mean())/a.std()-(b-b.mean())/b.std()))
    return bool(corr>=.97 and normalized<=.25)

def learn(samples, width, height):
    """samples=(time, image, ball boxes). Position alone never establishes a mask."""
    clusters=[]
    for t,image,boxes in samples:
        for box in boxes:
            x1,y1,x2,y2=box;cx=(x1+x2)/2;cy=(y1+y2)/2
            if not (cy>.8*height or cy<.2*height) or not 6<=x2-x1<=.12*width:continue
            group=next((g for g in clusters if math.hypot(cx-g['cx'],cy-g['cy'])<=max(6,(x2-x1)*.2)),None)
            if group is None:
                group={'cx':cx,'cy':cy,'box':list(box),'items':[]};clusters.append(group)
            p=patch(image,group['box'])
            # Scene evidence retained only as a thumbnail, not the whole video.
            scene=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(48,27)).astype(float)
            group['items'].append((t,p,scene))
    graphics=[]
    for g in clusters:
        items=[r for r in g['items'] if r[1] is not None]
        if len(items)<3:continue
        stack=np.asarray([r[1] for r in items]);template=np.median(stack,axis=0)
        # Transparent scoreboard surroundings change with play; only recurrent
        # textured pixels can establish fixed appearance. No coordinate-only mask.
        spread=np.percentile(stack,90,axis=0)-np.percentile(stack,10,axis=0)
        stable=spread<=24
        support=[r for r in items if similar(r[1],template,stable)]
        if len(support)<3 or max(r[0] for r in support)-min(r[0] for r in support)<8:continue
        if max(np.mean(np.abs(r[2]-support[0][2])) for r in support)<12:continue
        graphics.append({'box':g['box'],'template':template.round().astype(int).tolist(),'stable_mask':stable.astype(int).tolist(),
                         'support':len(support),'span_s':round(max(r[0] for r in support)-min(r[0] for r in support),3),
                         'reason':'screen_fixed_appearance'})
    return graphics[:8]

def matches(frame, box, graphics):
    if frame is None:return False
    cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
    for g in graphics or []:
        x1,y1,x2,y2=g['box']
        if x1-4<=cx<=x2+4 and y1-4<=cy<=y2+4 and similar(patch(frame,g['box']),np.asarray(g['template'],dtype=float),g.get('stable_mask')):
            return True
    return False

def probe(video, model, options, count=24):
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS) or 30
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));width=int(cap.get(3));height=int(cap.get(4));samples=[]
    try:
        for index in np.linspace(0,max(0,total-1),count).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(index));ok,image=cap.read()
            if not ok:continue
            result=model.predict(image,**options)[0];boxes=[]
            for b in result.boxes if result.boxes is not None else []:
                if 'ball' in str(result.names.get(int(b.cls[0]),'')).lower():boxes.append([float(x) for x in b.xyxy[0]])
            samples.append((index/fps,image,boxes))
        return {'sampled_frames':len(samples),'graphics':learn(samples,width,height), 'inference':{k:options[k] for k in ('imgsz','conf','iou') if k in options}}
    finally:cap.release()
