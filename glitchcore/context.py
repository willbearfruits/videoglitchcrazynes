"""Per-frame context + a beat clock that effects read to sync to the music."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


class BeatClock:
    """Holds detected beat times (seconds) and answers musical-timing queries."""

    def __init__(self, beats, fps: float):
        b = np.asarray(sorted(beats), dtype=float) if beats is not None else np.array([], float)
        self.beats = b
        self.fps = float(fps)
        self.period = float(np.median(np.diff(b))) if b.size > 1 else 0.5

    def last_beat_index(self, t: float) -> int:
        """Index of the most recent beat at or before time t, or -1."""
        if self.beats.size == 0:
            return -1
        return int(np.searchsorted(self.beats, t, side="right") - 1)

    def is_beat_frame(self, t: float, dt: float) -> bool:
        """True if a beat falls inside [t, t+dt) — i.e. this frame lands on a beat."""
        if self.beats.size == 0:
            return False
        i = int(np.searchsorted(self.beats, t, side="left"))
        return i < self.beats.size and self.beats[i] < t + dt

    def qualifying_beat(self, t: float, div: int) -> tuple[int, float]:
        """Last beat whose index is a multiple of `div`. Returns (index, time)."""
        bidx = self.last_beat_index(t)
        if bidx < 0:
            return -1, -1.0
        div = max(1, int(div))
        qb = bidx - (bidx % div)
        return qb, float(self.beats[qb])


@dataclass
class FrameContext:
    """Everything an effect needs to know about the frame it's processing."""
    index: int
    time: float
    fps: float
    total: int
    width: int
    height: int
    rng: np.random.Generator
    is_beat: bool = False
    audio: object = None        # audio.AudioEnv | None (reactive modulation)
