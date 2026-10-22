"""Read exact sampled frames without repeatedly decoding the same video GOP."""
import cv2


class FrameReader:
    def __init__(self, capture):
        self.capture = capture
        self.last_index = -1

    def read(self, index):
        index = max(0, int(index))
        gap = index - self.last_index if self.last_index is not None else 121
        if gap <= 0 or gap > 120:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        else:
            for _ in range(gap - 1):
                if not self.capture.grab():
                    self.last_index = None
                    return False, None
        ok, image = self.capture.read()
        self.last_index = index if ok else None
        return ok, image
