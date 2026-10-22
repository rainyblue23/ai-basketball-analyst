"""Metric denominators for the isolated baseline collector."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('collect_cv_baseline',
    Path(__file__).resolve().parents[1]/'scripts/collect_cv_baseline.py')
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def test_reviewed_detector_metrics_are_one_to_one_counts():
    result = _module.feedback_metrics({'totals': {
        'frames': 11, 'ground_truth_boxes': 8, 'predictions': 7, 'matched_iou_50': 3}})
    assert (result['tp'], result['fp'], result['fn']) == (3, 4, 5)
    assert result['precision'] == 3/7 and result['recall'] == 3/8
    assert result['f1'] == .4 and result['independent_test'] is False


def test_missing_denominators_are_not_fabricated_zero_accuracy():
    result = _module.feedback_metrics({'totals': {'frames': 1}})
    assert result['precision'] is None and result['recall'] is None
    assert result['f1'] is None


def test_no_predictions_with_labelled_ball_is_zero_recall():
    result = _module.feedback_metrics({'totals': {
        'frames': 1, 'ground_truth_boxes': 1, 'predictions': 0, 'matched_iou_50': 0}})
    assert result['precision'] is None and result['recall'] == 0 and result['f1'] == 0
