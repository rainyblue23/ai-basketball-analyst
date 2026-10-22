"""Conservative repeated-image evidence. Never merges official shot records."""
from collections import deque
import cv2
import numpy as np


def visual_hash(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    small=cv2.resize(gray,(32,32)).astype(np.float32)
    dct=cv2.dct(small)[:8,:8].ravel()[1:]
    bits=dct>np.median(dct)
    return int(sum(int(b)<<i for i,b in enumerate(bits)))


class ReplayCandidateLinker:
    def __init__(self,options):self.options=options;self.samples=deque(maxlen=90);self.sequences={};self.links=[]
    def sample(self,frame,t,image):
        if image is not None:self.samples.append((frame,t,visual_hash(image)))
    def observe(self,candidate):
        key=candidate['candidate_id']
        if key in self.sequences:return
        recent=[s for s in self.samples if candidate['timestamp']-.2<=s[1]<=candidate['timestamp']+.2]
        if len(recent)<5:return
        seq=[recent[i* (len(recent)-1)//4][2] for i in range(5)]
        moving=max((a^b).bit_count() for a,b in zip(seq,seq[1:]))>=self.options['replay_min_motion']
        if not moving:return
        for old,(hashes,segment) in self.sequences.items():
            if segment==candidate['segment']:continue
            distances=[(a^b).bit_count() for a,b in zip(seq,hashes)]
            if max(distances)<=self.options['replay_hamming']:
                link=dict(candidate_id=key,possible_same_play_as=old,
                    state='POSSIBLE_REPLAY_UNKNOWN',hamming=distances,
                    play_id='UNKNOWN',automatic_merge=False)
                self.links.append(link);candidate['possible_replay_of']=old
        self.sequences[key]=(seq,candidate['segment'])
