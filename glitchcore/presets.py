"""Preset chains — instant chaos. Each is a list of (name, overrides) that
build into a Chain. Tweak freely after loading one."""
from __future__ import annotations
from .chain import Chain
from . import effects as fx

PRESETS: dict[str, list[tuple[str, dict]]] = {
    "brainfuck": [
        ("zoompunch", {"beat_mode": "pulse", "hold": 0.12, "v": {"zoom": 1.9}}),
        ("rgbshift", {"amount": 0.9, "v": {"x": 16, "animate": 1, "rate": 1.3}}),
        ("stutter", {"beat_div": 2, "v": {"frames": 4}}),
        ("shuffle", {"amount": 0.7, "beat_div": 4, "v": {"depth": 16}}),
        ("shake", {"beat_mode": "pulse", "hold": 0.1, "v": {"px": 30}}),
        ("strobe", {"amount": 0.6, "beat_mode": "pulse", "beat_div": 4, "hold": 0.06,
                    "v": {"mode": 0}}),
        ("lobotomy", {"amount": 0.5, "v": {"bits": 4, "swap": 1, "drop": 0}}),
    ],
    "seizure": [
        ("strobe", {"beat_mode": "pulse", "hold": 0.05, "v": {"mode": 0}}),
        ("zoompunch", {"beat_mode": "pulse", "hold": 0.1, "v": {"zoom": 2.4}}),
        ("shake", {"v": {"px": 45}}),
        ("rgbshift", {"v": {"x": 28, "y": 10, "animate": 1, "rate": 3.0}}),
        ("slice", {"amount": 0.8, "beat_mode": "gate", "hold": 0.08,
                   "v": {"bands": 22, "max": 140}}),
    ],
    "datamoshhell": [
        ("echo", {"v": {"decay": 0.8}}),
        ("shuffle", {"amount": 0.8, "beat_div": 1, "v": {"depth": 24}}),
        ("stutter", {"beat_div": 2, "v": {"frames": 6}}),
        ("slice", {"amount": 0.6, "v": {"bands": 10, "max": 70}}),
        # the real codec datamosh is enabled via the render option, not here
    ],
    "vapordecay": [
        ("vhs", {"v": {"intensity": 0.7}}),
        ("rgbshift", {"amount": 0.5, "v": {"x": 8, "animate": 1, "rate": 0.4}}),
        ("echo", {"v": {"decay": 0.55}}),
        ("warp", {"amount": 0.5, "v": {"amp": 10, "freq": 4, "speed": 1.5}}),
        ("lobotomy", {"amount": 0.4, "v": {"bits": 5, "swap": 0, "drop": 0}}),
    ],
    "pixelmelt": [
        ("pixelsort", {"amount": 0.9, "v": {"thresh": 90, "vertical": 0}}),
        ("rgbshift", {"amount": 0.6, "v": {"x": 12, "animate": 1}}),
        ("slice", {"amount": 0.5, "beat_mode": "pulse", "hold": 0.2,
                   "v": {"bands": 8, "max": 60}}),
    ],
    "motionmelt": [   # v2 motion engine showcase
        ("optimosh", {"beat_mode": "pulse", "beat_div": 2, "hold": 0.4,
                      "v": {"strength": 1.8}}),
        ("flowsmear", {"amount": 0.6, "mod_source": "rms", "mod_depth": 0.7,
                       "v": {"reach": 3.0, "rate": 0}}),
        ("depthpush", {"amount": 0.5, "v": {"amount": 60, "invert": 0}}),
        ("rgbshift", {"amount": 0.5, "v": {"x": 10, "animate": 1}}),
    ],
}

# presets that strongly benefit from the real codec datamosh pass
WANTS_DATAMOSH = {"datamoshhell"}


def build(name: str, seed: int = 1337) -> Chain:
    chain = Chain(seed=seed)
    for ename, over in PRESETS.get(name, []):
        chain.add(fx.make(ename, **over))
    return chain


# ---- user preset library (saved effect chains) ----------------------------
import os as _os
import json as _json
import glob as _glob

USER_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "fx_presets")


def list_user() -> list:
    if not _os.path.isdir(USER_DIR):
        return []
    return sorted(_os.path.splitext(_os.path.basename(p))[0]
                  for p in _glob.glob(_os.path.join(USER_DIR, "*.json")))


def save_user(name: str, chain: Chain):
    _os.makedirs(USER_DIR, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "preset"
    with open(_os.path.join(USER_DIR, safe + ".json"), "w") as f:
        _json.dump(chain.to_dict(), f, indent=2)
    return safe


def load_user(name: str) -> Chain:
    with open(_os.path.join(USER_DIR, name + ".json")) as f:
        return Chain().load(_json.load(f))
