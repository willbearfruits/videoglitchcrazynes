"""The Auto-Lobotomizer — one call turns a layer into a full lobotomy edit:
a beat-driven time-warp + a beat-synced, audio-reactive effect chain."""
from __future__ import annotations
from .warp import TimeWarp
from .chain import Chain
from . import effects as fx


def lobotomize(layer, beats, content_dur: float, duration: float, seed: int = 99):
    """Configure `layer` in place. Returns it. Caller usually also turns on
    the Datamosh render option."""
    layer.warp = TimeWarp(seed=seed).build(beats, duration, content_dur)
    ch = Chain(seed=seed)
    ch.add(fx.make("stutter", beat_mode="gate", beat_div=2, v={"frames": 3}))
    ch.add(fx.make("zoompunch", beat_mode="pulse", hold=0.12, v={"zoom": 2.0},
                   mod_source="bass", mod_depth=0.6))
    ch.add(fx.make("rgbshift", amount=0.9, v={"x": 16, "animate": 1, "rate": 1.5},
                   mod_source="high", mod_depth=0.7))
    ch.add(fx.make("shake", beat_mode="pulse", hold=0.10, v={"px": 26},
                   mod_source="rms", mod_depth=0.6))
    ch.add(fx.make("strobe", amount=0.6, beat_mode="pulse", beat_div=4, hold=0.05,
                   v={"mode": 0}))
    ch.add(fx.make("slice", amount=0.6, beat_mode="gate", beat_div=2, hold=0.08,
                   v={"bands": 14, "max": 90}))
    layer.chain = ch
    return layer
