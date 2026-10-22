import unittest
from aihoop.replay_overlay import detection_overlay

class ReplayOverlayTest(unittest.TestCase):
    def test_only_observations(self):
        raw = {'width':960, 'height':540, 'detections_meta':{'legacy_shots':{'frames':[
            {'t':0, 'ball':{'xyxy':[1,2,11,12]}, 'rim':None,
             'tracked_rim':{'fresh':False,'cx':10,'cy':10},
             'persons':[{'xyxy':[20,30,50,100],'track_id':'T1'}]},
            {'t':1,'ball':{'xyxy':[1,2,11,12],'predicted':True},'persons':[]}]}}}
        result = detection_overlay(raw)
        self.assertTrue(result['available'])
        self.assertEqual(result['frames'][0]['players'][0]['id'],'T1')
        self.assertIsNone(result['frames'][0]['rim'])
        self.assertIsNone(result['frames'][1]['ball'])
        self.assertNotIn('made',result['frames'][0])
    def test_old_player_boxes_and_missing(self):
        self.assertFalse(detection_overlay({})['available'])
        d=detection_overlay({'width':960,'height':540,'player_obs':[
            {'t':1,'box':[1,2,10,20],'player_id':'T1'},
            {'t':1,'box':[20,30,40,80],'player_id':'T2'},
            {'t':2,'box':[float('nan'),0,1,1]}]})
        self.assertEqual(len(d['frames']),1)
        self.assertEqual(len(d['frames'][0]['players']),2)
        self.assertIsNone(d['frames'][0]['ball'])

    def test_large_spectator_box_is_not_shown_as_ball(self):
        raw={'width':1920,'height':1080,'detections_meta':{'legacy_shots':{'frames':[
            {'t':12.0,'ball':{'xyxy':[0,284,36,350]},'persons':[]}]}}}
        result=detection_overlay(raw)
        self.assertIsNone(result['frames'][0]['ball'])

    def test_camera_compensated_static_run_is_suppressed(self):
        frames=[]
        for i in range(5):
            dx=i*8
            persons=[{'xyxy':[100+dx,100,160+dx,400],'track_id':1},
                     {'xyxy':[400+dx,100,460+dx,400],'track_id':2},
                     {'xyxy':[700+dx,100,760+dx,400],'track_id':3}]
            frames.append({'t':i*.2,'ball':{'xyxy':[500+dx,220,524+dx,244]},
                           'persons':persons})
        raw={'width':1920,'height':1080,
             'detections_meta':{'legacy_shots':{'frames':frames}}}
        result=detection_overlay(raw)
        self.assertTrue(all(row['ball'] is None for row in result['frames']))

    def test_short_ball_observation_is_labeled_suspect(self):
        raw={'width':960,'height':540,'detections_meta':{'legacy_shots':{'frames':[
            {'t':1,'ball':{'xyxy':[100,100,116,116]},'persons':[]}]}}}
        self.assertTrue(detection_overlay(raw)['frames'][0]['ball_suspect'])

if __name__=='__main__': unittest.main()
