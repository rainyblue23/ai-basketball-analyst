import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi.responses import FileResponse
from aihoop import api
from aihoop.rules import build_shots
class CorrectionIntegration(unittest.TestCase):
 def test_http_frame_save_failure_and_sample(self):
  import cv2,numpy as np
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);video=root/'source.avi';w=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10,(32,24))
   for i in range(10):w.write(np.full((24,32,3),i*20,np.uint8))
   w.release()
   async def get_video(job_id):return FileResponse(video)
   with patch.object(api,'ROOT',root),patch.object(api,'get_video',get_video),patch('aihoop.auth.read_session',return_value='test'):
    client=TestClient(api.app)
    self.assertEqual(client.get('/api/games/job/ball-feedback/frame?t=0.35').status_code,200)
    body={'t':.35,'boxes':[{'kind':'ball','xyxy':[.2,.2,.4,.4]}]}
    response=client.post('/api/games/example_test/ball-feedback',json=body)
    self.assertEqual(response.status_code,200);self.assertTrue(response.json()['saved'])
    feedback_id=response.json()['id']
    rows=list((root/'data/ball_feedback').glob('*/record.json'));self.assertEqual(len(rows),1)
    self.assertEqual(json.loads(rows[0].read_text(encoding='utf-8'))['frame_index'],3)
    self.assertEqual(client.get('/api/ball-feedback?status=pending').json()['total'],1)
    denied=client.post(f'/api/ball-feedback/{feedback_id}/review',json={
     'decision':'approved','reviewer':'qa','frame_complete':False})
    self.assertEqual(denied.status_code,400)
    approved=client.post(f'/api/ball-feedback/{feedback_id}/review',json={
        'decision':'approved','reviewer':'qa','frame_complete':True,
        'conditions':['far_small'],'source_match_id':'match-test-001'})
    self.assertEqual(approved.status_code,200);self.assertTrue(approved.json()['training_approved'])
    self.assertEqual(client.post('/api/games/job/ball-feedback',json={'t':3,'boxes':body['boxes']}).status_code,400)
    self.assertEqual(len(list((root/'data/ball_feedback').glob('*/record.json'))),1)
    self.assertEqual(client.post('/api/games/example_test/shots/add',json={}).status_code,403)
 def test_manual_endpoint_rebuilds_statistics(self):
  from aihoop.sources import RawTrack
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);RawTrack(fps=30,duration=10).save(str(root/'raw_track.json'))
   with patch.object(api,'_out_dir',return_value=root),patch('aihoop.auth.read_session',return_value='test'):
    client=TestClient(api.app)
    for t,result in [(1,'made'),(2,'missed'),(3,'unknown')]:
     r=client.post('/api/games/feedback_test/shots/add',json={'t':t,'team':'home','value':2,'result':result})
     self.assertEqual(r.status_code,200,r.text)
    self.assertEqual(r.json()['score'],{'home':2,'away':0})
    timeline=r.json()['timeline'];self.assertEqual(len(timeline),3)
    self.assertEqual([e['result'] for e in timeline],['made','missed','unknown'])
    self.assertIsNone(timeline[-1]['made']);self.assertEqual(timeline[-1]['points'],0)
    self.assertTrue(all('location_unknown' in e['tags'] for e in timeline))
    before=(root/'manual_attempts.json').read_bytes()
    self.assertEqual(client.post('/api/games/feedback_test/shots/add',json={'t':10,'team':'home','value':2}).status_code,400)
    self.assertEqual(before,(root/'manual_attempts.json').read_bytes())
 def test_manual_mixed_unknown_home_away_is_atomic(self):
  from aihoop.sources import RawTrack
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);RawTrack(fps=30,duration=10).save(str(root/'raw_track.json'))
   with patch.object(api,'_out_dir',return_value=root),patch('aihoop.auth.read_session',return_value='test'):
    client=TestClient(api.app)
    cases=[{'t':1},{'t':2,'team':'home','result':'missed'},
           {'t':3,'team':'away','result':'made'}]
    for body in cases:
     r=client.post('/api/games/mixed/shots/add',json=body)
     self.assertEqual(r.status_code,200,r.text)
    timeline=r.json()['timeline']
    self.assertEqual([e['result'] for e in timeline],['unknown','missed','made'])
    self.assertEqual(r.json()['score'],{'home':0,'away':2})
    self.assertTrue(all('location_unknown' in e['tags'] for e in timeline))
    records=json.loads((root/'manual_attempts.json').read_text(encoding='utf-8'))
    self.assertEqual([x['player_id'] for x in records],
                     ['MANUAL_UNKNOWN','MANUAL_HOME','MANUAL_AWAY'])
    before=(root/'manual_attempts.json').read_bytes()
    with patch.object(api,'run_pipeline',side_effect=RuntimeError('rebuild failed')):
     with self.assertRaises(RuntimeError):api.asyncio.run(api.add_manual_shot('mixed',api.ManualShot(t=4,team='home')))
    self.assertEqual(before,(root/'manual_attempts.json').read_bytes())
 def test_manual_three_states_and_no_fake_location(self):
  for result,made in [('made',True),('missed',False),('unknown',None)]:
   shot=build_shots([{'t':1,'x':0,'y':0,'team':'home','manual':True,'manual_result':result,'made':made,'conf':1,'forced_value':2,'location_source':'rim_placeholder','counts_for_score':made is not None}])[0]
   self.assertEqual(shot.result,result);self.assertFalse(shot.location_known)
   if made is None:self.assertFalse(shot.counts_for_score);self.assertIn('needs_review',shot.tags)
 def test_unknown_not_overridden_by_scoreboard(self):
  a={'t':1,'x':0,'y':0,'team':'home','manual':True,'manual_result':'unknown','forced_value':2,'counts_for_score':False}
  s=build_shots([a],scoreboard_events=[{'t':2,'team':'home','delta':2}])[0]
  self.assertEqual(s.result,'unknown')
if __name__=='__main__':unittest.main()
