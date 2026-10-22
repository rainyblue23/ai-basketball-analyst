import importlib.util
from pathlib import Path


def test_event_models_and_adapter_have_a_coherent_schema():
    path=Path(__file__).resolve().parents[1]/'scripts/check_runtime_contract.py'
    spec=importlib.util.spec_from_file_location('runtime_contract',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.check()['evidence_roundtrip'] is True


def test_startup_contract_rejects_an_old_loaded_attempt_class(monkeypatch):
    import dataclasses
    import pytest
    import aihoop.sources as sources
    path=Path(__file__).resolve().parents[1]/'scripts/check_runtime_contract.py'
    spec=importlib.util.spec_from_file_location('runtime_contract_old',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(sources,'Attempt',dataclasses.make_dataclass('Attempt',[('t',float)]))
    with pytest.raises(RuntimeError,match='missing event evidence fields'):
        module.check()


def test_paused_scoreboard_fusion_can_be_disabled_without_changing_input(monkeypatch):
    from aihoop.scoreboard_fusion import apply_scoreboard
    attempts=[dict(t=1.,made=None)]
    monkeypatch.setenv('AIHOOP_DISABLE_SCOREBOARD_FUSION','1')
    result,board=apply_scoreboard(attempts,{'scoreboard_reference_only':{'ocr_hit':5}})
    assert board is None and result==attempts
    result[0]['made']=True
    assert attempts[0]['made'] is None
