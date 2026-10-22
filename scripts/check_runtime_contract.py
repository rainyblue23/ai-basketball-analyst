"""Fail startup if event models and adapters come from different releases."""
import dataclasses
import inspect
import json
from pathlib import Path


def check():
    from aihoop.sources import Attempt,RawTrack
    from aihoop.model import Shot
    from aihoop.legacy_shots.adapter import to_attempts
    from aihoop.rules import build_shots
    root=Path(__file__).resolve().parents[1]
    required={'release_known','release_evidence','candidate_t','geometry_source'}
    for cls in (Attempt,Shot):
        if not required <= {f.name for f in dataclasses.fields(cls)}:
            raise RuntimeError(f'{cls.__name__} is missing event evidence fields; deploy a coherent release')
        if not Path(inspect.getfile(cls)).resolve().is_relative_to(root/'src'):
            raise RuntimeError(f'{cls.__name__} loaded from a different source tree')
    event=dict(type='uncertain',t=2.,release_t=1.,release_known=False,
        release_evidence={'timestamp_estimated':True},candidate_t=1.,geometry_source='measured')
    attempt=to_attempts([event],RawTrack(fps=30,duration=3.))[0]
    shot=build_shots([attempt.to_dict()])[0]
    if shot.release_known is not False or shot.release_evidence!=event['release_evidence']:
        raise RuntimeError('Event evidence was lost between adapter and Shot')
    return dict(ok=True,root=str(root),models=['Attempt','Shot'],evidence_roundtrip=True)


if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False))
