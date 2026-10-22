import copy
from aihoop.scoreboard_fusion import apply_scoreboard, score_changes


def reference():
    return {'screen_start':{'left':88,'right':86},'screen_final':{'left':88,'right':88},
            'ocr_hit':7,'n_crops':7,'readings':[
                {'t':t,'pair':[88,86] if t<9.5 else [88,88],'confidence':.96}
                for t in [8,8.5,9,9.5,10]]}


def attempt(**kwargs):
    return dict(t=4.,decision_t=6.9,team='home',player_id='p',x=2,y=7,
                made=False,conf=.8,source='legacy_ball_rim',tags=[],
                counts_for_score=True,location_source='player_feet',**kwargs)


def metadata():
    return {'scoreboard_reference_only':reference(),
            'scoreboard_team_map':{'left':'away','right':'home'}}


def test_mapped_continuous_score_confirms_existing_shot_and_actual_value():
    original=[attempt()];out,board=apply_scoreboard(original,metadata())
    assert original[0]['made'] is False  # saved visual evidence is not overwritten
    assert out[0]['made'] is True
    assert out[0]['forced_value']==2 and not out[0]['value_assumed']
    assert out[0]['x']==2 and out[0]['y']==7
    assert len(board['matched_shots'])==1
    assert len(out)==1


def test_unmapped_score_automatically_confirms_existing_shot_without_reassigning_player():
    m=metadata();m.pop('scoreboard_team_map');original=[attempt()]
    out,board=apply_scoreboard(original,m)
    assert out[0]['made'] is True and out[0]['forced_value']==2
    assert out[0]['player_id']=='p' and out[0]['team']=='home'
    assert board['team_map'] is None and len(board['matched_shots'])==1
    assert original[0]['made'] is False
    m=metadata();m['scoreboard_team_map']={'left':'home','right':'away'}
    assert apply_scoreboard(original,m)[0]==original


def test_unmapped_ambiguous_changes_free_throws_and_unknown_teams_stay_safe():
    m={'scoreboard_reference_only':reference()}
    # A field goal candidate cannot claim a free throw's single point.
    r=m['scoreboard_reference_only']
    for row in r['readings']:
        if row['t']>=9.5:row['pair']=[88,87]
    original=attempt()
    assert apply_scoreboard([original],m)[0]==[original]
    original=attempt(is_free_throw=True)
    out,_=apply_scoreboard([original],m)
    assert out[0]['made'] and out[0]['forced_value']==1
    # An unknown team can have its outcome confirmed, but earns no team credit.
    original=attempt();original['team']='unknown';original['tags']=['team_unknown']
    out,_=apply_scoreboard([original],{'scoreboard_reference_only':reference()})
    assert out[0]['made'] and not out[0]['counts_for_score']
    assert out[0]['team']=='unknown'
    original=attempt(forced_value=3,value_assumed=False)
    assert apply_scoreboard([original],{'scoreboard_reference_only':reference()})[0]==[original]


def test_two_score_changes_of_different_teams_cannot_claim_one_unmapped_shot():
    r=reference()
    r['readings'] += [{'t':t,'pair':[90,88],'confidence':.99} for t in (10.1,10.3,10.4)]
    original=[attempt()]
    out,board=apply_scoreboard(original,{'scoreboard_reference_only':r})
    assert len(board['events'])==2
    assert out==original and not board['matched_shots']


def test_cut_during_shot_or_absence_of_change_does_not_override_outcome():
    m=metadata();m['legacy_shots']={'frames':[{'t':5.,'cut':True}]}
    original=[attempt()]
    assert apply_scoreboard(original,m)[0]==original
    m=metadata()
    for row in m['scoreboard_reference_only']['readings']:row['pair']=[88,86]
    original=[attempt()];original[0]['made']=None
    assert apply_scoreboard(original,m)[0]==original


def test_cuts_multi_score_jump_and_missing_reads_do_not_generate_shots():
    m=metadata();m['legacy_shots']={'frames':[{'t':8.,'cut':True}]}
    out,board=apply_scoreboard([attempt()],m)
    assert out[0]['made'] is False and not board['matched_shots']
    r=reference();r['readings'][-1]['pair']=[99,107];r['readings'][-2]['pair']=[99,107]
    events,gaps=score_changes(r)
    assert not events and len(gaps)==1
    out,board=apply_scoreboard([],metadata())
    assert out==[] and board['events'] and not board['matched_shots']


def test_manual_decisions_and_ambiguous_matches_are_not_overwritten():
    original=attempt(manual=True)
    out,board=apply_scoreboard([original],metadata())
    assert out[0]==original and board['matched_shots'][0]['manual_preserved']
    original=[attempt(),attempt()]
    out,board=apply_scoreboard(original,metadata())
    assert out==original and not board['matched_shots']


def test_one_side_stays_stable_when_other_team_scores_next():
    r={'readings':[{'t':t,'pair':values,'confidence':c} for t,values,c in
        [(8,[88,86],.99),(8.5,[88,86],.99),(9,[88,86],.99),
         (9.5,[88,88],.99),(10,[88,88],.68),
         (10.5,[90,88],.99),(11,[90,88],.99),(11.5,[90,88],.99)]]}
    events,gaps=score_changes(r)
    assert [(e['t'],e['screen_side'],e['delta']) for e in events]==[(9.5,'right',2),(10.5,'left',2)]
    assert not gaps


def test_pipeline_automatically_applies_score_to_stats_and_keeps_manual_override(tmp_path):
    from aihoop.sources import RawTrack,Attempt
    from aihoop.model import Player
    from aihoop.pipeline import run_pipeline,PipelineConfig
    rt=RawTrack(duration=12)
    rt.players={'p':Player('p','7号','home')}
    rt.attempts=[Attempt(**attempt())]
    rt.detections_meta=metadata();rt.detections_meta.pop('scoreboard_team_map')
    cfg=PipelineConfig(out_dir=str(tmp_path),make_highlights=False)
    result=run_pipeline(rt,cfg)
    assert result.game['score']=={'home':2,'away':0}
    assert result.game['teams']['home']['stats']['fgm']==1
    assert len(result.game['timeline'])==1
    assert result.game['broadcast_score']['matched_shots'][0]['delta']==2
    cfg.overrides={0:{'made':False}}
    result=run_pipeline(rt,cfg)
    assert result.game['score']=={'home':0,'away':0}


def test_team_map_endpoint_commits_complete_result_and_preserves_raw_visual(tmp_path,monkeypatch):
    from aihoop import api
    from aihoop.sources import RawTrack,Attempt
    from aihoop.model import Player
    from aihoop.pipeline import run_pipeline as real_pipeline
    import json
    from types import SimpleNamespace
    rt=RawTrack(duration=12)
    rt.players={'p':Player('p','7号','home')};rt.attempts=[Attempt(**attempt())]
    rt.detections_meta=metadata();rt.detections_meta.pop('scoreboard_team_map')
    rt.save(str(tmp_path/'raw_track.json'))
    monkeypatch.setattr(api,'_out_dir',lambda _job:tmp_path)
    monkeypatch.setitem(api._mem,'map-test',SimpleNamespace())
    monkeypatch.setattr(api,'_update',lambda *a,**kw:None)
    def run(rt,cfg):
        cfg.make_highlights=False
        return real_pipeline(rt,cfg)
    monkeypatch.setattr(api,'run_pipeline',run)
    result=api.set_scoreboard_team_map('map-test',api.ScoreboardTeamMap(left_team='away'))
    assert len(result['broadcast_score']['matched_shots'])==1
    assert json.loads((tmp_path/'game.json').read_text())['score']['home']==2
    assert RawTrack.load(str(tmp_path/'raw_track.json')).attempts[0].made is False
    old=(tmp_path/'game.json').read_bytes()
    monkeypatch.setattr(api,'run_pipeline',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('failed')))
    import pytest
    with pytest.raises(RuntimeError):api.set_scoreboard_team_map('map-test',api.ScoreboardTeamMap(left_team='home'))
    assert (tmp_path/'game.json').read_bytes()==old
