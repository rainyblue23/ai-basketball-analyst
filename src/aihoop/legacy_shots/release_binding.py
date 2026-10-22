"""Conservative ownership from the scorer's existing measured observation history."""


def contact_region(box, options):
    _,x1,y1,x2,y2=box
    w,h=x2-x1,y2-y1
    return (x1-w*options['x_pad'], y1+h*options['top'],
            x2+w*options['x_pad'], y1+h*options['bottom'])


def touches(xy, box, options):
    x1,y1,x2,y2=contact_region(box,options)
    return x1<=xy[0]<=x2 and y1<=xy[1]<=y2


def bind_release(history, t, options):
    """Require exclusive upper-body proximity followed by separate observations.

    Missing people/balls, ambiguous overlaps and time gaps do not prove release.
    The proximity/departure interval is a release proxy, not hand-contact truth.
    """
    snapshots=[s for s in history if 0<=t-s['t']<=options['lookback']]
    runs={}
    for i,s in enumerate(snapshots):
        contacts=[p for p in s.get('person_boxes',()) if p[0] is not None
                  and touches(s['ball_xy'],p,options)]
        if len(contacts)!=1:
            continue
        p=contacts[0];pid=p[0];old=runs.get(pid)
        consecutive=old is not None and i==old['index']+1 and 0<s['t']-old['t']<=options['contact_gap']
        runs[pid]=dict(index=i,t=s['t'],count=old['count']+1 if consecutive else 1,
                       feet=((p[1]+p[3])/2,p[4]),ball_xy=s['ball_xy'])
    candidates=[]
    for pid,run in runs.items():
        if run['count']<options['min_contacts']:continue
        departure=[];previous_t=run['t']
        for s in snapshots[run['index']+1:]:
            if not 0<s['t']-previous_t<=options['departure_gap']:break
            boxes=s.get('person_boxes',())
            owner=next((p for p in boxes if p[0]==pid),None)
            # Occlusion or another person's contact cannot establish separation.
            if owner is None or any(touches(s['ball_xy'],p,options) for p in boxes):break
            departure.append(s);previous_t=s['t']
            if len(departure)>=options['min_departures']:break
        if len(departure)<options['min_departures']:continue
        candidates.append(dict(pid=pid,**run,departure=departure))
    candidates.sort(key=lambda c:c['t'],reverse=True)
    if not candidates:
        return None,dict(status='unknown',reason='insufficient_contact_departure')
    if len(candidates)>1 and candidates[0]['t']-candidates[1]['t']<=options['ambiguity_s']:
        return None,dict(status='unknown',reason='ambiguous_shooter')
    winner=candidates[0]
    evidence=dict(status='observed_proximity_departure',ball_xy=winner['ball_xy'],
                  interval_s=[winner['t'],winner['departure'][0]['t']],
                  contact_frames=winner['count'],departure_frames=len(winner['departure']),
                  timestamp_source='last_upper_body_proximity',timestamp_estimated=True)
    return (winner['feet'],winner['pid'],'contact_sequence',winner['t']),evidence
