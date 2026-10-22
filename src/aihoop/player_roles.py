"""Shadow-only role evidence; preserve UNKNOWN people and BoT-SORT IDs."""
from collections import Counter


def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area/union if union>0 else 0.


class PlayerRoleClassifier:
    def __init__(self,options):self.options=options;self.votes={}
    def reset(self):self.votes.clear()
    def update(self,persons,specialists,on_court=None):
        rows=[]
        for p in persons:
            pid=p.track_id;key=str(pid);votes=self.votes.setdefault(key,[]) if pid is not None and key not in ('-1','T-1') else []
            matching=[d for d in specialists if d.cls_name.lower() in ('player','referee')
                      and d.conf>=self.options['role_detector_conf'] and overlap(p.xyxy,d.xyxy)>=self.options['role_iou']]
            labels={d.cls_name.lower() for d in matching}
            vote=next(iter(labels)) if len(labels)==1 else 'unknown'
            votes.append(vote);del votes[:-15]
            counts=Counter(votes);role='UNKNOWN';confidence=0.;evidence=[]
            court=(on_court or {}).get(key)
            if court is False:evidence.append('footpoint_outside_trusted_court; could_be_offcourt_player')
            for label in ('referee','player'):
                if counts[label]>=self.options['role_min_votes'] and counts[label]>counts['player' if label=='referee' else 'referee']:
                    role=label.upper();confidence=min(.85,counts[label]/max(1,len(votes)))
                    evidence.append('specialist_person_iou_multiframe_votes');break
            # Geometry alone cannot distinguish a spectator from a bench player.
            if court is False and role=='PLAYER':role='UNKNOWN';confidence=0.
            rows.append(dict(track_id=pid,role=role,confidence=confidence,
                on_court=court,evidence=evidence,spectator_hypothesis=court is False,
                diagnostic_only=True,xyxy=list(p.xyxy)))
        return rows
