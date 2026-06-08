"""Frame granular synthesis.

A *grain* is a short slice of a source clip — a patch of a frame, played from
some position at some rate for some duration, windowed by an envelope, scattered
in space and time. Many overlapping grains resynthesize a new "cloud" clip
(Forbes, Video Granular Synthesis, CAe 2015). The exact same grain schedule
drives the audio granulator, so picture and sound granulate in lockstep.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import cv2

from .params import ParamSpec


@dataclass
class Grain:
    onset: float       # output time (s) when the grain starts
    dur: float         # grain length (s)
    src_frac: float    # 0..1 read position into the source
    rate: float        # playback rate (negative = reverse)
    x: float           # canvas placement (fraction)
    y: float
    scale: float       # spatial zoom of the grain
    region: float      # patch size as fraction of the source frame (1 = whole)
    crop_x: float      # where the patch is cropped from (fraction)
    crop_y: float
    angle: float       # rotation (deg)
    gain: float


def _rotate(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderValue=(0, 0, 0))


class Granulator:
    PARAMS = {
        "density":   ParamSpec("Density g/s", 1, 120, 18, 1, "int"),
        "grain_ms":  ParamSpec("Grain ms", 20, 1500, 220, 5, "int"),
        "position":  ParamSpec("Position", 0, 1, 0.0, 0.01),
        "scan":      ParamSpec("Scan", -2, 2, 1.0, 0.05),
        "spray":     ParamSpec("Spray", 0, 1, 0.15, 0.01),
        "pitch":     ParamSpec("Rate", -2, 4, 1.0, 0.05),
        "pitch_jit": ParamSpec("Rate jitter", 0, 2, 0.0, 0.05),
        "reverse":   ParamSpec("Reverse prob", 0, 1, 0.0, 0.01),
        "region":    ParamSpec("Grain area", 0.1, 1.0, 1.0, 0.05),
        "scatter":   ParamSpec("Scatter", 0, 1, 0.0, 0.01),
        "size":      ParamSpec("Grain zoom", 0.2, 2.5, 1.0, 0.05),
        "size_jit":  ParamSpec("Zoom jitter", 0, 1.5, 0.0, 0.05),
        "angle_jit": ParamSpec("Angle jitter", 0, 180, 0, 5, "int"),
        "blend":     ParamSpec("Grain blend", 0, 2, 1, 1, "choice",
                               ("normal", "add", "screen")),
        "gain":      ParamSpec("Grain gain", 0.1, 2.0, 1.0, 0.05),
    }

    def __init__(self, seed: int = 4242):
        self.v = {k: float(s.default) for k, s in self.PARAMS.items()}
        self.seed = seed
        self.frames: list = []
        self.fps = 30.0
        self.grains: list[Grain] = []
        self.out_dur = 5.0

    def set_video(self, frames, fps):
        self.frames = frames or []
        self.fps = fps or 30.0

    # build the schedule (deterministic per seed); audio reuses self.grains
    def prepare(self, out_dur: float):
        self.out_dur = max(0.1, float(out_dur))
        rng = np.random.default_rng(self.seed)
        v = self.v
        n_src = max(1, len(self.frames))
        gsec = v["grain_ms"] / 1000.0
        density = max(0.1, v["density"])
        n = max(1, int(density * self.out_dur))
        grains = []
        for i in range(n):
            onset = (i + rng.random()) / density          # stratified async
            if onset > self.out_dur:
                continue
            fo = onset / self.out_dur
            src = v["position"] + v["scan"] * fo + v["spray"] * (rng.random() * 2 - 1)
            src = float(np.clip(src, 0.0, 1.0))
            rate = v["pitch"] + v["pitch_jit"] * (rng.random() * 2 - 1)
            if rng.random() < v["reverse"]:
                rate = -abs(rate)
            dur = gsec * (0.7 + 0.6 * rng.random())
            region = v["region"]
            cx = rng.random() * (1 - region)
            cy = rng.random() * (1 - region)
            if v["scatter"] <= 0:
                x, y = cx, cy
            else:
                x = float(np.clip(cx + v["scatter"] * (rng.random() * 2 - 1), 0, 1))
                y = float(np.clip(cy + v["scatter"] * (rng.random() * 2 - 1), 0, 1))
            size = max(0.05, v["size"] * (1 + v["size_jit"] * (rng.random() * 2 - 1)))
            angle = (rng.random() * 2 - 1) * v["angle_jit"]
            grains.append(Grain(onset, dur, src, rate, x, y, size, region,
                                cx, cy, angle, v["gain"]))
        self.grains = grains
        return grains

    def render(self, t: float, w: int, h: int):
        canvas = np.zeros((h, w, 3), np.float32)
        if not self.frames:
            return canvas.astype(np.uint8)
        n_src = len(self.frames)
        mode = int(self.v["blend"])
        for g in self.grains:
            if t < g.onset or t >= g.onset + g.dur:
                continue
            phase = (t - g.onset) / max(1e-6, g.dur)
            alpha = (0.5 - 0.5 * np.cos(2 * np.pi * phase)) * g.gain  # hann
            if alpha <= 0.01:
                continue
            idx = int(round(g.src_frac * (n_src - 1) +
                            g.rate * self.fps * (t - g.onset))) % n_src
            src = self.frames[idx]
            sh, sw = src.shape[:2]
            rw, rh = max(1, int(g.region * sw)), max(1, int(g.region * sh))
            cx, cy = min(int(g.crop_x * sw), sw - rw), min(int(g.crop_y * sh), sh - rh)
            patch = src[cy:cy + rh, cx:cx + rw]
            tw = max(1, int(g.region * w * g.scale))
            th = max(1, int(g.region * h * g.scale))
            patch = cv2.resize(patch, (tw, th))
            if abs(g.angle) > 0.5:
                patch = _rotate(patch, g.angle)
                th, tw = patch.shape[:2]
            px, py = int(g.x * w), int(g.y * h)
            x0, y0 = max(0, px), max(0, py)
            x1, y1 = min(w, px + tw), min(h, py + th)
            if x1 <= x0 or y1 <= y0:
                continue
            sub = patch[y0 - py:y1 - py, x0 - px:x1 - px].astype(np.float32)
            roi = canvas[y0:y1, x0:x1]
            if mode == 1:      # add
                roi += sub * alpha
            elif mode == 2:    # screen
                roi[:] = 255 - (255 - roi) * (255 - sub * alpha) / 255.0
            else:              # normal (weighted)
                roi[:] = roi * (1 - alpha) + sub * alpha
        return np.clip(canvas, 0, 255).astype(np.uint8)

    # serialization
    def to_dict(self):
        return {"seed": self.seed, "v": dict(self.v)}

    def load(self, d):
        self.seed = d.get("seed", self.seed)
        for k, val in d.get("v", {}).items():
            if k in self.v:
                self.v[k] = val
        return self
