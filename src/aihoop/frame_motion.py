"""镜头位移补偿：把不同帧上标的点，映射到同一个参考帧的坐标系。

为什么需要它（用户实测结论）：
  在同一段镜头内平移的几帧里，同一个球场特征点的**像素位置是不同的**；
  而标定要求所有点在同一坐标系里。实测证据：
    t=101.46s 的两个点误差 6.6m / 2.78m（同帧自洽），
    t=34.69s 的点误差 483m（跨镜头，完全对不上）。
  所以要先把各帧的点"搬"到同一帧的坐标系，再来解单应矩阵。

做法：
  1. 对相邻采样帧估计**背景单应矩阵**（ORB 特征匹配 + RANSAC）；
  2. 用内点率判断这两帧是否属于**同一镜头**（剪接处内点率会很低）；
  3. 同一镜头内的帧链式变换到参考帧；跨剪接的地方断开（分成不同 segment）；
  4. 每个 segment 内的点映射到该段第一帧，再解球场标定。

这个模块只做"几何"，不解球场标定 —— 职责单一，便于单独验证。
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


def _grab(video: str, t: float, max_side: int = 960):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None, None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t * fps))))
    ok, fr = cap.read()
    cap.release()
    if not ok:
        return None, None
    h, w = fr.shape[:2]
    scale = 1.0
    if max(h, w) > max_side:
        scale = max_side / float(max(h, w))
        fr = cv2.resize(fr, (int(w * scale), int(h * scale)),
                        interpolation=cv2.INTER_AREA)
    return fr, {"scale": scale, "w": w, "h": h, "fps": fps}


def estimate_motion(video: str, t_a: float, t_b: float,
                    min_matches: int = 12,
                    ok_ratio: float = 0.35) -> dict:
    """估计"把帧 b 的像素映到帧 a 的像素"的单应矩阵。

    返回 {ok, H, ratio, matches, note}；H 是 3x3（b→a）。
    ok=False 表示这两帧大概率**不在同一镜头**（剪接/大幅切换），不该硬连。
    """
    fa, ma = _grab(video, t_a)
    fb, mb = _grab(video, t_b)
    if fa is None or fb is None:
        return {"ok": False, "H": None, "ratio": 0.0, "matches": 0,
                "note": "取帧失败"}
    result=estimate_frame_motion(fa,fb,min_matches=min_matches,ok_ratio=ok_ratio,min_grid_cells=0)
    if result.get('H') is not None:
        H=np.asarray(result['H']);sc=ma['scale']
        if sc!=1.:
            S=np.diag([sc,sc,1.]);H=np.linalg.inv(S) @ H @ S
        result['H']=H.tolist()
    return result


def motion_features(image):
    """ORB descriptors of one resized image; safe to reuse, never a transform."""
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    return cv2.ORB_create(nfeatures=1500).detectAndCompute(gray,None)


def estimate_frame_motion(fa, fb, min_matches=20, ok_ratio=.45, min_grid_cells=3,
                          min_points_per_cell=3, _features=None):
    """Existing ORB/RANSAC geometry on decoded images, with spatial support.

    Screen-fixed logos alone cannot establish scene continuity: inliers must
    occupy multiple cells across the picture, not only broadcast overlays.
    """
    if fa is None or fb is None or fa.shape[:2]!=fb.shape[:2]:
        return {'ok':False,'H':None,'ratio':0.,'matches':0,'grid_cells':0,'note':'missing_or_incompatible_frames'}
    ga = cv2.cvtColor(fa, cv2.COLOR_BGR2GRAY) if fa.ndim==3 else fa
    gb = cv2.cvtColor(fb, cv2.COLOR_BGR2GRAY) if fb.ndim==3 else fb
    (ka,da),(kb,db)=_features if _features is not None else (motion_features(ga),motion_features(gb))
    if da is None or db is None or len(ka) < min_matches or len(kb) < min_matches:
        return {"ok": False, "H": None, "ratio": 0.0, "matches": 0,
                "note": f"特征点太少（a={len(ka)}, b={len(kb)}）"}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(db, da)
    if len(ms) < min_matches:
        return {"ok": False, "H": None, "ratio": 0.0, "matches": len(ms),
                "note": f"匹配太少（{len(ms)}）"}
    ms = sorted(ms, key=lambda m: m.distance)[:300]
    src = np.float32([kb[m.queryIdx].pt for m in ms]).reshape(-1, 1, 2)  # b
    dst = np.float32([ka[m.trainIdx].pt for m in ms]).reshape(-1, 1, 2)  # a
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        return {"ok": False, "H": None, "ratio": 0.0, "matches": len(ms),
                "note": "RANSAC 没找到一致变换"}
    ratio = float(mask.sum()) / float(len(ms))
    inliers=dst.reshape(-1,2)[mask.ravel().astype(bool)]
    height,width=ga.shape[:2]
    from collections import Counter
    cells=Counter((min(2,int(x*3/max(width,1))),min(1,int(y*2/max(height,1)))) for x,y in inliers)
    grid_cells=sum(n>=min_points_per_cell for n in cells.values())
    ok=ratio>=ok_ratio and grid_cells>=min_grid_cells
    return {'ok':ok,'H':H.tolist(),'ratio':round(ratio,3),'matches':len(ms),
            'grid_cells':grid_cells,'note':'continuous_background_geometry' if ok else 'insufficient_distributed_motion_evidence'}


def validated_forward_motion(previous, current, options, *, feature_cache=None, frame_index=None):
    """Distributed background motion, previous ORIGINAL pixels -> current.

    Reject implausible projective/scale estimates. This is an association aid,
    not a new ball/rim observation or a new way to establish shot outcomes.
    """
    if previous is None or current is None or previous.shape!=current.shape:
        return {'ok':False,'forward_H':None,'reason':'missing_previous_image'}
    h,w=current.shape[:2];scale=min(1.,options['camera_max_side']/max(h,w))
    a=cv2.resize(previous,None,fx=scale,fy=scale) if scale<1 else previous
    b=cv2.resize(current,None,fx=scale,fy=scale) if scale<1 else current
    features=None;hit=False
    if feature_cache is not None and frame_index is not None:
        signature=(current.shape,options['camera_max_side'])
        hit=(feature_cache.get('frame')==frame_index-1 and feature_cache.get('signature')==signature)
        previous_features=feature_cache['features'] if hit else motion_features(a)
        current_features=motion_features(b)
        features=(previous_features,current_features)
        feature_cache.clear()
        feature_cache.update(frame=frame_index,signature=signature,features=current_features)
    audit=estimate_frame_motion(a,b,min_matches=options['camera_min_matches'],
        ok_ratio=options['camera_min_ratio'],min_grid_cells=options['camera_min_grid_cells'],_features=features)
    if feature_cache is not None:audit['descriptor_cache_hit']=hit
    if not audit.get('ok'):return dict(audit,forward_H=None,reason='unverified_camera_motion')
    try:
        resize=np.diag([scale,scale,1.]);forward=np.linalg.inv(resize)@np.linalg.inv(np.array(audit['H']))@resize
        forward/=forward[2,2]
        corners=np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
        mapped=cv2.perspectiveTransform(corners,forward).reshape(-1,2)
        change=options['camera_max_scale_change'];edges=np.linalg.norm(np.roll(mapped,-1,axis=0)-mapped,axis=1)/np.array([w,h,w,h])
        if (not np.isfinite(mapped).all() or np.linalg.det(forward[:2,:2])<=0 or
                np.any(edges<1-change) or np.any(edges>1+change) or
                abs(forward[2,0])*w>.15 or abs(forward[2,1])*h>.15):
            return dict(audit,forward_H=None,reason='unsafe_camera_geometry',ok=False)
        return dict(audit,forward_H=forward.tolist(),reason='verified_background_motion')
    except (np.linalg.LinAlgError,ValueError):
        return dict(audit,forward_H=None,reason='singular_camera_motion',ok=False)


def _motion_via_chain(video: str, a: float, b: float,
                      step: float = 0.35) -> dict:
    """a→b 的变换：间隔大时**插入中间帧**逐段估计再串起来。

    为什么不能直接估：实测 57.5→58.4（相隔 0.9s）直接估只有 28% 内点，
    会被误判成剪接；而 56.3→56.9→57.5→58.1… 这样密集链式估计时全段内点率
    39~100%，判定正确。间隔越大、画面里人动得越多，直接估计越不可靠。
    """
    import numpy as _np
    if b - a <= step * 1.5:
        return estimate_motion(video, a, b)
    n = max(2, int(round((b - a) / step)))
    times = [a + (b - a) * i / n for i in range(n + 1)]
    H_total = _np.eye(3)
    ratios, notes = [], []
    for t0, t1 in zip(times, times[1:]):
        m = estimate_motion(video, t0, t1)
        ratios.append(m["ratio"])
        notes.append(m["note"])
        if not m["ok"] or m["H"] is None:
            return {"ok": False, "H": None, "ratio": round(min(ratios), 3),
                    "matches": m.get("matches", 0),
                    "note": (f"链式估计在 {t0:.1f}→{t1:.1f}s 断开（内点率 "
                             f"{m['ratio']:.0%}）——这两帧之间大概有剪接")}
        H_total = H_total @ _np.array(m["H"], dtype=_np.float64)
    return {"ok": True, "H": H_total.tolist(),
            "ratio": round(min(ratios), 3),
            "matches": 0,
            "note": (f"链式估计 {len(times)} 帧通过（最低内点率 "
                     f"{min(ratios):.0%}）")}


def build_segments(video: str, times: list[float],
                   ok_ratio: float = 0.35) -> dict:
    """把采样帧按"是否同一镜头"分组，并给出各帧到该段参考帧的变换。

    返回 {segments: [{times:[...], ref_t, to_ref:{t: H}}], motions:[...]}
    to_ref[t] 是把**帧 t 的像素**映到该段参考帧像素的 3x3 矩阵。
    """
    times = sorted(float(t) for t in times)
    motions = []
    segments = []
    cur = {"times": [times[0]], "ref_t": times[0], "to_ref": {times[0]: np.eye(3)}}
    for a, b in zip(times, times[1:]):
        m = _motion_via_chain(video, a, b)
        motions.append({"from": b, "to": a, **{k: v for k, v in m.items()
                                                if k != "H"},
                        "H": m.get("H")})
        if m["ok"] and m["H"] is not None:
            # 帧 b -> 帧 a，再链到参考帧
            Hab = np.array(m["H"], dtype=np.float64)
            Href_a = cur["to_ref"][a]
            cur["to_ref"][b] = Href_a @ Hab
            cur["times"].append(b)
        else:
            segments.append(cur)
            cur = {"times": [b], "ref_t": b, "to_ref": {b: np.eye(3)}}
    segments.append(cur)
    return {"segments": [{**s, "to_ref": {t: H.tolist()
                                          for t, H in s["to_ref"].items()}}
                         for s in segments],
            "motions": motions}


def warp_point(H, x: float, y: float) -> tuple[float, float]:
    """把一个像素点按 H 映射过去。"""
    v = np.array(H, dtype=np.float64) @ np.array([x, y, 1.0])
    return float(v[0] / v[2]), float(v[1] / v[2])
