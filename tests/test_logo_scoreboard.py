from unittest.mock import patch
import numpy as np
from aihoop.logo_scoreboard import pair, scan


def test_clock_and_partial_labels_are_not_score_pairs():
    assert pair('88 86')==(88,86)
    assert pair('109 120')==(109,120)
    assert pair('11:20 12') is None
    assert pair('3rd 88') is None
    assert pair('88') is None


def test_temporal_confirmation_and_edited_jump_never_invents_shots():
    values=['88 86']*3+['88 88']*3+['90 94']*3+['90 96']*3
    class Capture:
        def get(self,k):return {5:2,7:len(values)}.get(k,0)
        def release(self):pass
    class Frames:
        def __init__(self,cap):pass
        def read(self,index):return True,np.zeros((100,200,3),np.uint8)
    class Reader:
        def readtext(self,*args,**kwargs):
            return [([[0,0],[100,0],[100,20],[0,20]],values.pop(0),.95)]
    with patch('aihoop.logo_scoreboard.cv2.VideoCapture',return_value=Capture()),patch('aihoop.logo_scoreboard.FrameReader',Frames):
        result=scan('fake.mp4',Reader(),[0,0,100,20])
    assert result['screen_start']=={'left':88,'right':86}
    assert result['screen_final']=={'left':90,'right':96}
    assert len(result['screen_events'])==2
    assert len(result['discontinuities'])==1
    assert result['team_mapping_confirmed'] is False
    assert all('team' not in e for e in result['screen_events'])
