"""Random-access video source with an LRU frame cache + a sequential preloader
(used to feed the granulator a pool of frames)."""
from __future__ import annotations
from collections import OrderedDict
import cv2


class VideoSource:
    def __init__(self, path: str, cache: int = 300):
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise ValueError(f"Could not open video: {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = (self.n / self.fps) if self.fps else 0.0
        self._cache: "OrderedDict[int, object]" = OrderedDict()
        self._cap_max = cache
        self._pos = -1

    def _read_index(self, i: int):
        i = max(0, min(self.n - 1, i)) if self.n else max(0, i)
        if i in self._cache:
            self._cache.move_to_end(i)
            return self._cache[i]
        if i != self._pos + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = self.cap.read()
        self._pos = i
        if not ok:
            return None
        self._cache[i] = frame
        if len(self._cache) > self._cap_max:
            self._cache.popitem(last=False)
        return frame

    def frame_at_time(self, t: float):
        return self._read_index(int(round(t * self.fps)))

    def preload(self, work_w: int = 720, max_frames: int = 600):
        """Decode sequentially into a list (downscaled) for the granulator."""
        frames = []
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        while len(frames) < max_frames:
            ok, fr = self.cap.read()
            if not ok:
                break
            if work_w and fr.shape[1] > work_w:
                s = work_w / fr.shape[1]
                fr = cv2.resize(fr, (work_w, max(1, int(fr.shape[0] * s))))
            frames.append(fr)
        self._pos = -1
        return frames

    def release(self):
        try:
            self.cap.release()
        except Exception:
            pass
