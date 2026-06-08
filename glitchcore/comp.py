"""Compositor: a timeline of layers, each a video or a granulator, mixed with
blend modes and run through its own effect chain."""
from __future__ import annotations
import cv2
import numpy as np

from .blend import blend
from .chain import Chain
from .granular import Granulator


class Layer:
    def __init__(self, name: str, source=None, granulator: Granulator | None = None):
        self.name = name
        self.source = source              # VideoSource | None
        self.granulator = granulator      # Granulator | None
        self.is_granular = granulator is not None
        self.enabled = True
        self.opacity = 1.0
        self.blend = "normal"
        self.start = 0.0                  # placement on the timeline (s)
        self.trim_in = 0.0                # in-point into the source (s)
        self.duration = None             # length on the timeline (s); None = full
        self.warp = None                 # TimeWarp | None (variable time-remap)
        self.chain = Chain()

    def length(self) -> float:
        if self.duration:
            return self.duration
        if self.is_granular:
            return self.granulator.out_dur
        return self.source.duration if self.source else 0.0

    def end(self) -> float:
        return self.start + self.length()

    def active(self, t: float) -> bool:
        return self.enabled and self.start <= t < self.end()

    def frame_at(self, t, w, h, fps, clock, total, t_out=None, audio=None):
        if not self.active(t):
            return None
        if t_out is None:
            t_out = t
        base = t - self.start
        if self.warp is not None:
            base = self.warp.map(base)        # variable beat-driven time-remap
        local = base + self.trim_in
        if self.is_granular:
            img = self.granulator.render(local, w, h)
        else:
            f = self.source.frame_at_time(local)
            if f is None:
                return None
            img = f if (f.shape[1] == w and f.shape[0] == h) else cv2.resize(f, (w, h))
        if self.chain.effects:
            img = self.chain.process_frame(img, int(t_out * fps), t_out, fps,
                                           total, clock, audio=audio)
        return img

    def to_dict(self):
        d = {
            "name": self.name, "enabled": self.enabled, "opacity": self.opacity,
            "blend": self.blend, "start": self.start, "trim_in": self.trim_in,
            "duration": self.duration, "is_granular": self.is_granular,
            "chain": self.chain.to_dict(),
            "warp": self.warp.to_dict() if self.warp else None,
        }
        if self.is_granular:
            d["granulator"] = self.granulator.to_dict()
        elif self.source:
            d["path"] = self.source.path
        return d


class Timeline:
    def __init__(self, fps: float = 30.0):
        self.layers: list[Layer] = []
        self.fps = fps
        self.width = 0
        self.height = 0

    def add(self, layer: Layer):
        self.layers.append(layer)
        if self.width == 0 and not layer.is_granular and layer.source:
            self.width, self.height = layer.source.w, layer.source.h
        return layer

    def duration(self) -> float:
        return max((l.end() for l in self.layers), default=0.0)

    def render_frame(self, t, w, h, clock, t_out=None, audio=None):
        total = int(self.duration() * self.fps)
        canvas = np.zeros((h, w, 3), np.uint8)
        for layer in self.layers:
            f = layer.frame_at(t, w, h, self.fps, clock, total, t_out, audio=audio)
            if f is None:
                continue
            canvas = blend(layer.blend, canvas, f, layer.opacity)
        return canvas
