import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from benchmark_stage2_windows import budget_windows


def test_disabled_budget_uses_evidence_without_known_times_and_never_exceeds_cap():
 frames=[{'frame':i,'t':i/30,'ball':None,'tracked_rim':{}} for i in range(300)]
 events=[{'release_t':x/10,'result':'unknown'} for x in range(100)]
 r=budget_windows(frames,events,30,max_seconds=2,max_windows=2)
 assert r['enabled'] is False and r['formal_statistics_write'] is False
 assert r['selected_frame_count']<=60 and len(r['windows'])<=2
 assert all(w['reason']=='forward_candidate' for w in r['windows'])
 assert budget_windows(frames,[],30)['windows']==[]


def test_score_plus_one_is_not_budgeted_as_a_field_goal():
 frames=[{'frame':i,'t':i/30} for i in range(300)]
 assert budget_windows(frames,[],30,score_facts=[{'delta':1,'t':6.}])['windows']==[]
 assert budget_windows(frames,[],30,score_facts=[{'delta':2,'t':6.}])['windows']


def test_empty_and_zero_budget():
 assert budget_windows([],[],30)['selected_frame_count']==0
 assert not budget_windows([{'frame':0,'t':0}], [{'t':0}],30,max_seconds=0)['windows']
