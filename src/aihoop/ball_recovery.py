"""Bounded, optional crop inference. Only actual detector boxes are returned."""
import math
from .legacy_shots.detector import Det


def measured_detections(result, offset=(0,0), balls_only=False):
    rows=[]
    for box in result.boxes if result.boxes is not None else []:
        name=str(result.names.get(int(box.cls[0]),''))
        if balls_only and 'ball' not in name.lower():continue
        xyxy=[float(v)+offset[i%2] for i,v in enumerate(box.xyxy[0])]
        rows.append(Det(name,float(box.conf[0]),tuple(xyxy)))
    return rows


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
    result=model.predict(image[y1:y2,x1:x2],**dict(options,imgsz=640))[0]
    detections=measured_detections(result,(x1,y1),balls_only=True)
    # Map each measured crop box back to the ORIGINAL frame exactly once.
    detections=[d for d in detections if x1<=d.xyxy[0]<d.xyxy[2]<=x2 and y1<=d.xyxy[1]<d.xyxy[3]<=y2]
    audit.update(ran=True,reason='measured_crop_retry',imgsz=640,
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
    if rim is None or not getattr(rim,'initialized',False):
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
    result=model.predict(image[y1:y2,x1:x2],**dict(options,imgsz=960))[0]
    detections=measured_detections(result,(x1,y1),balls_only=True)
    detections=[d for d in detections if x1<=d.xyxy[0]<d.xyxy[2]<=x2 and y1<=d.xyxy[1]<d.xyxy[3]<=y2]
    audit.update(ran=True,reason='rim_crop_retry',imgsz=960,
                 candidates=[d.as_dict() for d in detections])
    return detections,audit
