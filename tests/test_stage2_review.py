import copy
import pytest
from scripts.serve_match_labeling import validate
from scripts.prepare_stage2_review import audit_source_splits

ITEM={'start_s':19.5,'end_s':23.5,'images':['frame_000600.jpg']}
def base():
 return {'shots':[],'frames':[], 'shots_complete':False,'frames_complete':False,'review':{'reviewer':'','status':'pending','is_shot':'pending','is_replay':'pending','result':'pending','release_interval':None}}

def test_completed_unknown_is_not_training_or_approval():
 d=base();d['review'].update(reviewer='human',status='completed',is_shot='unknown',is_replay='unknown',result='unknown');d['shots_complete']=True
 d['training_approved']=True
 r=validate(d,ITEM)
 assert r['training_approved'] is False and r['review_status']=='human_completed'

@pytest.mark.parametrize('change',[{'status':'completed'},{'release_interval':[19.,21.]},{'release_interval':[22.,21.]},{'release_interval':[21.,float('nan')]},{'is_shot':'no','result':'made'}])
def test_invalid_or_incomplete_review_rejected(change):
 d=base();d['review'].update(change)
 with pytest.raises(ValueError):validate(d,ITEM)

def test_no_shot_requires_empty_shots_and_can_be_complete():
 d=base();d['shots_complete']=True;d['review'].update(reviewer='human',status='completed',is_shot='no',is_replay='no',result='not_applicable')
 assert validate(d,ITEM)['shots']==[]
 d['shots']=[{'release_s':21.,'result':'unknown','value':None}]
 with pytest.raises(ValueError):validate(d,ITEM)

def test_person_and_rim_complete_do_not_make_ball_complete():
 d=base();d['frames']=[{'image':'frame_000600.jpg','visibility':'pending','rims_complete':True,'persons_complete':True,'boxes':[{'kind':'person','role':'REFEREE','xyxy':[.1,.1,.2,.5]}]}]
 validate(d,ITEM)
 d['frames_complete']=True
 with pytest.raises(ValueError):validate(d,ITEM)

def test_known_clip_transcode_match_and_duplicate_sha_leaks():
 a={'source_match_id':'match1','split':'Development','assets':[{'sha256':'x'}]}
 b={'source_match_id':'match1','split':'Validation','leakage_review_status':'approved','assets':[{'sha256':'y'}]}
 assert any('match_cross_split' in e for e in audit_source_splits([a,b]))
 b['source_match_id']='alias';b['assets'][0]['sha256']='x'
 assert any('sha_cross_split' in e for e in audit_source_splits([a,b]))
 b['assets'][0]['sha256']='y';b['leakage_review_status']='pending'
 assert any('unapproved_source' in e for e in audit_source_splits([a,b]))


def test_legacy_annotations_remain_compatible():
 d=base();d.pop('review');d['shots']=[{'release_s':21.,'result':'missed','value':2}]
 assert validate(d,ITEM)['shots']==d['shots']


def test_http_roundtrip_and_origin_isolation(tmp_path):
 import socket,subprocess,sys,json,time,urllib.request,urllib.error
 from pathlib import Path
 task=tmp_path/'task';task.mkdir();(task/'frame_000600.jpg').write_bytes(b'image')
 (tmp_path/'manifest.json').write_text(json.dumps([dict(ITEM,id='task',video=str(task/'frame_000600.jpg'),source_match_id='dev1',video_sha256='sha1',original_sha256='original1')]))
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 process=subprocess.Popen([sys.executable,'scripts/serve_match_labeling.py','--batch',str(tmp_path),'--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:
  url=f'http://127.0.0.1:{port}'
  for _ in range(100):
   try:
    with urllib.request.urlopen(url+'/manifest') as r:assert len(json.load(r))==1
    break
   except OSError:time.sleep(.02)
  else:raise AssertionError('Review server did not start')
  payload=base();payload['training_approved']=True
  body=json.dumps(payload).encode()
  bad=urllib.request.Request(url+'/annotations/task',body,{'Content-Type':'application/json','Origin':'https://untrusted.invalid'})
  with pytest.raises(urllib.error.HTTPError) as err:urllib.request.urlopen(bad)
  assert err.value.code==403 and not (task/'annotations.json').exists()
  req=urllib.request.Request(url+'/annotations/task',body,{'Content-Type':'application/json','Origin':url})
  with urllib.request.urlopen(req) as r:assert json.load(r)['saved']
  with urllib.request.urlopen(url+'/annotations/task') as r:saved=json.load(r)
  assert saved['video_sha256']=='sha1' and saved['source_match_id']=='dev1' and saved['training_approved'] is False
  assert saved['review']['status']=='pending' and saved['saved_at']
 finally:process.terminate();process.wait(timeout=5)


def test_skipped_duplicate_is_not_reviewed_absence():
 d=base();d['frames']=[{'image':'frame_000600.jpg','visibility':'pending','boxes':[],'review_skip':'redundant_or_not_reviewed'}]
 assert validate(d,ITEM)['frames'][0]['visibility']=='pending'
 assert not d['training_approved'] and not d['frames_complete']
 d['frames_complete']=True
 with pytest.raises(ValueError):validate(d,ITEM)
