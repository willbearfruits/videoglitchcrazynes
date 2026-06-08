"""glitchcore — headless video-glitch engine (no Qt).

Public surface:
    effects.REGISTRY / make()       build effects
    Chain                           ordered effect stack applied per frame
    presets.build(name)             instant-chaos preset chains
    beat.detect_beats(path)         librosa beat/onset detection
    render(...)                     single-input file render
    Timeline / Layer / render_timeline   multi-layer compositor
    Granulator                      frame granular synthesis
    audio.granulate_audio(...)      matching audio grains
    blend.blend(mode, ...)          layer blend modes
"""
from .chain import Chain
from .context import BeatClock, FrameContext
from .renderer import render, render_timeline, RenderOptions
from .comp import Timeline, Layer
from .granular import Granulator, Grain
from .sources import VideoSource
from .warp import TimeWarp
from .auto import lobotomize
from . import effects, presets, beat, media, datamosh, blend, audio

__all__ = [
    "Chain", "BeatClock", "FrameContext",
    "render", "render_timeline", "RenderOptions",
    "Timeline", "Layer", "Granulator", "Grain", "VideoSource",
    "TimeWarp", "lobotomize",
    "effects", "presets", "beat", "media", "datamosh", "blend", "audio",
]
