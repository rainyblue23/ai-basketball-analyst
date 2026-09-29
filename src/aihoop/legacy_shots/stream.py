"""单帧检测 → 旧版选球/筐与状态机。无视频 I/O，可离线重放。"""
from __future__ import annotations

import copy
import math
from .detector import Det, filter_by_size, pick_best, pick_rim
from .scorer import ScoreEngine

# 旧版 config.yaml 的有效默认值；不搬旧版的机器路径、UI 和估算三分。
DEFAULT_CONFIG = {
    'detect': {'imgsz': 640, 'ball_conf': .25, 'rim_min_conf': .35,
               'ball_min_w_ratio': .012, 'ball_max_w_ratio': .24,
               'ball_jump_px_per_frame': 90., 'rim_min_aspect': 1.2, 'center_lock_widths': 0.},
    'score': {'enable_three_point': False, 'make_radius_ratio': .65,
              'make_exit_radius_ratio': 1., 'in_rim_below_ratio': .6,
              'make_window_s': .9, 'make_allow_occluded_entry': False,
              'make_window_from_crossing': False, 'approach_radius_ratio': 5.,
              'miss_timeout_s': 3.5, 'attempt_min_gap_s': .35,
              'leave_radius_ratio': 3., 'ball_recent_s': .5, 'suspected_make_max_gap_s': .7,
              'rim_max_jump_px': 0, 'rim_readopt_far_frames': 6,
              'rim_stale_s': 1.5, 'rim_need_confirm': 2,
              'ball_max_gap_frames': 5, 'release_lookback_s': 2.,
              'release_max_person_dist_ratio': .9}}

def rim_availability(frames, fps):
    """Observed tracker availability, not detector accuracy or shot recall.

    Old traces without the tracked_rim contract must not acquire invented
    coverage numbers. Intervals describe runs of sampled unavailable frames.
    """
    if not frames or any('tracked_rim' not in r for r in frames):
        return None
    usable = sum(bool((r.get('tracked_rim') or {}).get('fresh')) for r in frames)
    gaps = []
    start = None
    for row in frames:
        fresh = bool((row.get('tracked_rim') or {}).get('fresh'))
        if not fresh and start is None:
            start = float(row['t'])
        if fresh and start is not None:
            end = float(row['t'])
            if end - start >= 2.0:
                gaps.append(dict(start=round(start, 3), end=round(end, 3)))
            start = None
    if start is not None:
        end = float(frames[-1]['t']) + 1 / max(float(fps), 1)
        if end - start >= 2.0:
            gaps.append(dict(start=round(start, 3), end=round(end, 3)))
    return dict(sampled_frames=len(frames), usable_frames=usable,
                usable_fraction=usable / len(frames), unavailable_ranges=gaps,
                min_gap_s=2.0)

def unpack(det):
    return None if det is None else Det(det['cls'], det['conf'], tuple(det['xyxy']),
                                       det.get('track_id'), det.get('predicted',False))

def pack(det):
    # 不四舍五入：回放应使用同一次运行、同精度的检测。
    return None if det is None else dict(cls=det.cls_name, conf=det.conf,
        xyxy=list(det.xyxy), track_id=det.track_id, predicted=det.predicted)

class LegacyShotStream:
    def __init__(self, fps, width, config=None, manual_hoop=None, hint=None):
        self.config=copy.deepcopy(DEFAULT_CONFIG)
        for section, values in (config or {}).items():
            if section in self.config:self.config[section].update(values)
        self.fps=fps; self.width=width; self.engine=ScoreEngine(self.config,fps)
        self.manual_hoop=manual_hoop; self.hint=hint
        self.center_lock_width=None; self.center_rejected=0
        self.last_ball=None; self.last_frame=-999; self.vx=self.vy=0.
        self.events=[]; self.frames=[]; self.rim_seen=0; self.real_seen=0
        self.track_segment=0; self.transitions=[]; self.first_confirmed=None
        self.center_rejected_frames=0

    def tracked_state(self, t):
        r=self.engine.rim
        if not r.initialized:return None
        return dict(cx=r.cx,cy=r.cy,w=r.w,h=r.h,segment=self.track_segment,
                    fresh=r.fresh(t,self.engine.rim_stale_s),last_seen_t=r.last_seen_t)

    def hint_relation(self, state):
        if self.hint is None or state is None:return None
        dx=state['cx']-self.hint[0];dy=state['cy']-self.hint[1]
        return dict(distance_px=math.hypot(dx,dy),
                    inside_box=abs(dx)<=state['w']/2 and abs(dy)<=state['h']/2)


    def reset(self, frame, t):
        # 切镜结束已有候选并清空身份，禁止跨镜头拼接穿筐。
        previous=self.tracked_state(t)
        closed=self.engine.finalize(frame,t)
        self.events.extend(closed)
        self.transitions.append(dict(frame=frame,t=t,reason='cut',previous=previous,
                                     current=None,closed_attempts=len(closed)))
        self.engine=ScoreEngine(self.config,self.fps)
        self.last_ball=None; self.last_frame=-999; self.vx=self.vy=0.

    def update(self, frame, t, detections, persons=(), cut=False):
        if cut:self.reset(frame,t)
        d=self.config['detect'];s=self.config['score']
        gap=s['ball_max_gap_frames']
        if self.last_ball and frame-self.last_frame>max(gap,int(self.fps*s['ball_recent_s'])):
            self.last_ball=None; self.vx=self.vy=0.
        balls=filter_by_size([b for b in detections if ('ball' in b.cls_name.lower() or
            'basket' in b.cls_name.lower()) and b.conf>=d['ball_conf']],self.width,
            d['ball_min_w_ratio'],d['ball_max_w_ratio'])
        ball=pick_best(balls,(self.last_ball.cx,self.last_ball.cy) if self.last_ball else None)
        if ball and self.last_ball:
            delta=max(1,frame-self.last_frame)
            # Prediction is bounded by the existing extrapolation horizon.
            # Missing frames increase uncertainty, not the allowable speed linearly.
            horizon=min(delta,max(1,gap))
            px=self.last_ball.cx+self.vx*horizon;py=self.last_ball.cy+self.vy*horizon
            bound=d['ball_jump_px_per_frame']*math.sqrt(delta)
            if math.hypot(ball.cx-px,ball.cy-py)>bound:
                valid=[b for b in balls if math.hypot(b.cx-px,b.cy-py)<=bound]
                ball=max(valid,key=lambda b:b.conf) if valid else None
        if ball:
            if self.last_ball and 0<frame-self.last_frame<=10:
                delta=frame-self.last_frame
                self.vx=(ball.cx-self.last_ball.cx)/delta;self.vy=(ball.cy-self.last_ball.cy)/delta
            self.last_ball=ball;self.last_frame=frame;self.real_seen+=1
        elif self.last_ball and frame-self.last_frame<=gap:
            delta=frame-self.last_frame;b=self.last_ball
            ball=Det('basketball',0.,tuple(v+(self.vx if i%2==0 else self.vy)*delta
                        for i,v in enumerate(b.xyxy)),predicted=True)
        rims=[r for r in detections if any(k in r.cls_name.lower() for k in ('rim','hoop'))]
        # 完整指送到此处的 NMS 后候选，不包含检测器阈值以下的框。
        candidates=[dict(index=i,**pack(r),selection_reason='not_selected') for i,r in enumerate(rims)]
        candidate_by_id={id(r):c for r,c in zip(rims,candidates)}
        rejected_before=self.center_rejected
        for r in rims:
            if r.conf<d['rim_min_conf']:candidate_by_id[id(r)]['selection_reason']='low_confidence'
            elif (r.h>0 and r.w/r.h<d['rim_min_aspect']) or (self.hint and not self.engine.rim.initialized and r.h<=0):candidate_by_id[id(r)]['selection_reason']='invalid_shape'

        # 中心提示仅用于初次选筐，不把无尺寸的点变成静态篮筐。
        if self.hint and not self.engine.rim.initialized:
            valid=[r for r in rims if r.conf>=d['rim_min_conf'] and r.h>0 and r.w/r.h>=d['rim_min_aspect']]
            rims=sorted(valid,key=lambda r:math.hypot(r.cx-self.hint[0],r.cy-self.hint[1]))[:1]
            for r in valid:
                if not rims or r is not rims[0]:candidate_by_id[id(r)]['selection_reason']='not_nearest_hint'
        if self.hint and d['center_lock_widths'] > 0:
            valid=[]
            for r in rims:
                radius=d['center_lock_widths'] * (self.center_lock_width or r.w)
                if math.hypot(r.cx-self.hint[0],r.cy-self.hint[1]) <= radius:
                    valid.append(r)
                else:
                    self.center_rejected+=1
                    candidate_by_id[id(r)]["selection_reason"]="outside_center_lock"
            rims=valid
        rim,_=pick_rim(rims,min_conf=d['rim_min_conf'],min_aspect=d['rim_min_aspect'])
        if rim is not None:candidate_by_id[id(rim)]['selection_reason']='selected'
        selected_source='detector' if rim is not None else 'none'
        if self.manual_hoop is not None and self.manual_hoop.rx>0 and self.manual_hoop.ry>0:
            for c in candidates:
                if c['selection_reason']=='selected':c['selection_reason']='manual_override'
            selected_source='manual'
            h=self.manual_hoop
            rim=Det('rim',1.,(h.cx-h.rx,h.cy-h.ry,h.cx+h.rx,h.cy+h.ry))
        self.rim_seen+=int(rim is not None)
        previous=self.tracked_state(t)
        row=dict(frame=frame,t=t,ball=pack(ball),rim=pack(rim),persons=[pack(p) for p in persons],cut=cut,
                 rim_candidates=candidates,selected_rim_source=selected_source,
                 ball_candidates=[pack(b) for b in balls])
        new_events=self.engine.update(frame,t,ball,rim,list(persons))
        reason=self.engine.rim.last_update_reason
        if reason in ('initialized','reacquired_near','reacquired_far'):
            self.track_segment+=1
            state=self.tracked_state(t)
            self.transitions.append(dict(frame=frame,t=t,reason=reason,previous=previous,
                current=state,closed_attempts=len(new_events) if previous is not None else 0))
            if self.first_confirmed is None:
                self.first_confirmed=dict(t=t,tracked_rim=state,hint_relation=self.hint_relation(state))
        state=self.tracked_state(t)
        row.update(tracked_rim=state,tracker_reason=reason,hint_relation=self.hint_relation(state),
                   center_rejected_candidates=self.center_rejected-rejected_before,
                   evidence_segment=(previous['segment'] if previous and new_events and reason.startswith('reacquired') else self.track_segment))
        for c in candidates:
            c['tracker_reason']=reason if c['selection_reason']=='selected' else 'not_submitted'
        self.center_rejected_frames+=int(self.center_rejected>rejected_before)
        self.frames.append(row)
        self.events.extend(new_events)
        if self.center_lock_width is None and self.engine.rim.initialized:
            self.center_lock_width=self.engine.rim.w
        return ball

    def finish(self, frame, t):
        self.events.extend(self.engine.finalize(frame,t))
        return self.events

    def to_dict(self):
        return dict(version='hoopai_legacy_v1',trace_schema=2,fps=self.fps,config=self.config,
                    rim_tracking=self.tracking_summary(),
                    frames=self.frames,events=self.events,real_ball_frames=self.real_seen,
                    rim_frames=self.rim_seen, center_rejected=self.center_rejected,
                    center_lock_width=self.center_lock_width, center_hint=self.hint)

    def tracking_summary(self):
        last=self.frames[-1] if self.frames else {}
        return dict(schema=2,center_hint=self.hint,
            availability=rim_availability(self.frames,self.fps),
            lock_enabled=bool(self.hint is not None and self.config['detect']['center_lock_widths']>0),
            lock_requested=self.config['detect']['center_lock_widths']>0,
            lock_widths=self.config['detect']['center_lock_widths'],lock_width=self.center_lock_width,
            rejected_candidates=self.center_rejected,rejected_frames=self.center_rejected_frames,
            frames=len(self.frames),first_confirmed=self.first_confirmed,
            last_tracked=last.get('tracked_rim'),transitions=self.transitions,
            note='跟踪段变化不等于物理换筐；候选为检测器阈值和 NMS 后输出。')

def replay_trace(trace):
    """同一运行已选中的真实/预测框回放，不重跑检测器，不混用别的筐位。"""
    engine=ScoreEngine(trace['config'],trace['fps']);events=[]
    for row in trace['frames']:
        if row.get('cut'):
            events.extend(engine.finalize(row['frame'],row['t']))
            engine=ScoreEngine(trace['config'],trace['fps'])
        events.extend(engine.update(row['frame'],row['t'],unpack(row['ball']),unpack(row['rim']),
                                    [unpack(p) for p in row['persons']]))
    if trace['frames']:
        row=trace['frames'][-1]
        events.extend(engine.finalize(row['frame']+1,row['t']+1/trace['fps']))
    return events
