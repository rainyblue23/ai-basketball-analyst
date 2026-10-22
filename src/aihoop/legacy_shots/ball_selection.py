"""Select measured ball boxes; motion predictions never become measurements."""
import math


def select_ball(candidates, previous, delta, velocity, horizon, jump):
    audits=[]
    target=None
    if previous is not None:
        delta=max(1,delta)
        steps=min(delta,max(1,horizon))
        target=(previous.cx+velocity[0]*steps,previous.cy+velocity[1]*steps)
        bound=jump*math.sqrt(delta)
    for box in candidates:
        distance=math.hypot(box.cx-target[0],box.cy-target[1]) if target else None
        # Scale is a soft preference only: blur, depth and zoom change box size.
        scale=abs(math.log(max(box.w,1)/max(previous.w,1))) if previous else 0.
        score=float(box.conf)-(0.002*distance if distance is not None else 0.)-0.08*min(scale,2.)
        audits.append(dict(selection_reason='motion_rejected' if target and distance>bound else 'not_selected',
                           temporal_score=round(score,6),prediction_distance_px=distance,
                           scale_log_change=scale))
    valid=[i for i,a in enumerate(audits) if a['selection_reason']!='motion_rejected']
    if not valid:return None,audits
    best=max(valid,key=lambda i:audits[i]['temporal_score'])
    audits[best]['selection_reason']='selected'
    return candidates[best],audits


def temporal_support(candidate, frame, fps, history, min_frames=3, window_s=.25,
                     min_motion_px=2., jump=90.):
    """Independent model observations only; preview calls never create history."""
    chain=[(frame,candidate)]
    seen={frame}
    for old_frame,old_candidates in reversed(history):
        if old_frame in seen or old_frame>=frame or (frame-old_frame)/fps>window_s:continue
        anchor_frame,anchor=chain[-1]
        eligible=[old for old in old_candidates if old.is_measurement
                  and .5*candidate.w <= old.w <= 2*candidate.w
                  and math.hypot(old.cx-anchor.cx,old.cy-anchor.cy)<=jump*math.sqrt(anchor_frame-old_frame)]
        if not eligible:continue
        chosen=min(eligible,key=lambda old:math.hypot(old.cx-anchor.cx,old.cy-anchor.cy))
        chain.append((old_frame,chosen));seen.add(old_frame)
        if len(chain)>=min_frames:break
    if len(chain)<min_frames:return False
    return math.hypot(chain[0][1].cx-chain[-1][1].cx,chain[0][1].cy-chain[-1][1].cy)>=min_motion_px


def adaptive_size_evidence(candidate, previous, persons, rim, history, frame, fps,
                           width, height, lo, hi, options, jump):
    """Contextual size proposal; raw temporal votes never become ball truth.

    The standard size range is untouched. Extending it needs independent model
    observations, movement, bounded scale and player/rim/recent-ball context.
    The caller must still apply head, graphics, confidence and motion gates.
    """
    import statistics
    if lo<=candidate.w<=hi and lo<=candidate.h<=hi:
        return True,dict(mode='base',limits_px=[lo,hi])
    heights=[p.h for p in persons if p.h>0 and not p.predicted]
    context_hi=statistics.median(heights)*options['adaptive_person_height_ratio'] if heights else hi
    if previous is not None:context_hi=max(context_hi,max(previous.w,previous.h)*options['adaptive_growth_ratio'])
    if rim and rim.get('fresh'):context_hi=max(context_hi,rim['w']*options['adaptive_rim_width_ratio'])
    max_side=options['adaptive_max_short_side_ratio']*min(width,height or width)
    upper=max(hi,min(max_side,context_hi))
    lower=min(lo,max(options['adaptive_min_side_px'],statistics.median(heights)*.02)) if heights else lo
    within=lower<=candidate.w<=upper and lower<=candidate.h<=upper
    context=previous is not None or bool(heights) or bool(rim and rim.get('fresh'))
    supported=within and context and temporal_support(candidate,frame,fps,history,
        min_frames=options['adaptive_support_frames'],window_s=options['adaptive_window_s'],
        min_motion_px=options['adaptive_motion_px'],jump=jump)
    return bool(supported),dict(mode='adaptive_confirmed' if supported else 'adaptive_pending',
        limits_px=[lower,upper],temporal_support=bool(supported),context_available=bool(context))
