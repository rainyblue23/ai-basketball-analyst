"""Track a user-boxed hoop through one continuous camera shot."""
from __future__ import annotations

import cv2
import numpy as np

from .legacy_shots.detector import Det


class ManualHoopLock:
    """Seed from the marked frame, then match its appearance in a local window.

    Pixel coordinates must not survive a broadcast cut.  On a cut this tracker
    stops and the learned rim detector takes over; another camera angle needs its
    own user box rather than pretending the old coordinates still apply.
    """
    def __init__(self, hoop, fps: float):
        self.hoop=hoop;self.fps=max(1.,float(fps));self.template=None
        self.box=None;self.active=True;self.seeded=False;self.matches=0;self.misses=0

    def reset_on_cut(self):
        self.active=False;self.box=None

    def update(self, frame, t: float, cut: bool=False):
        target=float(getattr(self.hoop,'t',0.) or 0.)
        # A lock for a later marked camera shot must survive earlier cuts while it
        # is still waiting for its own timestamp.
        if cut and (self.seeded or t+(.51/self.fps)>=target):self.reset_on_cut()
        if not self.active:return None
        if not self.seeded:
            if t+(.51/self.fps)<target:return None
            h,w=frame.shape[:2];rx=float(self.hoop.rx);ry=float(self.hoop.ry)
            x1=max(0,int(round(self.hoop.cx-rx)));y1=max(0,int(round(self.hoop.cy-ry)))
            x2=min(w,int(round(self.hoop.cx+rx)));y2=min(h,int(round(self.hoop.cy+ry)))
            if x2-x1<6 or y2-y1<4:return None
            self.template=cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
            if float(np.std(self.template))<5:return None
            self.box=(x1,y1,x2,y2);self.seeded=True
            return Det('rim_manual_lock',1.,tuple(map(float,self.box)))
        x1,y1,x2,y2=self.box;bw=x2-x1;bh=y2-y1;h,w=frame.shape[:2]
        radius=int(max(80,3*bw,5*bh))
        sx1=max(0,int((x1+x2)/2-radius));sy1=max(0,int((y1+y2)/2-radius))
        sx2=min(w,int((x1+x2)/2+radius));sy2=min(h,int((y1+y2)/2+radius))
        search=cv2.cvtColor(frame[sy1:sy2,sx1:sx2],cv2.COLOR_BGR2GRAY)
        if search.shape[0]<bh or search.shape[1]<bw:return None
        score=cv2.matchTemplate(search,self.template,cv2.TM_CCOEFF_NORMED)
        _,best,_,where=cv2.minMaxLoc(score)
        if not np.isfinite(best) or best<.58:
            self.misses+=1
            return None
        nx1=sx1+where[0];ny1=sy1+where[1]
        self.box=(nx1,ny1,nx1+bw,ny1+bh);self.matches+=1
        return Det('rim_manual_lock',min(.99,.7+.29*float(best)),tuple(map(float,self.box)))

    def summary(self):
        return {'seeded':self.seeded,'appearance_matches':self.matches,
                'appearance_misses':self.misses,'stopped_at_cut':not self.active}
