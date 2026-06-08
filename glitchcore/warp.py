"""Variable, beat-driven time-remap.

A TimeWarp maps a layer's local timeline time -> source *content* time. The
output duration and the music bed are unchanged — only the video's sampling
position warps, so you get freeze / speed-ramp / reverse hits locked to the beat
over steady audio. That's the lobotomy time-feel.
"""
from __future__ import annotations
import numpy as np

from .params import ParamSpec


class TimeWarp:
    PARAMS = {
        "freeze":    ParamSpec("Freeze prob", 0, 1, 0.30, 0.05),
        "ramp":      ParamSpec("Ramp prob", 0, 1, 0.25, 0.05),
        "reverse":   ParamSpec("Reverse prob", 0, 1, 0.15, 0.05),
        "jump":      ParamSpec("Jump prob", 0, 1, 0.10, 0.05),
        "ramp_rate": ParamSpec("Ramp rate", 1.5, 8, 4.0, 0.5),
        "subdiv":    ParamSpec("Subdivide", 1, 4, 2, 1, "int"),
    }

    def __init__(self, seed: int = 99):
        self.v = {k: float(s.default) for k, s in self.PARAMS.items()}
        self.seed = seed
        self.ctrl_out = np.array([0.0, 1.0])
        self.ctrl_c = np.array([0.0, 1.0])
        self.content_dur = 1.0

    def build(self, beats, duration: float, content_dur: float):
        self.content_dur = max(0.1, float(content_dur))
        rng = np.random.default_rng(self.seed)
        v = self.v
        bs = [b for b in (beats or []) if 0 <= b <= duration]
        if not bs or bs[0] > 0:
            bs = [0.0] + bs
        if bs[-1] < duration:
            bs = bs + [duration]
        sub = max(1, int(v["subdiv"]))
        segs = []
        for i in range(len(bs) - 1):
            a, b = bs[i], bs[i + 1]
            for k in range(sub):
                segs.append((a + (b - a) * k / sub, a + (b - a) * (k + 1) / sub))

        out, con, c = [0.0], [0.0], 0.0
        pf = v["freeze"]
        pr = pf + v["ramp"]
        pv = pr + v["reverse"]
        pj = pv + v["jump"]
        for a, b in segs:
            L = b - a
            r = rng.random()
            if r < pf:                       # freeze: content holds
                pass
            elif r < pr:                     # ramp forward fast
                c += L * v["ramp_rate"]
            elif r < pv:                     # reverse
                c -= L * v["ramp_rate"]
            elif r < pj:                     # jump to a random moment
                c = rng.random() * self.content_dur
            else:                            # normal
                c += L
            c = float(np.clip(c, 0.0, self.content_dur))
            out.append(b)
            con.append(c)
        # guard monotonic out axis for np.interp
        self.ctrl_out = np.maximum.accumulate(np.array(out))
        self.ctrl_c = np.array(con)
        return self

    def map(self, t: float) -> float:
        return float(np.interp(t, self.ctrl_out, self.ctrl_c))

    def to_dict(self):
        return {"seed": self.seed, "v": dict(self.v)}

    def load(self, d):
        self.seed = d.get("seed", self.seed)
        for k, val in d.get("v", {}).items():
            if k in self.v:
                self.v[k] = val
        return self
