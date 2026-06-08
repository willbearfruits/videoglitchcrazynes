"""The glitch effects library.

Every effect is a small class. The base class handles beat-syncing (always /
pulse / gate) and wet amount; subclasses just implement `process()` on a BGR
uint8 frame. New effects auto-register and the GUI builds controls from PARAMS.
"""
from __future__ import annotations
import numpy as np
import cv2

from .params import ParamSpec
from .context import FrameContext, BeatClock
from . import motion as mo

REGISTRY: dict[str, type] = {}
EFFECT_ORDER: list[str] = []


def register(cls):
    REGISTRY[cls.name] = cls
    EFFECT_ORDER.append(cls.name)
    return cls


class Effect:
    name = "effect"
    label = "Effect"
    category = "glitch"
    PARAMS: dict[str, ParamSpec] = {}

    # Effects that are edge-triggered on beats (stutter/shuffle) bypass the
    # decay gate and run every frame, doing their own beat-edge detection.
    self_gated = False

    def __init__(self):
        self.enabled = True
        self.amount = 1.0          # master wet 0..1
        self.beat_mode = "always"  # always | pulse | gate
        self.beat_div = 1          # trigger every Nth beat
        self.hold = 0.14           # seconds: pulse decay / gate window
        self.mod_source = "none"   # none | rms | bass | mid | high (audio-reactive)
        self.mod_depth = 0.8       # how much the audio band drives strength
        self.v = {k: float(s.default) for k, s in self.PARAMS.items()}
        self.reset()

    # -- state lifecycle ---------------------------------------------------
    def reset(self):
        """Clear any per-clip buffers. Called before each render/playback."""

    # -- beat gating -------------------------------------------------------
    def gate(self, ctx: FrameContext, clock: BeatClock) -> float:
        if self.self_gated or self.beat_mode == "always":
            return 1.0
        qb, qt = clock.qualifying_beat(ctx.time, self.beat_div)
        if qb < 0:
            return 0.0
        tsb = ctx.time - qt
        if self.beat_mode == "gate":
            return 1.0 if 0.0 <= tsb <= self.hold else 0.0
        return float(np.exp(-tsb / max(1e-3, self.hold)))  # pulse

    def audio_mul(self, ctx: FrameContext) -> float:
        """Audio-reactive scaling: depth 0 = ignore audio, 1 = fully driven."""
        if self.mod_source == "none" or ctx.audio is None:
            return 1.0
        env = ctx.audio.value(self.mod_source, ctx.time)
        return (1.0 - self.mod_depth) + self.mod_depth * env

    def apply(self, frame, ctx: FrameContext, clock: BeatClock):
        if not self.enabled:
            return frame
        s = self.gate(ctx, clock) * self.amount * self.audio_mul(ctx)
        if s <= 0.001:
            return frame
        return self.process(frame, ctx, clock, min(1.0, s))

    def process(self, frame, ctx, clock, s):  # pragma: no cover - overridden
        return frame

    # -- (de)serialization for presets / project files --------------------
    def to_dict(self):
        return {
            "name": self.name, "enabled": self.enabled, "amount": self.amount,
            "beat_mode": self.beat_mode, "beat_div": self.beat_div,
            "hold": self.hold, "mod_source": self.mod_source,
            "mod_depth": self.mod_depth, "v": dict(self.v),
        }

    def load(self, d: dict):
        self.enabled = d.get("enabled", True)
        self.amount = d.get("amount", 1.0)
        self.beat_mode = d.get("beat_mode", "always")
        self.beat_div = int(d.get("beat_div", 1))
        self.hold = d.get("hold", 0.14)
        self.mod_source = d.get("mod_source", "none")
        self.mod_depth = d.get("mod_depth", 0.8)
        for k, val in d.get("v", {}).items():
            if k in self.v:
                self.v[k] = val
        return self


def make(name: str, **over) -> Effect:
    """Instantiate an effect by name with field/param overrides."""
    eff = REGISTRY[name]()
    for k in ("enabled", "amount", "beat_mode", "beat_div", "hold",
              "mod_source", "mod_depth"):
        if k in over:
            setattr(eff, k, over.pop(k))
    v = over.pop("v", {})
    for k, val in v.items():
        if k in eff.v:
            eff.v[k] = val
    return eff


# ======================================================================
#  EFFECTS
# ======================================================================

@register
class RGBShift(Effect):
    name, label, category = "rgbshift", "RGB Shift", "color"
    PARAMS = {
        "x": ParamSpec("X tear", -80, 80, 10, 1, "int"),
        "y": ParamSpec("Y tear", -80, 80, 0, 1, "int"),
        "animate": ParamSpec("Wobble", 0, 1, 1, 1, "bool"),
        "rate": ParamSpec("Wobble rate", 0.1, 6, 0.7, 0.1),
    }

    def process(self, frame, ctx, clock, s):
        dx, dy = self.v["x"], self.v["y"]
        if self.v["animate"] > 0.5:
            m = np.sin(ctx.time * 2 * np.pi * self.v["rate"])
            dx *= m; dy *= m
        dx = int(round(dx * s)); dy = int(round(dy * s))
        out = frame.copy()
        out[:, :, 2] = np.roll(np.roll(frame[:, :, 2], dx, 1), dy, 0)   # R
        out[:, :, 0] = np.roll(np.roll(frame[:, :, 0], -dx, 1), -dy, 0)  # B
        return out


@register
class ChannelLobotomy(Effect):
    name, label, category = "lobotomy", "Channel Lobotomy", "color"
    PARAMS = {
        "bits": ParamSpec("Bit crush", 1, 8, 3, 1, "int"),
        "swap": ParamSpec("Swap channels", 0, 1, 1, 1, "bool"),
        "drop": ParamSpec("Kill channel", 0, 3, 0, 1, "choice",
                          ("none", "blue", "green", "red")),
    }

    def process(self, frame, ctx, clock, s):
        bits = int(self.v["bits"])
        q = max(1, 256 >> bits)
        out = (frame // q) * q
        if self.v["swap"] > 0.5:
            out = out[:, :, [1, 2, 0]]
        d = int(self.v["drop"])
        if d in (1, 2, 3):
            out = out.copy()
            out[:, :, d - 1] = 0
        if s < 0.999:
            out = cv2.addWeighted(out, s, frame, 1 - s, 0)
        return out


@register
class Shake(Effect):
    name, label, category = "shake", "Camera Shake", "motion"
    PARAMS = {"px": ParamSpec("Max px", 0, 120, 28, 1, "int")}

    def process(self, frame, ctx, clock, s):
        amp = int(self.v["px"] * s)
        if amp <= 0:
            return frame
        dx = int(ctx.rng.integers(-amp, amp + 1))
        dy = int(ctx.rng.integers(-amp, amp + 1))
        return np.roll(np.roll(frame, dx, 1), dy, 0)


@register
class ZoomPunch(Effect):
    name, label, category = "zoompunch", "Zoom Punch", "motion"
    PARAMS = {"zoom": ParamSpec("Max zoom", 1.0, 4.0, 1.7, 0.05)}

    def __init__(self):
        super().__init__()
        self.beat_mode = "pulse"  # punches on the beat by default

    def process(self, frame, ctx, clock, s):
        z = 1.0 + (self.v["zoom"] - 1.0) * s
        if z <= 1.001:
            return frame
        h, w = frame.shape[:2]
        big = cv2.resize(frame, (int(w * z), int(h * z)), interpolation=cv2.INTER_LINEAR)
        x = (big.shape[1] - w) // 2
        y = (big.shape[0] - h) // 2
        return big[y:y + h, x:x + w]


@register
class Stutter(Effect):
    """Latch a frame on the beat and repeat it — the classic retrigger/freeze."""
    name, label, category = "stutter", "Stutter / Freeze", "time"
    self_gated = True
    PARAMS = {"frames": ParamSpec("Hold frames", 1, 30, 4, 1, "int")}

    def reset(self):
        self._left = 0
        self._buf = None
        self._lastqb = -999

    def process(self, frame, ctx, clock, s):
        qb, _ = clock.qualifying_beat(ctx.time, self.beat_div)
        if qb >= 0 and qb != self._lastqb:
            self._lastqb = qb
            self._left = max(1, int(round(self.v["frames"] * s)))
            self._buf = frame.copy()
        if self._left > 0 and self._buf is not None:
            self._left -= 1
            return self._buf
        return frame


@register
class FrameShuffle(Effect):
    """Jump to a random recent frame on the beat — 'weird movement between frames'."""
    name, label, category = "shuffle", "Frame Shuffle", "time"
    self_gated = True
    PARAMS = {"depth": ParamSpec("Buffer depth", 2, 40, 14, 1, "int")}

    def reset(self):
        self._buf = []
        self._lastqb = -999

    def process(self, frame, ctx, clock, s):
        self._buf.append(frame)
        depth = int(self.v["depth"])
        if len(self._buf) > depth:
            self._buf.pop(0)
        qb, _ = clock.qualifying_beat(ctx.time, self.beat_div)
        if qb >= 0 and qb != self._lastqb and len(self._buf) > 1 and ctx.rng.random() < s:
            self._lastqb = qb
            j = int(ctx.rng.integers(0, len(self._buf)))
            return self._buf[j]
        return frame


@register
class FrameEcho(Effect):
    """Feedback trails — blends the previous output back in. Datamosh-ish smear."""
    name, label, category = "echo", "Echo / Trails", "time"
    PARAMS = {"decay": ParamSpec("Trail", 0.0, 0.97, 0.6, 0.01)}

    def reset(self):
        self._prev = None

    def process(self, frame, ctx, clock, s):
        if self._prev is None or self._prev.shape != frame.shape:
            self._prev = frame.copy()
            return frame
        d = float(self.v["decay"] * s)
        out = cv2.addWeighted(frame, 1.0, self._prev, d, 0.0)
        self._prev = out.copy()
        return out


@register
class PixelSort(Effect):
    name, label, category = "pixelsort", "Pixel Sort", "glitch"
    PARAMS = {
        "thresh": ParamSpec("Threshold", 0, 255, 110, 1, "int"),
        "vertical": ParamSpec("Vertical", 0, 1, 0, 1, "bool"),
    }

    def process(self, frame, ctx, clock, s):
        vert = self.v["vertical"] > 0.5
        img = np.transpose(frame, (1, 0, 2)) if vert else frame
        lum = img.mean(axis=2)
        out = img.copy()
        thr = int(self.v["thresh"])
        h = img.shape[0]
        step = max(1, int(round(1.0 / max(0.05, s))))
        for y in range(0, h, step):
            l = lum[y]
            idx = np.where(l > thr)[0]
            if idx.size < 2:
                continue
            order = idx[np.argsort(l[idx])]
            out[y, idx] = img[y, order]
        return np.transpose(out, (1, 0, 2)) if vert else out


@register
class SliceGlitch(Effect):
    name, label, category = "slice", "Slice Displace", "glitch"
    PARAMS = {
        "bands": ParamSpec("Bands", 1, 50, 14, 1, "int"),
        "max": ParamSpec("Max shift", 0, 300, 90, 1, "int"),
    }

    def process(self, frame, ctx, clock, s):
        h, w = frame.shape[:2]
        out = frame.copy()
        n = int(self.v["bands"])
        mx = max(1, int(self.v["max"] * s))
        bhmax = max(3, h // 12)
        for _ in range(n):
            y0 = int(ctx.rng.integers(0, h))
            y1 = min(h, y0 + int(ctx.rng.integers(2, bhmax)))
            sh = int(ctx.rng.integers(-mx, mx + 1))
            out[y0:y1] = np.roll(frame[y0:y1], sh, axis=1)
        return out


@register
class Warp(Effect):
    name, label, category = "warp", "Wave Warp", "motion"
    PARAMS = {
        "amp": ParamSpec("Amp", 0, 80, 18, 1, "int"),
        "freq": ParamSpec("Freq", 1, 24, 6, 0.5),
        "speed": ParamSpec("Speed", 0, 12, 3, 0.5),
    }

    def process(self, frame, ctx, clock, s):
        h, w = frame.shape[:2]
        amp = self.v["amp"] * s
        ys = np.arange(h, dtype=np.float32)
        off = amp * np.sin(2 * np.pi * self.v["freq"] * ys / h + ctx.time * self.v["speed"])
        map_x = np.tile(np.arange(w, dtype=np.float32), (h, 1)) + off[:, None]
        map_y = np.tile(ys.reshape(-1, 1), (1, w))
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


@register
class Strobe(Effect):
    name, label, category = "strobe", "Strobe / Invert", "color"
    PARAMS = {"mode": ParamSpec("Mode", 0, 2, 0, 1, "choice", ("invert", "white", "black"))}

    def __init__(self):
        super().__init__()
        self.beat_mode = "pulse"

    def process(self, frame, ctx, clock, s):
        m = int(self.v["mode"])
        if m == 0:
            tgt = 255 - frame
        elif m == 1:
            tgt = np.full_like(frame, 255)
        else:
            tgt = np.zeros_like(frame)
        return cv2.addWeighted(tgt, s, frame, 1 - s, 0)


@register
class Databend(Effect):
    """Anti-art databending: JPEG-encode the frame, corrupt bytes after the
    header, decode the wreckage. Real compression-artifact glitch, not a fake."""
    name, label, category = "databend", "Databend (JPEG)", "glitch"
    PARAMS = {
        "quality": ParamSpec("JPEG quality", 2, 60, 18, 1, "int"),
        "corrupt": ParamSpec("Corruption", 0.0, 0.02, 0.003, 0.0005),
    }

    def reset(self):
        self._last = None

    def process(self, frame, ctx, clock, s):
        q = int(self.v["quality"])
        ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, q])
        if not ok:
            return frame
        buf = bytearray(enc.tobytes())
        header = min(len(buf) - 1, 640)            # keep SOI/markers intact
        n = int((len(buf) - header) * self.v["corrupt"] * s)
        for _ in range(n):
            i = int(ctx.rng.integers(header, len(buf)))
            buf[i] = int(ctx.rng.integers(0, 256))
        dec = cv2.imdecode(np.frombuffer(bytes(buf), np.uint8), cv2.IMREAD_COLOR)
        if dec is None:
            return self._last if self._last is not None else frame  # decode died
        if dec.shape != frame.shape:
            dec = cv2.resize(dec, (frame.shape[1], frame.shape[0]))
        self._last = dec
        return dec


@register
class VHS(Effect):
    name, label, category = "vhs", "VHS / Decay", "color"
    PARAMS = {"intensity": ParamSpec("Intensity", 0, 1, 0.6, 0.01)}

    def process(self, frame, ctx, clock, s):
        amt = self.v["intensity"] * s
        out = frame.astype(np.int16)
        out[::2] = (out[::2] * (1 - 0.55 * amt)).astype(np.int16)  # scanlines
        out = np.clip(out, 0, 255).astype(np.uint8)
        sh = int(5 * amt)
        if sh:
            out[:, :, 2] = np.roll(out[:, :, 2], sh, 1)
            out[:, :, 0] = np.roll(out[:, :, 0], -sh, 1)
        if amt > 0:
            n = int(28 * amt)
            noise = ctx.rng.integers(-n, n + 1, size=out.shape[:2], dtype=np.int16)
            out = np.clip(out.astype(np.int16) + noise[:, :, None], 0, 255).astype(np.uint8)
        return out


# ======================================================================
#  v2 — AI MOTION ENGINE (optical flow + depth)
# ======================================================================

@register
class OpticalDatamosh(Effect):
    """Real motion-vector datamosh: keep the old frame's pixels and push them
    along the live optical flow — controllable melt/bloom, no codec luck."""
    name, label, category = "optimosh", "Optical Datamosh", "motion"
    PARAMS = {"strength": ParamSpec("Motion push", 0.2, 4.0, 1.4, 0.1)}

    def __init__(self):
        super().__init__()
        self.beat_mode = "pulse"      # bloom on beats, refresh between

    def reset(self):
        self._pg = None
        self._canvas = None

    def process(self, frame, ctx, clock, s):
        g = mo.gray(frame)
        if self._canvas is None or self._canvas.shape != frame.shape:
            self._pg = g
            self._canvas = frame.copy()
            return frame
        fl = mo.flow(self._pg, g)
        self._pg = g
        self._canvas = mo.warp_by_flow(self._canvas, fl, self.v["strength"])
        keep = float(s)               # 1 = pure bloom, 0 = refresh to live
        self._canvas = cv2.addWeighted(self._canvas, keep, frame, 1.0 - keep, 0.0)
        return self._canvas


@register
class FlowSmear(Effect):
    """Push the current frame along its own motion — weird inbetween movement."""
    name, label, category = "flowsmear", "Flow Smear", "motion"
    PARAMS = {
        "reach": ParamSpec("Reach", 0.5, 6.0, 2.5, 0.1),
        "rate": ParamSpec("Wobble", 0, 8, 0, 0.5),
    }

    def reset(self):
        self._pg = None

    def process(self, frame, ctx, clock, s):
        g = mo.gray(frame)
        if self._pg is None or self._pg.shape != g.shape:
            self._pg = g
            return frame
        fl = mo.flow(self._pg, g)
        self._pg = g
        t = self.v["reach"] * s
        if self.v["rate"] > 0:
            t *= np.sin(ctx.time * 2 * np.pi * self.v["rate"] * 0.2)
        return mo.warp_by_flow(frame, fl, t)


@register
class DepthDisplace(Effect):
    """Parallax displacement keyed by estimated depth (MiDaS if enabled, else
    luminance pseudo-depth)."""
    name, label, category = "depthpush", "Depth Displace", "motion"
    PARAMS = {
        "amount": ParamSpec("Push px", 0, 140, 50, 1, "int"),
        "invert": ParamSpec("Invert", 0, 1, 0, 1, "bool"),
    }

    def process(self, frame, ctx, clock, s):
        d = mo.depth(frame)
        if self.v["invert"] > 0.5:
            d = 1.0 - d
        amt = self.v["amount"] * s
        h, w = frame.shape[:2]
        gx = np.arange(w, dtype=np.float32)[None, :]
        gy = np.arange(h, dtype=np.float32)[:, None]
        map_x = (gx + (d - 0.5) * amt * 2.0).astype(np.float32)
        map_y = (gy + 0.0 * d).astype(np.float32)
        return cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REFLECT)


@register
class ShaderFX(Effect):
    """GPU fragment-shader effect (moderngl). Falls back to passthrough if no GL."""
    name, label, category = "shaderfx", "Shader FX (GPU)", "gpu"
    PARAMS = {
        "shader": ParamSpec("Shader", 0, 5, 0, 1, "choice",
                            ("chroma", "kaleido", "crt", "pixelate", "bloom", "displace")),
        "p1": ParamSpec("Param 1", 0, 1, 0.5, 0.01),
        "p2": ParamSpec("Param 2", 0, 1, 0.5, 0.01),
    }

    def process(self, frame, ctx, clock, s):
        from . import gpu
        name = gpu.SHADER_NAMES[int(self.v["shader"])]
        try:
            return gpu.process(name, frame, time=ctx.time, amount=s,
                               p1=self.v["p1"], p2=self.v["p2"])
        except Exception:
            return frame
