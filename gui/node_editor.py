"""Visual node-graph editor (Phase 3). Click an output port then an input port
to wire. Sources come from the main window's layers; the graph evaluates live to
a preview. Feedback nodes enable video-feedback trails."""
from __future__ import annotations
import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from glitchcore.graph import (Graph, SourceNode, EffectNode, BlendNode,
                              FeedbackNode, OutputNode)
from glitchcore import effects as fx
from glitchcore.blend import MODES
from glitchcore.chain import Chain

PORT_R = 6
NODE_W, NODE_H = 150, 30


def _pix(bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QtGui.QPixmap.fromImage(
        QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy())


class NodeItem(QtWidgets.QGraphicsRectItem):
    def __init__(self, node, editor):
        rows = max(node.n_inputs(), 1)
        super().__init__(0, 0, NODE_W, NODE_H + (rows - 1) * 18)
        self.node = node
        self.editor = editor
        colors = {"source": "#26543a", "effect": "#3a3560", "blend": "#553a3a",
                  "feedback": "#5a5226", "output": "#264a54"}
        self.setBrush(QtGui.QColor(colors.get(node.type, "#333")))
        self.setPen(QtGui.QPen(QtGui.QColor("#7a8ad0"), 2))
        self.setFlags(self.GraphicsItemFlag.ItemIsMovable
                      | self.GraphicsItemFlag.ItemIsSelectable)
        self.setPos(node.x, node.y)
        self.setZValue(1)
        t = QtWidgets.QGraphicsSimpleTextItem(self.title(), self)
        t.setBrush(QtGui.QColor("#eee"))
        t.setPos(20, 7)
        self.in_dots = []
        for i in range(node.n_inputs()):
            d = QtWidgets.QGraphicsEllipseItem(-PORT_R, 9 + i * 18, 2 * PORT_R, 2 * PORT_R, self)
            d.setBrush(QtGui.QColor("#9fe0c0"))
            d.setData(0, ("in", node.id, i))
            self.in_dots.append(d)
        self.out_dot = None
        if node.type != "output":
            self.out_dot = QtWidgets.QGraphicsEllipseItem(
                NODE_W - PORT_R, 9, 2 * PORT_R, 2 * PORT_R, self)   # child of node
            self.out_dot.setBrush(QtGui.QColor("#e0c89f"))
            self.out_dot.setData(0, ("out", node.id, 0))

    def title(self):
        n = self.node
        if n.type == "source":
            return f"◳ {n.label}"
        if n.type == "effect":
            return "fx: " + (",".join(e.name for e in n.chain.effects) or "empty")
        if n.type == "blend":
            return f"⊕ {n.mode}"
        if n.type == "feedback":
            return f"↺ fb→{n.target or '?'}"
        return "OUTPUT"

    def in_pos(self, i):
        return self.scenePos() + QtCore.QPointF(0, 9 + i * 18 + PORT_R)

    def out_pos(self):
        return self.scenePos() + QtCore.QPointF(NODE_W, 9 + PORT_R)


class NodeScene(QtWidgets.QGraphicsScene):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor

    def mousePressEvent(self, e):
        items = self.items(e.scenePos())
        for it in items:
            d = it.data(0)
            if d:
                kind, nid, idx = d
                self.editor.port_clicked(kind, nid, idx)
                e.accept()
                return
        super().mousePressEvent(e)


class NodeEditor(QtWidgets.QMainWindow):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setWindowTitle("Node Graph")
        self.resize(1000, 620)
        L = main.timeline
        self.graph = Graph(w=480, h=270, fps=L.fps or 30.0)
        self.graph.clock = main.clock
        self.graph.audio = main.audio_env
        self.items: dict[str, NodeItem] = {}
        self.edges: list = []
        self.pending = None       # (node_id) awaiting an input click
        self.t = 0.0

        cen = QtWidgets.QWidget()
        self.setCentralWidget(cen)
        lay = QtWidgets.QVBoxLayout(cen)
        tb = QtWidgets.QHBoxLayout()
        for label, slot in (("+ Source", self.add_source), ("+ Effect", self.add_effect),
                            ("+ Blend", self.add_blend), ("+ Feedback", self.add_feedback),
                            ("Delete", self.delete_sel)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            tb.addWidget(b)
        tb.addStretch(1)
        self.play_btn = QtWidgets.QPushButton("▶ Play")
        self.play_btn.clicked.connect(self.toggle_play)
        tb.addWidget(self.play_btn)
        lay.addLayout(tb)

        split = QtWidgets.QSplitter()
        self.scene = NodeScene(self)
        self.view = QtWidgets.QGraphicsView(self.scene)
        self.view.setBackgroundBrush(QtGui.QColor("#1a1a1a"))
        split.addWidget(self.view)
        self.preview = QtWidgets.QLabel("graph output")
        self.preview.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(360)
        self.preview.setStyleSheet("background:#000;")
        split.addWidget(self.preview)
        split.setSizes([620, 380])
        lay.addWidget(split, 1)
        self.hint = QtWidgets.QLabel("Click an output port (right) then an input port (left) to wire.")
        lay.addWidget(self.hint)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._build_default()

    # ---- node creation ----
    def _add_item(self, node):
        self.graph.add(node)
        it = NodeItem(node, self)
        self.items[node.id] = it
        self.scene.addItem(it)        # child port dots are added with it
        return it

    def _build_default(self):
        out = OutputNode("out")
        out.x, out.y = 410, 110           # keep it inside the visible view
        self._add_item(out)
        self.graph.output_id = "out"
        # seed a source from the first available layer
        layer = next((l for l in self.main.timeline.layers), None)
        if layer is not None:
            self._make_source(layer, 40, 110)
        self._redraw_edges()
        self.view.centerOn(280, 150)

    def _make_source(self, layer, x, y):
        nid = self.graph.new_id("src")
        n = SourceNode(nid, source=layer.source, granulator=layer.granulator, label=layer.name)
        n.x, n.y = x, y
        self._add_item(n)
        return n

    def add_source(self):
        if not self.main.timeline.layers:
            QtWidgets.QMessageBox.information(self, "Source", "Add a layer in the main window first.")
            return
        names = [l.name for l in self.main.timeline.layers]
        name, ok = QtWidgets.QInputDialog.getItem(self, "Source layer", "Layer:", names, 0, False)
        if ok:
            layer = self.main.timeline.layers[names.index(name)]
            self._make_source(layer, 60, 60 + 90 * (len(self.items) % 4))
            self._redraw_edges()

    def add_effect(self):
        names = list(fx.EFFECT_ORDER)
        labels = [fx.REGISTRY[n].label for n in names]
        lab, ok = QtWidgets.QInputDialog.getItem(self, "Effect", "Effect:", labels, 0, False)
        if ok:
            nid = self.graph.new_id("fx")
            n = EffectNode(nid)
            n.chain.add(fx.make(names[labels.index(lab)]))
            n.x, n.y = 300, 60 + 90 * (len(self.items) % 4)
            self._add_item(n)
            self._redraw_edges()

    def add_blend(self):
        mode, ok = QtWidgets.QInputDialog.getItem(self, "Blend", "Mode:", MODES, 1, False)
        if ok:
            nid = self.graph.new_id("mix")
            n = BlendNode(nid, mode=mode)
            n.x, n.y = 480, 80 + 90 * (len(self.items) % 3)
            self._add_item(n)
            self._redraw_edges()

    def add_feedback(self):
        ids = [k for k in self.graph.nodes if self.graph.nodes[k].type != "feedback"]
        if not ids:
            return
        tgt, ok = QtWidgets.QInputDialog.getItem(self, "Feedback", "Tap node (prev frame):", ids, 0, False)
        if ok:
            nid = self.graph.new_id("fb")
            n = FeedbackNode(nid, target=tgt)
            n.x, n.y = 480, 240
            self._add_item(n)
            self._redraw_edges()

    def delete_sel(self):
        for it in list(self.scene.selectedItems()):
            if isinstance(it, NodeItem) and it.node.type != "output":
                self.graph.remove(it.node.id)
                self.items.pop(it.node.id, None)
        self._rebuild_scene()

    # ---- wiring ----
    def port_clicked(self, kind, nid, idx):
        if kind == "out":
            self.pending = nid
            self.hint.setText(f"output of {nid} selected — now click an input port")
        elif kind == "in" and self.pending:
            if self.pending != nid:
                self.graph.connect(self.pending, nid, idx)
            self.pending = None
            self.hint.setText("wired ✓  Click an output then an input to wire more.")
            self._redraw_edges()

    def _redraw_edges(self):
        for e in self.edges:
            self.scene.removeItem(e)
        self.edges = []
        for nid, node in self.graph.nodes.items():
            dst = self.items.get(nid)
            if not dst:
                continue
            for i, src_id in enumerate(node.inputs):
                src = self.items.get(src_id) if src_id else None
                if src is None:
                    continue
                p1 = src.out_pos()
                p2 = dst.in_pos(i)
                path = QtGui.QPainterPath(p1)
                dx = max(40, abs(p2.x() - p1.x()) * 0.5)
                path.cubicTo(p1 + QtCore.QPointF(dx, 0), p2 - QtCore.QPointF(dx, 0), p2)
                e = QtWidgets.QGraphicsPathItem(path)
                col = "#e0c050" if self.graph.nodes[src_id].type == "feedback" else "#7a8ad0"
                e.setPen(QtGui.QPen(QtGui.QColor(col), 2))
                e.setZValue(0)
                self.scene.addItem(e)
                self.edges.append(e)

    def _rebuild_scene(self):
        self.scene.clear()
        self.items = {}
        self.edges = []
        for node in self.graph.nodes.values():
            it = NodeItem(node, self)
            self.items[node.id] = it
            self.scene.addItem(it)
        self._redraw_edges()

    # ---- playback ----
    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play_btn.setText("▶ Play")
        else:
            self.graph.audio = self.main.audio_env
            self.graph.clock = self.main.clock
            self.graph.total = int(self.main.timeline.duration() * self.graph.fps)
            self.graph.reset()
            self.timer.start(int(1000 / max(1, self.graph.fps)))
            self.play_btn.setText("⏸ Pause")

    def _tick(self):
        dur = max(0.5, self.main.timeline.duration())
        self.t += 1.0 / max(1, self.graph.fps)
        if self.t >= dur:
            self.t = 0.0
            self.graph.reset()
        # sync node positions moved by the user
        for nid, it in self.items.items():
            it.node.x, it.node.y = it.scenePos().x(), it.scenePos().y()
        self._redraw_edges()
        frame = self.graph.render_frame(self.t)
        self.preview.setPixmap(_pix(frame))

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)
