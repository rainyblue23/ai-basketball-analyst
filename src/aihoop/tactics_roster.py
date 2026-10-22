"""Opt-in tactical roster correction from measured appearance/role evidence.

This layer never changes shot attribution, BoT-SORT IDs or the input samples.
Role observations apply only to the matching time, never across a camera cut.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import math


@dataclass
class RosterEvidenceConfig:
    use_roles: bool = False
    use_teams: bool = False
    referee_confidence: float = .8
    team_min_votes: int = 3
    team_min_margin: float = .25
    team_min_vote_share: float = .7
    hue_min_sat: float = 60.
    hue_min_share: float = .8
    jersey_skin_filter: bool = False
    stitch_tracks: bool = False
    stitch_max_gap_s: float = .5
    stitch_max_dist_m: float = 1.5
    stitch_max_prediction_error_m: float = .75
    stitch_max_appearance_distance: float = .35
    stitch_min_endpoint_samples: int = 2
    stitch_max_iterations: int = 100
    stitch_motion_space: str = 'camera_pixels'
    stitch_max_pixel_error_ratio: float = .2

    def __post_init__(self):
        if not 0 < self.referee_confidence <= 1:
            raise ValueError('referee_confidence must be in (0, 1]')
        if self.team_min_votes < 3 or not 0 <= self.hue_min_sat <= 255:
            raise ValueError('Invalid appearance evidence threshold')
        for threshold in (self.team_min_margin, self.team_min_vote_share, self.hue_min_share):
            if not 0 < threshold <= 1:
                raise ValueError('Appearance confidence thresholds must be in (0, 1]')
        if (not 0 < self.stitch_max_gap_s <= 1 or self.stitch_max_dist_m <= 0
                or self.stitch_max_prediction_error_m <= 0 or self.stitch_min_endpoint_samples < 2
                or not 0 < self.stitch_max_appearance_distance <= 1 or self.stitch_max_iterations < 1):
            raise ValueError('Invalid tracklet evidence thresholds')
        if self.stitch_motion_space not in ('court','camera_pixels') or not 0 < self.stitch_max_pixel_error_ratio <= 1:
            raise ValueError('Invalid tracklet motion configuration')


def roster_signature(raw):
    """Bind cached evidence to pixel boxes, positions, timing and cut boundaries."""
    payload = {'video': raw.video_path, 'fps': raw.fps, 'duration': raw.duration,
               'width': raw.width, 'height': raw.height,
               'track': [s.to_dict() for s in raw.player_track], 'observations': raw.player_obs,
               'cuts': [r['t'] for r in raw.detections_meta.get('legacy_shots', {}).get('frames', []) if r.get('cut')]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def samples_signature(samples):
    return hashlib.sha256(json.dumps([s.to_dict() for s in samples],sort_keys=True,
        separators=(',',':')).encode()).hexdigest()


def validate_roster_evidence(raw, evidence, cfg=None):
    if evidence.get('input_signature') != roster_signature(raw):
        raise ValueError('Tactical roster evidence does not match this video/track/camera timeline')
    if cfg and cfg.use_teams:
        for name in ('team_min_votes','team_min_margin','team_min_vote_share',
                     'hue_min_sat','hue_min_share','jersey_skin_filter'):
            if evidence.get('config', {}).get(name) != getattr(cfg, name):
                raise ValueError('Tactical appearance evidence configuration mismatch: '+name)


def apply_roster_evidence(samples, evidence, cfg=None):
    cfg = cfg or RosterEvidenceConfig()
    roles = {(round(float(r['t']), 3), str(r['player_id'])): r
             for r in evidence.get('observations', [])}
    teams = evidence.get('teams', {}).get('assignments', {})
    out, decisions = [], []
    for s in samples:
        row = roles.get((round(s.t, 3), s.player_id), {})
        if (cfg.use_roles and row.get('role') == 'REFEREE'
                and row.get('confidence', 0) >= cfg.referee_confidence):
            decisions.append({'t': s.t, 'player_id': s.player_id,
                              'action': 'exclude_from_tactics', 'reason': 'multiframe_referee_evidence'})
            continue
        team = s.team
        if cfg.use_teams:
            assignment = teams.get(s.player_id, {})
            # Anonymous appearance groups; home/away identity is not inferred
            # from jersey brightness or horizontal position.
            team = {'home': 'team_a', 'away': 'team_b'}.get(assignment.get('team'), 'unknown')
        out.append(replace(s, team=team))
    return out, decisions


def stitch_roster_evidence(samples, evidence, cuts=(), cfg=None):
    """Opt-in use of the existing stitcher; aliases affect tactics only."""
    from .sources import stitch_player_tracks
    cfg=cfg or RosterEvidenceConfig()
    if not cfg.stitch_tracks:return list(samples), {'enabled':False,'aliases':{}}
    links=evidence.get('identity_links',{})
    if links.get('samples_signature')!=samples_signature(samples):
        raise ValueError('Tracklet endpoint evidence does not match the filtered roster')
    if links.get('proposals') and not links.get('camera_links'):
        raise ValueError('Tracklet camera continuity evidence is missing')
    joined,meta=stitch_player_tracks(samples,max_gap=cfg.stitch_max_gap_s,
        max_dist=cfg.stitch_max_dist_m,max_iter=cfg.stitch_max_iterations,cuts=cuts,
        link_evaluator=TrackletLinkEvaluator(links,cfg),allow_unknown=True)
    return joined,dict(meta,enabled=True,real_player_identity_verified=False,
                       measured_positions_added=0)


def torso_descriptor(frame, box):
    """Small torso HSV histogram; colour supports a link, never proves identity."""
    import cv2
    import numpy as np
    x1,y1,x2,y2=map(float,box)
    h,w=frame.shape[:2]
    x0,x3=max(0,int(x1+(x2-x1)*.25)),min(w,int(x2-(x2-x1)*.25))
    y0,y3=max(0,int(y1+(y2-y1)*.25)),min(h,int(y1+(y2-y1)*.60))
    if x3-x0<4 or y3-y0<6:return None
    hsv=cv2.cvtColor(frame[y0:y3,x0:x3],cv2.COLOR_BGR2HSV)
    hsv[hsv[:,:,1]<60,0]=0  # hue noise must not split a white jersey
    bands=[]
    for part in np.array_split(hsv,2):
        valid=(part[:,:,2]>=30)&(part[:,:,2]<=245)
        if int(valid.sum())<6:return None
        hist=cv2.calcHist([part],[0,1,2],valid.astype(np.uint8),[8,3,3],[0,180,0,256,0,256]).reshape(-1)
        bands.extend((hist/hist.sum()/2).tolist())
    return [round(float(x),6) for x in bands]


def appearance_distance(a, b):
    if len(a)!=len(b) or not a:return 1.
    total_a,total_b=sum(a),sum(b)
    if min(total_a,total_b)<=0:return 1.
    coefficient=sum(math.sqrt(max(0,x*y)/(total_a*total_b)) for x,y in zip(a,b))
    return math.sqrt(max(0.,1-min(1.,coefficient)))


class TrackletLinkEvaluator:
    """Use cached measured endpoint crops and existing ORB/RANSAC evidence.

    A motion prediction is used for association only. It is not appended as a
    new observed player position. Spatially plausible alternatives without
    enough evidence keep the existing stitcher's uniqueness gate closed.
    """
    def __init__(self, evidence, cfg=None):
        self.data=evidence
        self.cfg=cfg or RosterEvidenceConfig()

    def __call__(self, source_a, source_b, ta, tb):
        from statistics import median
        cfg=self.cfg
        reasons=[]
        head=self.data.get('endpoints',{}).get(source_b,{}).get('head',[])
        tail=self.data.get('endpoints',{}).get(source_a,{}).get('tail',[])
        row={'accepted':False,'plausible':True,'rejection_reasons':reasons,
             'motion_space':cfg.stitch_motion_space}
        if len(tail)<cfg.stitch_min_endpoint_samples or len(head)<cfg.stitch_min_endpoint_samples:
            reasons.append('insufficient_measured_endpoint_appearance')
            return row
        if abs(tail[-1]['t']-ta[-1].t)>.002 or abs(head[0]['t']-tb[0].t)>.002:
            reasons.append('endpoint_evidence_time_mismatch')
            return row
        distances=[appearance_distance(x['descriptor'],y['descriptor']) for x in tail for y in head]
        distance=median(distances)
        row['appearance_distance']=round(distance,4)
        if distance>cfg.stitch_max_appearance_distance:
            reasons.append('appearance_mismatch')
            if distance>.7:row['plausible']=False
        key=f"{tail[-1]['frame']}:{head[0]['frame']}"
        camera=self.data.get('camera_links',{}).get(key,{})
        row['camera_key']=key
        if not camera.get('ok'):
            reasons.append('camera_continuity_unverified')
        ha=tail[-1]['box'][3]-tail[-1]['box'][1]
        hb=head[0]['box'][3]-head[0]['box'][1]
        ratio=hb/max(ha,1)
        row['bbox_height_ratio']=round(ratio,4)
        if not .5<=ratio<=2:reasons.append('bbox_scale_change')

        def prediction_error(points,t,target):
            import numpy as np
            ts=np.array([s.t for s in points],float)
            if len(points)<2 or ts.max()-ts.min()<.02:return None
            matrix=np.column_stack((ts-ts.mean(),np.ones(len(ts))))
            xy=np.array([(s.x,s.y) for s in points],float)
            coefficient=np.linalg.lstsq(matrix,xy,rcond=None)[0]
            predicted=np.array([t-ts.mean(),1.])@coefficient
            return float(np.linalg.norm(predicted-np.array(target)))
        before=[s for s in ta if ta[-1].t-s.t<=.35][-4:]
        following=[s for s in tb if s.t-tb[0].t<=.35][:4]
        forward=prediction_error(before,tb[0].t,(tb[0].x,tb[0].y))
        backward=prediction_error(following,ta[-1].t,(ta[-1].x,ta[-1].y))
        row['forward_error_m']=round(forward,4) if forward is not None else None
        row['backward_error_m']=round(backward,4) if backward is not None else None
        if cfg.stitch_motion_space=='court':
            if forward is None or backward is None:reasons.append('insufficient_measured_motion')
            elif max(forward,backward)>cfg.stitch_max_prediction_error_m:reasons.append('motion_prediction_mismatch')
        else:
            # Projected court points can jitter even when pixel boxes remain
            # coherent. Evaluate measured torso centres in ONE verified camera
            # coordinate system; do not relax the court error threshold.
            import numpy as np
            from types import SimpleNamespace
            ref=tail[-1]['frame']
            width,height=self.data.get('image_size',(0,0))
            camera_width,camera_height=self.data.get('camera_size',(0,0))
            def pixel_points(observations):
                points=[]
                for o in observations:
                    box=o['box']
                    p=np.array([(box[0]+box[2])/2*camera_width/max(width,1),
                        (box[1]+.55*(box[3]-box[1]))*camera_height/max(height,1),1.])
                    if o['frame']!=ref:
                        transform=self.data.get('camera_links',{}).get(f"{ref}:{o['frame']}",{})
                        if not transform.get('ok') or transform.get('H') is None:return []
                        p=np.asarray(transform['H'])@p
                        if not np.isfinite(p).all() or abs(p[2])<1e-6:return []
                        p=p/p[2]
                    points.append(SimpleNamespace(t=o['t'],x=float(p[0]),y=float(p[1])))
                return points
            pbefore,pafter=pixel_points(tail),pixel_points(head)
            if width<=0 or height<=0 or len(pbefore)<2 or len(pafter)<2:
                reasons.append('pixel_camera_motion_unverified')
            else:
                pf=prediction_error(pbefore,pafter[0].t,(pafter[0].x,pafter[0].y))
                pb=prediction_error(pafter,pbefore[-1].t,(pbefore[-1].x,pbefore[-1].y))
                normalizer=ha*camera_height/max(height,1)
                error=max(pf,pb)/max(normalizer,1.) if pf is not None and pb is not None else None
                row['camera_pixel_error_ratio']=round(error,4) if error is not None else None
                if error is None or error>cfg.stitch_max_pixel_error_ratio:reasons.append('pixel_motion_prediction_mismatch')
        row['accepted']=not reasons
        row['supporting_evidence']=['short_gap','torso_multiframe_appearance','bidirectional_measured_motion',
                                    'verified_background_geometry'] if row['accepted'] else []
        return row
