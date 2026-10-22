"""Bounded, optional crop inference. Only actual detector boxes are returned."""
import math
import cv2
import numpy as np
from .legacy_shots.detector import Det


def cpu_boxes(result):
    """Transfer the compact box tensor once, avoiding a CUDA sync per scalar."""
    boxes = result.boxes
    if boxes is not None and hasattr(boxes, 'cpu'):
        result.boxes = boxes.cpu()
    return result.boxes if result.boxes is not None else []


def measured_detections(result, offset=(0,0), balls_only=False, source="full_frame", region=None):
    rows=[]
    for box in cpu_boxes(result):
        name=str(result.names.get(int(box.cls[0]),''))
        if balls_only and 'ball' not in name.lower():continue
        xyxy=[float(v)+offset[i%2] for i,v in enumerate(box.xyxy[0])]
        rows.append(Det(name,float(box.conf[0]),tuple(xyxy),source=source,region=region))
    return rows


def deduplicate_candidates(detections, iou=.5):
    """One measured ball box per overlapping object, retaining all source names.

    Separate model scales/ROIs at one timestamp are not temporal votes. Never
    merge rim or motion candidates into a measured ball or inflate confidence.
    """
    from dataclasses import replace
    remaining=[];balls=[]
    for index,det in enumerate(detections):
        if det.is_measurement and 'ball' in det.cls_name.lower():balls.append((index,det))
        else:remaining.append(det)
    kept=[];positions=[]
    for position,det in sorted(balls,key=lambda item:item[1].conf,reverse=True):
        duplicate=None
        for index,old in enumerate(kept):
            intersection=max(0,min(old.xyxy[2],det.xyxy[2])-max(old.xyxy[0],det.xyxy[0])) * max(0,min(old.xyxy[3],det.xyxy[3])-max(old.xyxy[1],det.xyxy[1]))
            union=old.area+det.area-intersection
            if union>0 and intersection/union>=iou:
                duplicate=index;break
        if duplicate is None:
            kept.append(det);positions.append(position)
        else:
            old=kept[duplicate]
            kept[duplicate]=replace(old,support_sources=tuple(dict.fromkeys((old.source,*old.support_sources,det.source,*det.support_sources))))
            positions[duplicate]=min(positions[duplicate],position)
    return [*remaining,*(det for _,det in sorted(zip(positions,kept),key=lambda pair:pair[0]))]


def unconfirmed_crop_boundary(det, width, height, margin=2.):
    """A crop-clipped box needs full-frame corroboration before seeding a track.

    A crop boundary inside the image can truncate an unrelated larger object.
    Keep the detector box in the audit; do not confuse this with a screen edge
    or with full-frame boxes corroborated by IoU during candidate fusion.
    """
    if det.source not in ('ball_roi','rim_roi') or det.region is None:return False
    if {'full_frame','multiscale'} & set(det.support_sources):return False
    x1,y1,x2,y2=det.region;bx1,by1,bx2,by2=det.xyxy
    return ((x1>0 and bx1-x1<=margin) or (y1>0 and by1-y1<=margin)
            or (x2<width and x2-bx2<=margin)
            or (height is not None and y2<height and y2-by2<=margin))


def recovery_region(stream, frame, width, height):
    old=stream.last_ball;delta=frame-stream.last_frame
    if old is None or delta<=0 or delta>max(1,int(stream.fps*stream.config['score']['ball_recent_s'])):
        return None
    horizon=min(delta,max(1,stream.config['score']['ball_max_gap_frames']))
    cx=old.cx+stream.vx*horizon;cy=old.cy+stream.vy*horizon
    if not 0<=cx<width or not 0<=cy<height:return None
    radius=min(384,max(96,4*max(old.w,old.h),
                       stream.config['detect']['ball_jump_px_per_frame']*math.sqrt(delta)))
    return [max(0,int(cx-radius)),max(0,int(cy-radius)),
            min(width,int(cx+radius)),min(height,int(cy+radius))]


def recover_region(model,image,options,stream,frame):
    h,w=image.shape[:2];region=recovery_region(stream,frame,w,h)
    audit=dict(ran=False,reason='no_recent_track',region_px=region,candidates=[])
    if region is None:return [],audit
    x1,y1,x2,y2=region
    size=stream.config['detect'].get('ball_roi_imgsz',640)
    result=model.predict(image[y1:y2,x1:x2],**dict(options,imgsz=size))[0]
    detections=measured_detections(result,(x1,y1),balls_only=True,source="ball_roi",region=tuple(region))
    # Map each measured crop box back to the ORIGINAL frame exactly once.
    detections=[d for d in detections if x1<=d.xyxy[0]<d.xyxy[2]<=x2 and y1<=d.xyxy[1]<d.xyxy[3]<=y2]
    audit.update(ran=True,reason='measured_crop_retry',imgsz=size,
                 candidates=[d.as_dict() for d in detections])
    return detections,audit


def rim_recovery_region(stream, frame, width, height):
    """以**被跟踪的篮筐**为中心的复检窗口（而不是"球的预测位置"）。

    为什么要换中心（第五轮）：
      * 球被锁在一个静止误检上时（实测转播段 23% 的帧），"预测位置"就是那个假目标的位置，
        真球在 1000+ px 外的筐附近 —— ROI 开在假目标上等于白开（这正是 ball_roi_recovery
        开了反而更差的原因之一）。
      * 而出乎**必须**在筐附近被看见：scorer 建立一次出手的条件就是"球被真实观测到、
        且高于筐心、且距筐心水平距离 < approach_radius_ratio × 筐宽"。
        既然"必须有观测"的地方是筐周围，补观测就该补在那里。
    半径取 approach_radius_ratio × 筐宽（默认 5×），与建立出手的门限同源。
    """
    rim=getattr(stream.engine,'rim',None)
    t=frame/max(stream.fps,1.)
    bounded_prediction=bool(rim is not None and getattr(rim,'dynamic_enabled',False)
                            and rim.status(t,stream.engine.rim_stale_s)=='PREDICTED')
    if (rim is None or not getattr(rim,'initialized',False)
            or not (rim.fresh(t,stream.engine.rim_stale_s) or bounded_prediction)):
        return None
    ratio=float(stream.config['score'].get('approach_radius_ratio',5.))
    radius=min(float(max(width,height)),max(96.,ratio*max(1.,float(rim.w))))
    cx,cy=float(rim.cx),float(rim.cy)
    x1=int(max(0,cx-radius));y1=int(max(0,cy-radius))
    x2=int(min(width,cx+radius));y2=int(min(height,cy+radius))
    if x2-x1<32 or y2-y1<32:return None
    return [x1,y1,x2,y2]


def recover_rim(model,image,options,stream,frame):
    """在筐周围的小窗口里**高分辨率**重检一次球。

    窗口比整帧小得多（约 1000px 见方 vs 1920 宽），同样的 imgsz=960 下
    等效放大倍数高得多 —— 针对的正是"球小 + 运动模糊"这个具体成因
    （全图提到 960 已经实测无效、还会变差）。
    """
    h,w=image.shape[:2];region=rim_recovery_region(stream,frame,w,h)
    audit=dict(ran=False,reason='no_rim',region_px=region,candidates=[])
    if region is None:return [],audit
    x1,y1,x2,y2=region
    size=stream.config['detect'].get('ball_rim_roi_imgsz',960)
    result=model.predict(image[y1:y2,x1:x2],**dict(options,imgsz=size))[0]
    detections=measured_detections(result,(x1,y1),balls_only=True,source="rim_roi",region=tuple(region))
    detections=[d for d in detections if x1<=d.xyxy[0]<d.xyxy[2]<=x2 and y1<=d.xyxy[1]<d.xyxy[3]<=y2]
    audit.update(ran=True,reason='rim_crop_retry',imgsz=size,
                 candidates=[d.as_dict() for d in detections])
    return detections,audit


def motion_candidates(motion, stream, frame, width, height, max_candidates=8):
    """Generate small fast-moving object candidates inside a bounded search region.

    Motion alone never proves that an object is a basketball.  These candidates are
    admitted only when a detector observation is missing and when there is either a
    recent ball trajectory or an established rim.  The existing temporal selector
    and shot geometry still have to accept the resulting track.
    """
    if motion is None or getattr(motion, 'size', 0) == 0:
        return [], {'ran': False, 'reason': 'no_motion'}
    region = recovery_region(stream, frame, width, height)
    reason = 'recent_ball'
    if region is None:
        # A fast blob near a rim is still just a hand, head, net, LED or camera
        # motion.  Without a detector-confirmed recent ball it stays diagnostic
        # evidence and must not seed the scoring trajectory.
        return [], {'ran': False, 'reason': 'no_recent_ball'}
    x1,y1,x2,y2=region
    roi=motion[y1:y2,x1:x2]
    if roi.size == 0:
        return [], {'ran': False, 'reason': 'empty_region', 'region_px': region}
    # Camera motion raises the whole ROI.  Use a high local percentile and a fixed
    # floor so only compact peaks remain; then join the short streak of a blurred ball.
    threshold=max(28.,float(np.percentile(roi,96)))
    mask=(roi>=threshold).astype(np.uint8)*255
    mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8),iterations=1)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    hi=.075*min(width,960)
    rows=[]
    for contour in contours:
        area=float(cv2.contourArea(contour))
        if area<5 or area>max(1600.,hi*hi):continue
        xx,yy,w,h=cv2.boundingRect(contour)
        if w<3 or h<3 or w>hi or h>hi:continue
        aspect=max(w,h)/max(1.,min(w,h))
        if aspect>3.0:continue
        perimeter=float(cv2.arcLength(contour,True))
        circularity=(4*math.pi*area/(perimeter*perimeter)) if perimeter>0 else 0.
        if circularity<.18:continue
        fill=area/max(1.,w*h)
        if fill<.16:continue
        patch=roi[yy:yy+h,xx:xx+w]
        strength=float(patch.mean())/255.
        conf=min(.49,.26+.14*strength+.05*min(fill,1.)+.04*min(circularity,1.)
                 -.025*max(0.,aspect-1.))
        rows.append((conf,Det('motion_ball',conf,(x1+xx,y1+yy,x1+xx+w,y1+yy+h))))
    rows.sort(key=lambda item:item[0],reverse=True)
    detections=[d for _,d in rows[:max_candidates]]
    return detections, {'ran': True, 'reason': reason, 'region_px': region,
                        'threshold': round(threshold,2),
                        'candidates': [d.as_dict() for d in detections]}
