"""Live frame sources — webcam and screen capture — usable as timeline layers.

They mimic the VideoSource interface (frame_at_time / preload / w,h,fps,duration)
so the compositor treats them like any clip. `frame_at_time` ignores t and grabs
"now", so during render they record whatever is happening live.
"""
from __future__ import annotations
import threading
import numpy as np
import cv2


class WebcamSource:
    def __init__(self, index: int = 0, duration: float = 15.0):
        self.cap = cv2.VideoCapture(index)
        self.w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.duration = duration
        self.n = int(duration * self.fps)
        self.path = f"webcam:{index}"
        self._last = None

    def ok(self):
        return self.cap.isOpened()

    def frame_at_time(self, t):
        got, fr = self.cap.read()
        if got:
            self._last = fr
        return self._last

    def preload(self, work_w: int = 480, max_frames: int = 150):
        out = []
        for _ in range(max_frames):
            got, fr = self.cap.read()
            if not got:
                break
            if work_w and fr.shape[1] > work_w:
                s = work_w / fr.shape[1]
                fr = cv2.resize(fr, (work_w, max(1, int(fr.shape[0] * s))))
            out.append(fr)
        return out

    def release(self):
        try:
            self.cap.release()
        except Exception:
            pass


class ScreenSource:
    def __init__(self, monitor: int = 1, duration: float = 15.0):
        import mss
        probe = mss.mss()
        mons = probe.monitors
        self.mon = mons[monitor] if monitor < len(mons) else mons[0]
        self.w = self.mon["width"]
        self.h = self.mon["height"]
        self.fps = 30.0
        self.duration = duration
        self.n = int(duration * self.fps)
        self.path = "screen"
        self._local = threading.local()   # mss is per-thread
        self._instances = []              # every per-thread mss, for cleanup
        self._lock = threading.Lock()
        probe.close()

    def _sct(self):
        import mss
        if getattr(self._local, "inst", None) is None:
            inst = mss.mss()
            self._local.inst = inst
            with self._lock:
                self._instances.append(inst)
        return self._local.inst

    def frame_at_time(self, t):
        img = np.array(self._sct().grab(self.mon))   # BGRA
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def preload(self, work_w: int = 480, max_frames: int = 60):
        out = []
        for _ in range(max_frames):
            fr = self.frame_at_time(0)
            if work_w and fr.shape[1] > work_w:
                s = work_w / fr.shape[1]
                fr = cv2.resize(fr, (work_w, max(1, int(fr.shape[0] * s))))
            out.append(fr)
        return out

    def release(self):
        with self._lock:
            insts, self._instances = self._instances, []
        for inst in insts:                # close mss contexts from every thread
            try:
                inst.close()
            except Exception:
                pass


def find_webcam_index():
    """Scan /dev/video* and return the first index that yields a frame, or None."""
    import glob
    idxs = sorted(int(p.rsplit("video", 1)[1]) for p in glob.glob("/dev/video*")
                  if p.rsplit("video", 1)[1].isdigit())
    for i in idxs or range(0, 10):
        cap = cv2.VideoCapture(i)
        ok = cap.isOpened() and cap.read()[0]
        cap.release()
        if ok:
            return i
    return None
