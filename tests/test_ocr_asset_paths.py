from pathlib import Path
import importlib.util
import pytest
from aihoop.ocr_assets import ocr_model_directory,OCR_FILES


def provision(path):
    path.mkdir(parents=True)
    for name in OCR_FILES:(path/name).write_bytes(b'local-model')
    return path


def test_pinned_release_uses_shared_project_assets_without_changing_release(tmp_path,monkeypatch):
    monkeypatch.delenv('AIHOOP_SCOREBOARD_OCR_MODELS',raising=False)
    project=tmp_path/'project';(project/'data').mkdir(parents=True)
    release=project/'deploy/runtime/version';release.mkdir(parents=True)
    (release/'data').symlink_to(project/'data',target_is_directory=True)
    expected=provision(tmp_path/'aihoop_assets/models/easyocr')
    assert ocr_model_directory(project)==expected
    assert ocr_model_directory(release)==expected
    # The actual scoreboard script must pass its own release root to the resolver.
    script=Path(__file__).resolve().parents[1]/'scripts/read_marked_scoreboard.py'
    spec=importlib.util.spec_from_file_location('ocr_relocation_test',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',release)
    assert module._easyocr_model_dir()==expected
    assert sorted(p.name for p in release.iterdir())==['data']


def test_explicit_bad_path_does_not_silently_fall_back(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir()
    provision(tmp_path/'aihoop_assets/models/easyocr')
    missing=tmp_path/'wrong';monkeypatch.setenv('AIHOOP_SCOREBOARD_OCR_MODELS',str(missing))
    assert ocr_model_directory(project)==missing


def test_project_model_directory_and_partial_models(tmp_path,monkeypatch):
    monkeypatch.delenv('AIHOOP_SCOREBOARD_OCR_MODELS',raising=False)
    project=tmp_path/'project';project.mkdir()
    target=provision(project/'models/easyocr')
    assert ocr_model_directory(project)==target
    (target/OCR_FILES[0]).unlink()
    assert ocr_model_directory(project)!=target


@pytest.mark.parametrize('disabled',['off','none',''])
def test_jersey_explicit_disable_is_preserved(monkeypatch,disabled):
    from aihoop.jersey_numbers import model_path
    monkeypatch.setenv('AIHOOP_JERSEY_MODEL',disabled)
    assert model_path() is None


@pytest.mark.parametrize('options,expected',[(None,True),({'ball_rim_recovery':False},False),({'ball_rim_recovery':True},True)])
def test_manual_hoops_do_not_override_independent_roi_configuration(options,expected):
    from aihoop.sources import VideoSource
    from aihoop.court import Calibration
    from aihoop.hoop import Hoop
    hoop=Hoop(cx=200,cy=100,rx=30,ry=10)
    source=VideoSource('not-decoded-in-this-test.mp4',Calibration(method='unavailable'),
                       manual_hoop=hoop,manual_hoops=[hoop],legacy_detect=options)
    assert source.legacy_detect['ball_rim_recovery'] is expected
    assert source.manual_hoop is hoop


@pytest.mark.parametrize('ball_roi,rim_roi',[(False,False),(True,False),(False,True),(True,True)])
def test_offline_recovery_respects_roi_switches_and_records_audits(tmp_path,monkeypatch,ball_roi,rim_roi):
    import cv2
    import numpy as np
    from types import SimpleNamespace
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    import experiment_score_recovery as experiment
    video=tmp_path/'frames.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),30,(160,120))
    for _ in range(8):writer.write(np.zeros((120,160,3),np.uint8))
    writer.release();calls=[]
    def recovery(name):
        def run(*args):calls.append(name);return [],dict(ran=True,reason='test_crop',candidates=[])
        return run
    monkeypatch.setattr(experiment,'recover_region',recovery('ball_recovery'))
    monkeypatch.setattr(experiment,'recover_rim',recovery('rim_recovery'))
    model=SimpleNamespace(predict=lambda *a,**k:[SimpleNamespace(names={},boxes=[])])
    result=experiment.reanalyze(video,dict(start_s=0.,end_s=.1),model,
        dict(ball_roi_recovery=ball_roi,ball_rim_recovery=rim_roi),{i:{} for i in range(8)})
    expected={name for name,on in [('ball_recovery',ball_roi),('rim_recovery',rim_roi)] if on}
    assert set(calls)==expected
    assert {name for name in ('ball_recovery','rim_recovery') if name in result['frames'][0]}==expected
