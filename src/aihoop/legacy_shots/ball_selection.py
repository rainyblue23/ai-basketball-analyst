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
