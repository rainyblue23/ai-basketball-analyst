from types import SimpleNamespace

import cv2
import numpy as np

from aihoop.frame_reader import FrameReader
from aihoop.ball_recovery import measured_detections


def test_sampled_frames_match_seeks_including_backwards_and_long_gaps(tmp_path):
    path = str(tmp_path / 'numbered.avi')
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 30, (64, 48))
    for i in range(180):
        writer.write(np.full((48, 64, 3), i, np.uint8))
    writer.release()
    baseline = cv2.VideoCapture(path)
    actual = cv2.VideoCapture(path)
    reader = FrameReader(actual)
    try:
        for index in [0, 1, 15, 30, 30, 2, 160, 179]:
            baseline.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, expected = baseline.read()
            got, image = reader.read(index)
            assert got == ok
            np.testing.assert_array_equal(image, expected)
        assert reader.read(220)[0] is False
        baseline.set(cv2.CAP_PROP_POS_FRAMES, 0)
        _, expected = baseline.read()
        ok, recovered = reader.read(0)
        assert ok
        np.testing.assert_array_equal(recovered, expected)
    finally:
        baseline.release()
        actual.release()


def test_bulk_box_transfer_preserves_class_confidence_and_pixel_offsets():
    calls = []
    box = SimpleNamespace(cls=[0], conf=[.8125], xyxy=[[1., 2., 8., 9.]])
    class DeviceBoxes:
        def cpu(self):
            calls.append('transfer')
            return [box]
    result = SimpleNamespace(boxes=DeviceBoxes(), names={0:'basketball'})
    detections = measured_detections(result, offset=(10, 20))
    measured_detections(result)
    assert calls == ['transfer']
    assert detections[0].xyxy == (11., 22., 18., 29.)
    assert detections[0].conf == .8125
