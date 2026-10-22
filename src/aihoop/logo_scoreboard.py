"""Read a logo-only score strip with a clock below it, without guessing teams."""
import re
import cv2
from .frame_reader import FrameReader


def pair(text):
    text = str(text).strip()
    if ':' in text or re.search('[A-Za-z]', text):
        return None
    numbers = re.findall(r'\d+', text)
    if len(numbers) != 2 or any(len(n) > 3 for n in numbers):
        return None
    return tuple(map(int, numbers))


def locate(video, reader):
    cap = cv2.VideoCapture(str(video))
    width,height= int(cap.get(3)),int(cap.get(4))
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); proposals=[]
    try:
        for fraction in (.01,.25,.5,.75,.99):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(max(0,total-1)*fraction))
            ok,frame=cap.read()
            if not ok:continue
            top=int(height*.78)
            image=cv2.resize(frame[top:],None,fx=2,fy=2)
            words=reader.readtext(image,detail=1,paragraph=False)
            # Both a game-clock pattern and a period label provide context;
            # an isolated pair in a stand or advertisement cannot establish it.
            clocks=[w for w in words if re.fullmatch(r'\d{1,2}[:.]\d{1,2}',str(w[1]).strip()) and float(w[2])>=.5]
            periods=[w for w in words if re.search(r'quarter|qtr|\b[1-4](?:st|nd|rd|th)\b',str(w[1]),re.I)]
            if not clocks or not periods:continue
            candidates=list(words)
            digits=[w for w in words if re.fullmatch(r'\d{1,3}',str(w[1]).strip()) and float(w[2])>=.75]
            for a in digits:
                for b in digits:
                    ax=min(p[0] for p in a[0]);bx=min(p[0] for p in b[0])
                    ah=max(p[1] for p in a[0])-min(p[1] for p in a[0])
                    bh=max(p[1] for p in b[0])-min(p[1] for p in b[0])
                    if not 0<bx-ax<width*.4 or abs(min(p[1] for p in a[0])-min(p[1] for p in b[0]))>min(ah,bh)*.25:continue
                    if min(ah,bh)<max(ah,bh)*.65:continue
                    candidates.append((list(a[0])+list(b[0]),str(a[1])+' '+str(b[1]),min(a[2],b[2])))
            for polygon,text,conf in candidates:
                if float(conf)<.65 or pair(text) is None:continue
                xs=[float(p[0]) for p in polygon];ys=[float(p[1]) for p in polygon]
                x,y,X,Y=min(xs),min(ys),max(xs),max(ys)
                clock=clocks[0][0]
                if Y>=min(float(p[1]) for p in clock) or Y-y<16:continue
                if not any(abs((x+X)/2-sum(float(p[0]) for p in c[0])/len(c[0]))<width*.65 for c in clocks):continue
                proposals.append((x/2,y/2+top,(X-x)/2,(Y-y)/2,fraction))
    finally:cap.release()
    # Stable position in at least three independent video samples.
    for anchor in proposals:
        group=[p for p in proposals if abs(p[0]-anchor[0])<width*.015 and abs(p[1]-anchor[1])<height*.015
               and abs(p[2]-anchor[2])<width*.025]
        if len({p[4] for p in group})>=3:
            x=min(p[0] for p in group)-5;y=min(p[1] for p in group)-4
            X=max(p[0]+p[2] for p in group)+5;Y=max(p[1]+p[3] for p in group)+4
            return [max(0,int(x)),max(0,int(y)),int(X-x),int(Y-y)]
    raise ValueError('没有找到带计时和节次依据的稳定双比分区域')


def scan(video, reader, box, step=.5, max_seconds=0, diagnostic=False):
    cap=cv2.VideoCapture(str(video));fps=cap.get(cv2.CAP_PROP_FPS) or 30
    total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));frames=FrameReader(cap)
    x,y,w,h=box;readings=[];sampled=0;samples=[]
    try:
        for index in range(0,total,max(1,round(step*fps))):
            t=index/fps
            if max_seconds>0 and t>max_seconds:break
            ok,frame=frames.read(index)
            if not ok:break
            sampled+=1
            crop=cv2.resize(frame[y:y+h,x:x+w],None,fx=3,fy=3)
            words=reader.readtext(crop,detail=1,paragraph=False,allowlist='0123456789')
            words=sorted(words,key=lambda w:min(p[0] for p in w[0]))
            text=' '.join(str(w[1]) for w in words if float(w[2])>=.65)
            values=pair(text)
            confidence=min((float(w[2]) for w in words if float(w[2])>=.65),default=0.)
            # A slash or border between teams can merge the two OCR words.
            # Independently reread each half; this changes neither temporal nor
            # scoring thresholds and retains only measured, agreeing digits.
            if values is None or confidence<.9:
                halves=[]
                for image in (crop[:,:crop.shape[1]//2],crop[:,crop.shape[1]//2:]):
                    reads=reader.readtext(image,detail=1,paragraph=False,allowlist='0123456789')
                    digits=[(str(v).strip(),float(c)) for _,v,c in reads
                            if re.fullmatch(r'\d{1,3}',str(v).strip()) and float(c)>=.9]
                    if len(digits)!=1:break
                    halves.append(digits[0])
                if len(halves)==2:
                    measured=tuple(int(v) for v,c in halves)
                    if values is None or measured==values:
                        values=measured;confidence=min(c for v,c in halves)
                        text=' '.join(v for v,c in halves)
            if values is not None:
                readings.append({'t':round(t,3),'pair':values,'text':text,'confidence':confidence})
            if diagnostic:
                samples.append({'frame_id':index,'t':index/fps,
                    'raw_words':[{'text':str(v),'confidence':float(c),
                                  'polygon':[[float(x),float(y)] for x,y in polygon]}
                                 for polygon,v,c in words],
                    'accepted_pair':values,'confidence':confidence,
                    'reason':'parsed_pair' if values is not None else 'no_reliable_score_pair'})
    finally:cap.release()
    current=None;pending=None;pending_rows=[];events=[];confirmed=[];rejected=[];baseline=None;gaps=[]
    for row in readings:
        values=row['pair']
        if values!=pending or (pending_rows and row['t']-pending_rows[-1]['t']>max(1.,step*2)):
            pending=values;pending_rows=[]
        pending_rows.append(row)
        strong_pair=(len(pending_rows)>=2 and pending_rows[-1]['t']-pending_rows[0]['t']>=.45
                     and all(r.get('confidence',0)>=.9 for r in pending_rows))
        if len(pending_rows)<3 and not strong_pair:continue
        if current is None:
            current=values;baseline=values;confirmed.append(row);continue
        delta=[values[i]-current[i] for i in (0,1)]
        if values==current:confirmed.append(row);continue
        if sum(d>0 for d in delta)==1 and all(0<=d<=3 for d in delta):
            side=0 if delta[0] else 1
            events.append({'t':pending_rows[0]['t'],'screen_side':'left' if side==0 else 'right',
                           'delta':delta[side],'value':values[side]})
            current=values;confirmed.append(row)
        else:
            gaps.append({'t':pending_rows[0]['t'],'previous':current,'next':values,
                         'reason':'比分跨段变化，不能还原为单次投篮'})
            current=values;confirmed.append(row)
    usable=baseline is not None and len(readings)>=max(3,sampled*.5)
    if not usable and not diagnostic:
        raise ValueError('双比分连续读数不足，未采用本次结果')
    result={'method':'logo_score_strip','box':box,'team_mapping_confirmed':False,
            'screen_start':dict(zip(('left','right'),baseline)) if baseline is not None else None,
            'screen_final':dict(zip(('left','right'),current)) if current is not None else None,
            'screen_events':events,'discontinuities':gaps,'readings':readings,'rejected':rejected,
            'ocr_hit':len(readings),'n_crops':sampled,
            'note':'左右表示比分牌显示顺序，尚未确认与球衣分队的对应关系；不得直接加到主客队总分。'}
    if diagnostic:result.update(usable=usable,samples=samples)
    return result
