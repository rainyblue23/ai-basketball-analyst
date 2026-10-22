from aihoop.tactics import PlayerSample,PlayerIndex,TacticsConfig,build_tactics_frames


def p(t,pid,x=0,y=5,team='home'):return PlayerSample(t,pid,team,x,y)

def cfg(**opts):return TacticsConfig(roster_evidence_filter=True,**opts)

def test_no_future_birth_or_long_holds_or_cut_interpolation():
 i=PlayerIndex([p(1,'new'),p(1.1,'new')],cfg())
 assert not i.at(.9) and not i.at(1.3)
 i=PlayerIndex([p(0,'a'),p(.2,'a',1)],cfg(camera_cuts_s=(.1,)))
 assert not i.at(.1)
 assert not PlayerIndex([p(0,'a'),p(1,'a',1)],cfg()).at(.5)


def test_stale_alias_can_yield_to_supported_same_team_but_observed_close_players_remain():
 i=PlayerIndex([p(0,'old'),p(.1,'new'),p(.2,'new')],cfg())
 assert set(i.at(.1))=={'new'}
 i=PlayerIndex([p(.1,'a'),p(.1,'b',.1,team='away')],cfg())
 assert set(i.at(.1))=={'a','b'}
 frames=build_tactics_frames([p(0,'a'),p(0,'b',.1,team='away')],[],.1,cfg())
 assert len(frames[0]['players'])==2


def test_actual_overcrowding_still_rejected_no_take_first_five():
 i=PlayerIndex([p(0,str(j),j) for j in range(6)],cfg())
 assert not i.at(0)
 assert len(i.at(0,allow_overcrowded=True))==6


def test_impossible_teleport_cannot_make_smooth_fake_path():
 i=PlayerIndex([p(0,'a',-6),p(.1,'a',6)],cfg())
 assert not i.at(.05)


def test_ball_cannot_be_carried_three_seconds_or_through_cut():
 from types import SimpleNamespace
 samples=[p(0,'a'),p(.2,'a'),p(1,'a'),p(1.2,'a')]
 frames=build_tactics_frames(samples,[SimpleNamespace(t=0,x=0,y=5)],1.2,cfg())
 assert all(f['ball'] is None for f in frames if f['t']>.25)
