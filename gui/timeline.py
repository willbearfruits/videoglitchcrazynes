"""A thin timeline that draws onset/beat ticks and a draggable playhead."""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui


class BeatBar(QtWidgets.QWidget):
    seek = QtCore.Signal(float)  # fraction 0..1

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.beats: list[float] = []
        self.onsets: list[float] = []
        self.duration = 1.0
        self.playhead = 0.0  # seconds

    def set_beats(self, beats, onsets, duration):
        self.beats = list(beats or [])
        self.onsets = list(onsets or [])
        self.duration = max(0.001, float(duration))
        self.update()

    def set_playhead(self, t):
        self.playhead = float(t)
        self.update()

    def mousePressEvent(self, e):
        f = e.position().x() / max(1, self.width())
        self.seek.emit(max(0.0, min(1.0, f)))

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self.mousePressEvent(e)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QtGui.QColor("#161616"))

        def x(t):
            return int(t / self.duration * w)

        p.setPen(QtGui.QPen(QtGui.QColor("#3a3a3a"), 1))
        for t in self.onsets:
            p.drawLine(x(t), h - 10, x(t), h)

        p.setPen(QtGui.QPen(QtGui.QColor("#00e5ff"), 1))
        for t in self.beats:
            p.drawLine(x(t), 4, x(t), h)

        px = x(self.playhead)
        p.setPen(QtGui.QPen(QtGui.QColor("#ff2d55"), 2))
        p.drawLine(px, 0, px, h)
        p.setBrush(QtGui.QColor("#ff2d55"))
        p.drawPolygon(QtGui.QPolygon([
            QtCore.QPoint(px - 5, 0), QtCore.QPoint(px + 5, 0), QtCore.QPoint(px, 8)]))
