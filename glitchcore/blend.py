"""Layer blend modes — normal plus the weird/glitchy ones for mixing clips."""
from __future__ import annotations
import numpy as np
import cv2

MODES = [
    "normal", "add", "screen", "multiply", "difference", "exclusion",
    "lighten", "darken", "overlay", "hardlight", "subtract", "divide",
    "xor", "and", "or", "average",
]


def blend(mode: str, base, top, opacity: float = 1.0):
    """Composite `top` over `base` (both BGR uint8, same shape). Returns uint8."""
    opacity = float(max(0.0, min(1.0, opacity)))
    if opacity <= 0.0:
        return base

    if mode in ("xor", "and", "or"):
        if mode == "xor":
            res = cv2.bitwise_xor(base, top)
        elif mode == "and":
            res = cv2.bitwise_and(base, top)
        else:
            res = cv2.bitwise_or(base, top)
        return cv2.addWeighted(res, opacity, base, 1 - opacity, 0)

    b = base.astype(np.float32) / 255.0
    t = top.astype(np.float32) / 255.0
    if mode == "normal":
        out = t
    elif mode == "add":
        out = b + t
    elif mode == "screen":
        out = 1 - (1 - b) * (1 - t)
    elif mode == "multiply":
        out = b * t
    elif mode == "difference":
        out = np.abs(b - t)
    elif mode == "exclusion":
        out = b + t - 2 * b * t
    elif mode == "lighten":
        out = np.maximum(b, t)
    elif mode == "darken":
        out = np.minimum(b, t)
    elif mode == "subtract":
        out = b - t
    elif mode == "divide":
        out = b / (t + 1e-3)
    elif mode == "average":
        out = (b + t) * 0.5
    elif mode == "overlay":
        out = np.where(b < 0.5, 2 * b * t, 1 - 2 * (1 - b) * (1 - t))
    elif mode == "hardlight":
        out = np.where(t < 0.5, 2 * b * t, 1 - 2 * (1 - b) * (1 - t))
    else:
        out = t
    out = np.clip(out, 0.0, 1.0)
    res = b * (1 - opacity) + out * opacity
    return (np.clip(res, 0.0, 1.0) * 255).astype(np.uint8)
