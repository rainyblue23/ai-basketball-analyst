import numpy as np
import cv2
import pytest
from aihoop.frame_motion import validated_forward_motion
from aihoop.legacy_shots.settings import GeneralVisionOptions
from aihoop.legacy_shots.stream import LegacyShotStream


def test_cached_descriptors_reproduce_motion_and_expire_across_gap():
 rng=np.random.default_rng(43);a=rng.integers(0,255,(240,420,3),dtype=np.uint8)
 options=GeneralVisionOptions().model_dump();cache={};prev=a
 for i in range(1,4):
  now=cv2.warpAffine(a,np.float32([[1,0,i*2],[0,1,i]]),(420,240))
  cv2.setRNGSeed(1);old=validated_forward_motion(prev,now,options)
  cv2.setRNGSeed(1);new=validated_forward_motion(prev,now,options,feature_cache=cache,frame_index=i)
  assert old['ok']==new['ok'];assert new['descriptor_cache_hit']==(i>1)
  if old['ok']:assert np.allclose(old['forward_H'],new['forward_H'])
  prev=now
 gap=validated_forward_motion(prev,now,options,feature_cache=cache,frame_index=10)
 assert gap['descriptor_cache_hit'] is False


def test_new_camera_options_default_off():
 o=GeneralVisionOptions()
 assert not o.camera_feature_cache and not o.camera_demand_only


def test_demand_skip_without_consumable_geometry_does_not_revive_rim(monkeypatch):
 import aihoop.frame_motion as fm
 calls=[]
 monkeypatch.setattr(fm,'validated_forward_motion',lambda *a,**k:calls.append(True) or {'ok':False,'forward_H':None})
 s=LegacyShotStream(30,420,height=240,config={'detect':{'general':{'dynamic_rim':True,'camera_demand_only':True,'camera_feature_cache':True}}})
 im=np.zeros((240,420,3),dtype=np.uint8)
 s.observe_camera(0,0,im)
 assert not calls and s.camera_audit['reason']=='geometry_not_consumable'
 r=s.engine.rim;r.seen=1;r.last_seen_t=0.;r.geometry_frame=0;r.geometry_t=0.;r.w=30;r.h=10
 s.observe_camera(1,1/30,im)
 assert len(calls)==1
 s.observe_camera(3,.1,im)
 assert len(calls)==1 and not r.camera_verified
 assert r.last_seen_t==0 and r.status(.1,1.5)=='STALE'
 s.observe_camera(4,.14,im,cut=True)
 assert len(calls)==1 and s._camera_image is not None
