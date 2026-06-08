"""Node-graph engine — a DAG (with feedback) of sources, effects, blends.

Each node is evaluated at most once per frame (memoized by an eval id). Feedback
is non-recursive: a FeedbackNode returns a tapped node's *previous frame* output
(every node stores `_prev` at end of frame), so loops can't recurse infinitely.
This is what enables classic video-feedback trails.
"""
from __future__ import annotations
import numpy as np
import cv2

from .blend import blend, MODES
from .chain import Chain
from .context import BeatClock


class Node:
    type = "node"

    def __init__(self, nid: str):
        self.id = nid
        self.inputs: list = []     # node ids per input port (or None)
        self.x = 0.0
        self.y = 0.0               # editor position
        self._cache = None
        self._cache_id = -1
        self._prev = None

    def n_inputs(self) -> int:
        return 0

    def evaluate(self, g, t, eid):
        if self._cache_id == eid:
            return self._cache
        self._cache = self.compute(g, t, eid)
        self._cache_id = eid
        return self._cache

    def compute(self, g, t, eid):
        return g.black()

    def _in(self, g, idx, t, eid):
        if idx < len(self.inputs) and self.inputs[idx] is not None:
            src = g.nodes.get(self.inputs[idx])
            if src is not None:
                return src.evaluate(g, t, eid)
        return g.black()


class SourceNode(Node):
    type = "source"

    def __init__(self, nid, source=None, granulator=None, label="source"):
        super().__init__(nid)
        self.source = source
        self.granulator = granulator
        self.label = label

    def compute(self, g, t, eid):
        if self.granulator is not None:
            img = self.granulator.render(t, g.w, g.h)
        elif self.source is not None:
            f = self.source.frame_at_time(t)
            img = g.black() if f is None else f
        else:
            return g.black()
        if img.shape[1] != g.w or img.shape[0] != g.h:
            img = cv2.resize(img, (g.w, g.h))
        return img


class EffectNode(Node):
    type = "effect"

    def __init__(self, nid, chain=None, label="fx"):
        super().__init__(nid)
        self.chain = chain or Chain()
        self.label = label

    def n_inputs(self):
        return 1

    def compute(self, g, t, eid):
        frame = self._in(g, 0, t, eid)
        if not self.chain.effects:
            return frame
        return self.chain.process_frame(frame, int(t * g.fps), t, g.fps,
                                        g.total, g.clock, audio=g.audio)


class BlendNode(Node):
    type = "blend"

    def __init__(self, nid, mode="screen", opacity=1.0):
        super().__init__(nid)
        self.mode = mode
        self.opacity = opacity

    def n_inputs(self):
        return 2

    def compute(self, g, t, eid):
        a = self._in(g, 0, t, eid)
        b = self._in(g, 1, t, eid)
        return blend(self.mode, a, b, self.opacity)


class FeedbackNode(Node):
    """Outputs the *previous frame* of the tapped node — breaks cycles."""
    type = "feedback"

    def __init__(self, nid, target=None):
        super().__init__(nid)
        self.target = target

    def compute(self, g, t, eid):
        tgt = g.nodes.get(self.target) if self.target else None
        if tgt is not None and tgt._prev is not None:
            return tgt._prev
        return g.black()


class OutputNode(Node):
    type = "output"

    def n_inputs(self):
        return 1

    def compute(self, g, t, eid):
        return self._in(g, 0, t, eid)


NODE_TYPES = {"source": SourceNode, "effect": EffectNode, "blend": BlendNode,
              "feedback": FeedbackNode, "output": OutputNode}


class Graph:
    def __init__(self, w=640, h=360, fps=30.0):
        self.nodes: dict[str, Node] = {}
        self.w, self.h, self.fps = w, h, fps
        self.clock = BeatClock([], fps)
        self.audio = None
        self.total = 0
        self.output_id = None
        self._eid = 0
        self._black = None
        self._counter = 0

    def black(self):
        if self._black is None or self._black.shape[:2] != (self.h, self.w):
            self._black = np.zeros((self.h, self.w, 3), np.uint8)
        return self._black

    def new_id(self, kind):
        self._counter += 1
        return f"{kind}{self._counter}"

    def add(self, node: Node):
        self.nodes[node.id] = node
        if node.type == "output" and self.output_id is None:
            self.output_id = node.id
        return node

    def remove(self, nid):
        self.nodes.pop(nid, None)
        for n in self.nodes.values():
            n.inputs = [None if i == nid else i for i in n.inputs]
            if getattr(n, "target", None) == nid:
                n.target = None

    def connect(self, src_id, dst_id, port=0):
        dst = self.nodes[dst_id]
        while len(dst.inputs) <= port:
            dst.inputs.append(None)
        dst.inputs[port] = src_id

    def render_frame(self, t):
        self._eid += 1
        out = self.nodes.get(self.output_id)
        if out is None:
            return self.black()
        val = out.evaluate(self, t, self._eid)
        for n in self.nodes.values():        # store prev for feedback taps
            if n._cache_id == self._eid:
                n._prev = n._cache
        return val

    def reset(self):
        for n in self.nodes.values():
            n._prev = None
            n._cache_id = -1
            if isinstance(n, EffectNode):
                n.chain.reset()
