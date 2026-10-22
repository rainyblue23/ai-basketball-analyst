"""Register measured court frames to a moving broadcast view; missing matches stay unknown."""
import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from .court import Calibration
from .multical import MultiCal, worst_readings, weak_segments
from .video_compat import ensure_cv2_preview


@dataclass(frozen=True)
class RegistrationOptions:
    """Bounded, opt-in re-registration; never carries a stale matrix forward."""
    local_recovery: bool = False
    anchor_step_s: float = .25
    max_anchor_gap_s: float = .75
    min_anchor_support: int = 3
    max_anchor_candidates: int = 6
    min_matches: int = 24
    min_inliers: int = 24
    min_inlier_ratio: float = .4
    ransac_px: float = 2.
    min_floor_fit: float = 1.25
    max_median_disagreement_ratio: float = .005
    max_disagreement_ratio: float = .015
    max_floor_median_difference: float = 20.
    floor_difference_threshold: float = 24.
    max_floor_changed_fraction: float = .45
    image_cache_size: int = 8

    def __post_init__(self):
        if not (0 < self.anchor_step_s <= self.max_anchor_gap_s <= 2.
                and 2 <= self.min_anchor_support <= self.max_anchor_candidates <= 12
                and self.min_matches >= 4 and self.min_inliers >= 4
                and 0 < self.min_inlier_ratio <= 1 and self.ransac_px > 0
                and self.min_floor_fit >= 1.25 and self.image_cache_size >= 1
                and self.max_floor_median_difference > 0 and self.floor_difference_threshold > 0
                and 0 < self.max_floor_changed_fraction < 1
                and 0 < self.max_median_disagreement_ratio <= self.max_disagreement_ratio <= .05):
            raise ValueError('Unsafe registration recovery configuration')


def floor_photometric_support(current, reference, transform, ref_cal, options):
    """Reject blends/overlays whose floor no longer resembles the anchor.

    Compare only the projected floor with valid warped pixels. Median exposure
    offset is removed; moving people can differ without clearing the whole
    scene. This gate establishes support, not a semantic scene/shot label.
    """
    from .court import FULL_COURT_CORNERS
    h,w=reference.shape[:2]
    gray=cv2.cvtColor(reference,cv2.COLOR_BGR2GRAY)
    warped=cv2.warpPerspective(cv2.cvtColor(current,cv2.COLOR_BGR2GRAY),transform,(w,h))
    valid=cv2.warpPerspective(np.full(current.shape[:2],255,np.uint8),transform,(w,h),flags=cv2.INTER_NEAREST)
    mask=np.zeros((h,w),np.uint8)
    try:
        poly=cv2.perspectiveTransform(np.float32(FULL_COURT_CORNERS).reshape(-1,1,2),
                                     np.linalg.inv(np.asarray(ref_cal.H))).reshape(-1,2)
        if not np.isfinite(poly).all():return dict(ok=False,reason='no_visible_floor')
        cv2.fillConvexPoly(mask,np.clip(poly,-10000,10000).astype(np.int32),255)
    except (cv2.error,np.linalg.LinAlgError,ValueError):
        return dict(ok=False,reason='invalid_floor_geometry')
    mask[:int(h*.13)]=0;mask[int(h*.80):]=0
    mask=cv2.bitwise_and(mask,valid)
    source=warped[mask>0].astype(float);target=gray[mask>0].astype(float)
    if len(source)<1000:return dict(ok=False,reason='insufficient_visible_floor')
    residual=source-target;residual=np.abs(residual-np.median(residual))
    median=float(np.median(residual));changed=float(np.mean(residual>options.floor_difference_threshold))
    return dict(ok=median<=options.max_floor_median_difference and changed<=options.max_floor_changed_fraction,
                median_difference=median,changed_fraction=changed,floor_pixels=len(source))


def registration_consistent(a, b, size, options):
    """Compare both estimated floor geometries, only on shared visible floor.

    World points are in native FULL court coordinates, not folded analytics
    coordinates. Widely extrapolated off-screen points cannot validate a match.
    """
    from .model import COURT_WIDTH, COURT_LENGTH
    width, height = size
    try:
        world = np.float32([(x, y) for x in (-COURT_WIDTH*.3, 0, COURT_WIDTH*.3)
                            for y in np.linspace(-COURT_LENGTH*.43, COURT_LENGTH*.43, 5)])
        pa = cv2.perspectiveTransform(world.reshape(-1, 1, 2), np.linalg.inv(np.asarray(a.H))).reshape(-1, 2)
        pb = cv2.perspectiveTransform(world.reshape(-1, 1, 2), np.linalg.inv(np.asarray(b.H))).reshape(-1, 2)
        visible = (np.isfinite(pa).all(axis=1) & np.isfinite(pb).all(axis=1)
                   & (pa[:,0] >= 0) & (pa[:,0] < width) & (pa[:,1] >= 0) & (pa[:,1] < height)
                   & (pb[:,0] >= 0) & (pb[:,0] < width) & (pb[:,1] >= 0) & (pb[:,1] < height))
        if visible.sum() < 4:
            return False
        delta = np.linalg.norm(pa[visible] - pb[visible], axis=1) / math.hypot(width, height)
        return (float(np.median(delta)) <= options.max_median_disagreement_ratio
                and float(delta.max()) <= options.max_disagreement_ratio)
    except (ValueError, np.linalg.LinAlgError, cv2.error):
        return False


def multical_fit(mc):
    """Per-camera scores must never be replaced by a whole-video primary-camera score."""
    readings=worst_readings(mc)
    weak=weak_segments(mc)
    return dict(readings, ok=not weak, weak_segments=weak,
                basis='verified_marked_frames', by_segment=mc.summary()['segments'])


class MarkedProjector:
    def __init__(self, video, calibration_file, width, height, *, options=None, camera_cuts=()):
        data=json.loads(Path(calibration_file).read_text())
        self.mc=MultiCal.from_dict(data)
        self.width=width;self.height=height
        self.capture=cv2.VideoCapture(ensure_cv2_preview(str(video)))
        from .frame_reader import FrameReader
        self.reader=FrameReader(self.capture)
        self.fps=self.capture.get(cv2.CAP_PROP_FPS) or 30.
        self.orb=cv2.ORB_create(nfeatures=2500)
        self.matcher=cv2.BFMatcher(cv2.NORM_HAMMING)
        self.references=[];self.cache={};self.audit=[]
        self.options=options or RegistrationOptions()
        self.camera_cuts=tuple(sorted(float(t) for t in camera_cuts))
        self._direct_cache={};self._images=OrderedDict();self._local_features=OrderedDict()
        for row in data.get('source_frames',[]):
            t=float(row['t']); cal=self.mc.cal_at(t)
            if cal is None or not cal.H:continue
            image=self.frame(t)
            if image is None:continue
            keypoints,descriptor=self.features(image)
            if descriptor is not None:
                self.references.append((t,cal,keypoints,descriptor))

    def close(self):
        self.capture.release()

    def frame(self,t):
        images=getattr(self,'_images',{})
        key=round(float(t),3)
        if key in images:
            images.move_to_end(key)
            return images[key]
        ok,frame=self.reader.read(round(max(0.,float(t))*self.fps))
        if ok and isinstance(images,OrderedDict):
            images[key]=frame
            while len(images)>self.options.image_cache_size:images.popitem(last=False)
        return frame if ok else None

    def features(self,image):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        # Broadcast score bugs and watermarks remain fixed on screen, unlike the court.
        mask=np.zeros(gray.shape,np.uint8)
        mask[int(gray.shape[0]*.13):int(gray.shape[0]*.80),int(gray.shape[1]*.04):int(gray.shape[1]*.96)]=255
        return self.orb.detectAndCompute(gray,mask)

    def at(self,t):
        t=round(float(t),3)
        if t in self.cache:return self.cache[t]
        result,detail=self._direct_at(t)
        options=getattr(self,'options',RegistrationOptions())
        if result is None and options.local_recovery:
            result,local_detail=self._recover_local(t)
            detail.update(local_recovery=local_detail)
            if result is not None:
                detail.update(matched=True,source='local_registered',
                              reference_t=local_detail['anchor_times'][0])
        self.cache[t]=result
        self.audit.append(detail)
        return result

    def _direct_at(self,t):
        """Original direct matcher, also used for *unrecovered* local anchors."""
        direct=getattr(self,'_direct_cache',{})
        if t in direct:
            calibration,detail=direct[t]
            return calibration,dict(detail)
        image=self.frame(t)
        result=None;best=0;chosen=None;ratio_out=0
        rejected=[]
        if image is not None:
            keypoints,descriptor=self.features(image)
            if descriptor is not None:
                for ref_t,cal,ref_kp,ref_desc in self.references:
                    pairs=self.matcher.knnMatch(descriptor,ref_desc,k=2)
                    matches=[p[0] for p in pairs if len(p)==2 and p[0].distance < .7*p[1].distance]
                    if len(matches)<24:
                        rejected.append(dict(reference_t=ref_t,reason='insufficient_matches',matches=len(matches)))
                        continue
                    src=np.float32([keypoints[m.queryIdx].pt for m in matches])
                    dst=np.float32([ref_kp[m.trainIdx].pt for m in matches])
                    transform,inliers=cv2.findHomography(src,dst,cv2.RANSAC,2.)
                    if transform is None:
                        rejected.append(dict(reference_t=ref_t,reason='no_homography'))
                        continue
                    count=int(inliers.sum());ratio=count/len(matches)
                    if count<24 or ratio<.4:
                        rejected.append(dict(reference_t=ref_t,reason='insufficient_inliers',inliers=count,ratio=ratio))
                        continue
                    if count<=best:continue
                    sx=image.shape[1]/self.width;sy=image.shape[0]/self.height
                    scale=np.diag([sx,sy,1.])
                    h=np.asarray(cal.H) @ np.linalg.inv(scale) @ transform @ scale
                    # Validate the actual current floor, rather than accepting the match alone.
                    from .calibcheck import frame_fit_detail
                    small=Calibration(H=(h @ np.linalg.inv(scale)).tolist(),dst_m=cal.dst_m,
                                      frame='full')
                    fit=frame_fit_detail(image,small,n_samples=20)
                    if fit['ratio']<1.25:
                        rejected.append(dict(reference_t=ref_t,reason='floor_fit_failed',fit=fit))
                        continue
                    result=Calibration(H=h.tolist(),src_px=cal.src_px,dst_m=cal.dst_m,
                                       frame='full',frame_size=[self.width,self.height],
                                       method='manual-registered')
                    chosen=ref_t;best=count;ratio_out=ratio
        detail={'t':t,'matched':result is not None,'reference_t':chosen,
                'inliers':best,'inlier_ratio':round(ratio_out,3),'source':'direct' if result else 'unmatched',
                'direct_rejections':rejected}
        direct[t]=(result,detail)
        return result,dict(detail)

    def _recover_local(self,t):
        options=self.options
        image=self.frame(t)
        if image is None:return None,dict(reason='frame_unavailable',anchor_times=[])
        keypoints,descriptor=self.features(image)
        if descriptor is None:return None,dict(reason='no_features',anchor_times=[])
        attempts=[];candidates=[]
        offsets=[]
        for step in range(1,math.ceil(options.max_anchor_gap_s/options.anchor_step_s)+1):
            offsets.extend((-step*options.anchor_step_s,step*options.anchor_step_s))
        for offset in offsets[:options.max_anchor_candidates]:
            anchor_t=round(t+offset,3)
            if anchor_t<0 or abs(offset)>options.max_anchor_gap_s:continue
            if any(min(t,anchor_t)<cut<=max(t,anchor_t) for cut in self.camera_cuts):
                attempts.append(dict(anchor_t=anchor_t,reason='known_cut_boundary'))
                continue
            # Never call at(anchor_t): recovered matrices cannot become anchors.
            cal,direct_detail=self._direct_at(anchor_t)
            if cal is None:continue
            if anchor_t not in self._local_features:
                ref_image=self.frame(anchor_t)
                if ref_image is None:continue
                self._local_features[anchor_t]=self.features(ref_image)
                while len(self._local_features)>options.image_cache_size:
                    self._local_features.popitem(last=False)
            ref_kp,ref_desc=self._local_features[anchor_t]
            if ref_desc is None:continue
            pairs=self.matcher.knnMatch(descriptor,ref_desc,k=2)
            matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.7*p[1].distance]
            row=dict(anchor_t=anchor_t,matches=len(matches),root_reference_t=direct_detail['reference_t'])
            if len(matches)<options.min_matches:
                attempts.append(dict(row,reason='insufficient_matches'));continue
            src=np.float32([keypoints[m.queryIdx].pt for m in matches])
            dst=np.float32([ref_kp[m.trainIdx].pt for m in matches])
            transform,inliers=cv2.findHomography(src,dst,cv2.RANSAC,options.ransac_px)
            if transform is None or inliers is None:
                attempts.append(dict(row,reason='no_homography'));continue
            count=int(inliers.sum());ratio=count/len(matches)
            row.update(inliers=count,inlier_ratio=ratio)
            if count<options.min_inliers or ratio<options.min_inlier_ratio:
                attempts.append(dict(row,reason='insufficient_inliers'));continue
            sx=image.shape[1]/self.width;sy=image.shape[0]/self.height
            scale=np.diag([sx,sy,1.])
            h=np.asarray(cal.H)@np.linalg.inv(scale)@transform@scale
            if not np.isfinite(h).all() or abs(np.linalg.det(h))<1e-12:
                attempts.append(dict(row,reason='unsafe_homography'));continue
            current=Calibration(H=h.tolist(),dst_m=cal.dst_m,frame='full',
                                frame_size=[self.width,self.height],method='manual-registered-local')
            from .calibcheck import frame_fit_detail
            fit=frame_fit_detail(image,Calibration(H=(h@np.linalg.inv(scale)).tolist(),
                                                  dst_m=cal.dst_m,frame='full'),n_samples=20)
            row['fit']=fit
            if fit['ratio']<options.min_floor_fit:
                attempts.append(dict(row,reason='floor_fit_failed'));continue
            ref_image=self.frame(anchor_t)
            preview_cal=Calibration(H=(np.asarray(cal.H)@np.linalg.inv(scale)).tolist(),frame='full')
            appearance=floor_photometric_support(image,ref_image,transform,preview_cal,options)
            row['photometric']=appearance
            if not appearance['ok']:
                attempts.append(dict(row,reason='floor_appearance_changed'));continue
            row['reason']='geometric_candidate'
            attempts.append(row);candidates.append((current,row))
        # Require distinct observed anchors with mutually consistent floor
        # estimates. A high white-line score from one patch is insufficient.
        groups=[]
        for group in combinations(candidates,options.min_anchor_support):
            if all(registration_consistent(a[0],b[0],(self.width,self.height),options)
                   for a,b in combinations(group,2)):
                groups.append(group)
        if not groups:
            return None,dict(reason='insufficient_consistent_anchors',anchor_times=[],attempts=attempts)
        chosen=max(groups,key=lambda group:sum(r['inliers'] for _,r in group))
        best=max(chosen,key=lambda pair:(pair[1]['inliers'],-abs(pair[1]['anchor_t']-t)))
        # Conflicting well-supported hypotheses must stay unknown.
        if any(not registration_consistent(best[0],other[0],(self.width,self.height),options)
               for group in groups for other in group):
            return None,dict(reason='ambiguous_local_geometry',anchor_times=[],attempts=attempts)
        return best[0],dict(reason='multi_anchor_registered',anchor_times=[r['anchor_t'] for _,r in chosen],
                            root_reference_times=[r['root_reference_t'] for _,r in chosen],
                            prediction=False,max_anchor_gap_s=options.max_anchor_gap_s,attempts=attempts)


def repair_positions(rt, video, calibration_file, progress=None, *, registration_options=None, camera_cuts=()):
    """Reuse stored pixel detections, preserving shot decisions and unknown locations."""
    from .tactics import PlayerSample
    projector=MarkedProjector(video,calibration_file,rt.width,rt.height,
                              options=registration_options,camera_cuts=camera_cuts)
    original_obs=list(rt.player_obs)
    frame_cache={}
    def at(t):
        rounded=round(float(t)*4)/4
        if rounded not in frame_cache:
            frame_cache[rounded]=projector.at(rounded)
        return frame_cache[rounded]
    samples=[];observations=[]
    try:
        for i,obs in enumerate(original_obs):
            cal=at(obs['t'])
            if cal is None:continue
            x,y=cal.to_court(obs['foot_x'],obs['foot_y'])
            if not cal.in_court(x,y,tol=.12):continue
            samples.append(PlayerSample(t=obs['t'],player_id=obs['player_id'],team=obs['team'],
                                        x=round(x,3),y=round(y,3),conf=obs.get('conf',1.)))
            observations.append(obs)
            if progress and i%2000==0:progress(i,len(original_obs))
        rt.player_track=sorted(samples,key=lambda p:p.t)
        rt.player_obs=observations
        events=(rt.detections_meta.get('legacy_shots') or {}).get('events',[])
        recovered=0
        for attempt in rt.attempts:
            if attempt.location_source!='rim_placeholder':continue
            event=next((e for e in events if abs(float(e.get('release_t',e['t']))-attempt.t)<.02),None)
            if not event or event.get('release_source')!='player_feet' or not event.get('release_xy'):continue
            cal=projector.at(attempt.t)
            if cal is None:continue
            x,y=cal.to_court(*event['release_xy'])
            if not cal.in_court(x,y,tol=.12):continue
            attempt.x=x;attempt.y=y;attempt.location_source='registered_player_feet'
            attempt.location_estimated=True
            recovered+=1
        # Detector candidates and airborne centers are not floor ball tracks.
        # Preserve validated ball evidence; do not invent possession or passes.
        meta=rt.detections_meta
        for key in ['calibration_rejected','calibration_position_unverified','tactics_frame_drop']:
            meta.pop(key,None)
        meta.update(calibration_valid=True,calibration_fit=multical_fit(projector.mc),
            calibration_for_value={'ok':True,'basis':'ground_plane','reason':'已按对应手标画面跟随镜头匹配'},
            player_track_source='manual_registered',
            player_track={'samples':len(samples),'players':len({p.player_id for p in samples}),'calibration_valid':True},
            marked_projection={'frames':projector.audit,'recovered_shot_locations':recovered,
                'input_observations':len(original_obs),'kept_observations':len(observations),
                'note':'只使用能匹配手标画面且通过白线检查的时刻；缺少对应镜头时保留未知。'})
    finally:projector.close()
    return rt
