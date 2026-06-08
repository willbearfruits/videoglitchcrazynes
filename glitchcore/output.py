"""Virtual camera output — pipe composited frames to a v4l2 loopback device so
OBS / Zoom / browsers see the glitch output as a webcam."""
from __future__ import annotations
import numpy as np
import cv2


class VirtualCam:
    def __init__(self, w: int, h: int, fps: float = 30.0):
        import pyvirtualcam
        self.cam = pyvirtualcam.Camera(width=w, height=h, fps=int(fps),
                                       fmt=pyvirtualcam.PixelFormat.BGR)
        self.w, self.h = w, h
        self.device = self.cam.device

    def send(self, frame_bgr):
        if frame_bgr.shape[1] != self.w or frame_bgr.shape[0] != self.h:
            frame_bgr = cv2.resize(frame_bgr, (self.w, self.h))
        self.cam.send(np.ascontiguousarray(frame_bgr))

    def close(self):
        try:
            self.cam.close()
        except Exception:
            pass
