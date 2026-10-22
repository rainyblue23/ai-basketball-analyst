import numpy as np

from aihoop.ball_recovery import motion_candidates
from aihoop.hoop import Hoop
from aihoop.hoop_lock import ManualHoopLock
from aihoop.legacy_shots.detector import Det
from aihoop.legacy_shots.stream import LegacyShotStream


def ball(x, y, w=16, conf=.8):
    return Det('basketball', conf, (x-w/2, y-w/2, x+w/2, y+w/2))


def test_person_head_is_not_selected_as_ball():
    stream=LegacyShotStream(30,1920)
    person=Det('person',.9,(400,100,500,500),track_id=1)
    picked,audit=stream.preview_ball(0,[ball(450,145,40)],persons=[person])
    assert picked is None
    assert audit[0]['selection_reason']=='person_head'


def test_ball_beside_players_head_remains_eligible():
    stream=LegacyShotStream(30,1920,height=1080)
    person=Det('person',.92,(1343,565,1544,788),track_id=1)
    real=Det('basketball',.77,(1496,610,1529,644))
    picked,audit=stream.preview_ball(0,[real],persons=[person])
    assert picked is real
    assert audit[0]['selection_reason']=='selected'


def test_broadcast_logo_sized_box_is_rejected():
    stream=LegacyShotStream(30,1920)
    picked,audit=stream.preview_ball(0,[ball(900,80,90)])
    assert picked is None
    assert audit[0]['selection_reason']=='size_rejected'


def test_tall_spectator_box_cannot_pass_width_only_gate():
    stream=LegacyShotStream(30,1920,height=1080)
    # Rebuild the exact failure shape: narrow enough in x, far too tall in y.
    tall=Det('basketball',.7,(2,275,38,345))
    picked,audit=stream.preview_ball(0,[tall])
    assert picked is None
    assert audit[0]['selection_reason']=='size_rejected'


def test_static_decoy_mask_follows_camera_pan():
    stream=LegacyShotStream(30,1920,height=1080)
    stream.fixed_decoys=[{'cx':500.,'cy':250.,'radius':20.}]
    previous=[Det('person',.9,(100,100,180,400),track_id=1),
              Det('person',.9,(400,100,480,400),track_id=2),
              Det('person',.9,(700,100,780,400),track_id=3)]
    moved=[Det('person',.9,(112,103,192,403),track_id=1),
           Det('person',.9,(412,103,492,403),track_id=2),
           Det('person',.9,(712,103,792,403),track_id=3)]
    stream._follow_camera(previous)
    stream._follow_camera(moved)
    assert stream.fixed_decoys[0]['cx']==512
    picked,audit=stream.preview_ball(1,[ball(512,253,w=16)],persons=moved)
    assert picked is None and audit[0]['selection_reason']=='screen_static'


def test_motion_is_only_a_bounded_candidate_after_recent_detected_ball():
    stream=LegacyShotStream(30,640)
    stream.update(2,2/30,[ball(330,136,12)],persons=())
    motion=np.zeros((360,640),dtype=np.uint8)
    motion[130:142,330:344]=255
    rows,audit=motion_candidates(motion,stream,3,640,360)
    assert audit['ran'] and audit['reason']=='recent_ball'
    assert rows and 'ball' in rows[0].cls_name


def test_motion_near_rim_does_not_create_ball_identity_by_itself():
    stream=LegacyShotStream(30,640)
    rim=Det('rim',.9,(280,190,360,210))
    stream.update(1,1/30,[rim],persons=());stream.update(2,2/30,[rim],persons=())
    motion=np.zeros((360,640),dtype=np.uint8);motion[130:142,330:344]=255
    rows,audit=motion_candidates(motion,stream,3,640,360)
    assert rows==[] and audit['reason']=='no_recent_ball'


def test_changing_upper_scoreboard_box_cannot_start_ball_track():
    stream=LegacyShotStream(30,1920,height=1080)
    picked,audit=stream.preview_ball(0,[ball(1477,153,50)])
    assert picked is None and audit[0]['selection_reason']=='upper_graphic'


def test_manual_hoop_appearance_lock_moves_and_stops_at_cut():
    rng=np.random.default_rng(4)
    texture=rng.integers(0,255,(12,24,3),dtype=np.uint8)
    first=np.zeros((160,240,3),dtype=np.uint8);first[60:72,80:104]=texture
    second=np.zeros_like(first);second[64:76,91:115]=texture
    lock=ManualHoopLock(Hoop(92,66,12,6,t=0),30)
    assert lock.update(first,0).xyxy==(80.,60.,104.,72.)
    moved=lock.update(second,1/30)
    assert moved is not None and moved.xyxy==(91.,64.,115.,76.)
    assert lock.update(second,2/30,cut=True) is None


def test_future_half_court_lock_survives_earlier_cut():
    frame=np.zeros((100,160,3),dtype=np.uint8)
    lock=ManualHoopLock(Hoop(80,40,10,4,t=5),30)
    assert lock.update(frame,1,cut=True) is None
    assert lock.active and not lock.seeded
