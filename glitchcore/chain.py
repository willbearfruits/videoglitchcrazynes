"""An ordered stack of effects applied to each frame."""
from __future__ import annotations
import numpy as np

from .context import FrameContext, BeatClock
from . import effects as fx


class Chain:
    def __init__(self, seed: int = 1337):
        self.effects: list[fx.Effect] = []
        self.seed = seed

    def add(self, eff: fx.Effect):
        self.effects.append(eff)
        return eff

    def remove(self, eff):
        if eff in self.effects:
            self.effects.remove(eff)

    def move(self, eff, delta: int):
        i = self.effects.index(eff)
        j = max(0, min(len(self.effects) - 1, i + delta))
        self.effects.insert(j, self.effects.pop(i))

    def reset(self):
        for e in self.effects:
            e.reset()

    def process_frame(self, frame, index, time, fps, total, clock: BeatClock, audio=None):
        ctx = FrameContext(
            index=index, time=time, fps=fps, total=total,
            width=frame.shape[1], height=frame.shape[0],
            rng=np.random.default_rng(self.seed + index),
            is_beat=clock.is_beat_frame(time, 1.0 / max(1e-6, fps)),
            audio=audio,
        )
        out = frame
        for e in self.effects:
            out = e.apply(out, ctx, clock)
        return out

    # -- serialization -----------------------------------------------------
    def to_dict(self):
        return {"seed": self.seed, "effects": [e.to_dict() for e in self.effects]}

    def load(self, d: dict):
        self.seed = d.get("seed", 1337)
        self.effects = []
        for ed in d.get("effects", []):
            if ed["name"] in fx.REGISTRY:
                self.add(fx.REGISTRY[ed["name"]]().load(ed))
        return self
