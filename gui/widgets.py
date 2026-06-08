"""Reusable widgets: an auto-built control row and the per-effect card."""
from __future__ import annotations
from PySide6 import QtWidgets, QtCore

from glitchcore.params import ParamSpec
from .live_input import CONTROL_IDS


class ParamRow(QtWidgets.QWidget):
    """One label + control bound to a setter. Handles float/int/bool/choice."""
    changed = QtCore.Signal()

    def __init__(self, label, spec: ParamSpec, value, setter):
        super().__init__()
        self.spec = spec
        self.setter = setter
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lab = QtWidgets.QLabel(label)
        lab.setMinimumWidth(92)
        lay.addWidget(lab)

        if spec.kind == "bool":
            self.w = QtWidgets.QCheckBox()
            self.w.setChecked(value > 0.5)
            self.w.toggled.connect(lambda b: self._emit(1.0 if b else 0.0))
            lay.addWidget(self.w)
            lay.addStretch(1)
        elif spec.kind == "choice":
            self.w = QtWidgets.QComboBox()
            self.w.addItems(list(spec.choices))
            self.w.setCurrentIndex(int(value))
            self.w.currentIndexChanged.connect(lambda i: self._emit(float(i)))
            lay.addWidget(self.w, 1)
        else:
            self.is_int = spec.kind == "int"
            self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            if self.is_int:
                self.slider.setRange(int(spec.min), int(spec.max))
                self.slider.setValue(int(round(value)))
            else:
                self.slider.setRange(0, 1000)
                self.slider.setValue(self._to_slider(value))
            self.val = QtWidgets.QLabel()
            self.val.setMinimumWidth(44)
            self.val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            self.slider.valueChanged.connect(self._slider_changed)
            lay.addWidget(self.slider, 1)
            lay.addWidget(self.val)
            self._update_label(value)

    def _to_slider(self, v):
        f = (v - self.spec.min) / max(1e-9, (self.spec.max - self.spec.min))
        return int(round(f * 1000))

    def _from_slider(self, s):
        return self.spec.min + (s / 1000.0) * (self.spec.max - self.spec.min)

    def _slider_changed(self, s):
        v = float(s) if self.is_int else self._from_slider(s)
        self._update_label(v)
        self._emit(v)

    def _update_label(self, v):
        if self.is_int:
            self.val.setText(f"{int(round(v))}")
        else:
            self.val.setText(f"{v:.2f}")

    def _emit(self, v):
        self.setter(v)
        self.changed.emit()


class EffectCard(QtWidgets.QFrame):
    """Header (enable / title / move / remove) + body of auto-built controls."""
    changed = QtCore.Signal()
    remove_me = QtCore.Signal(object)
    move_me = QtCore.Signal(object, int)

    def __init__(self, eff):
        super().__init__()
        self.eff = eff
        self.setObjectName("EffectCard")
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(4)

        # -- header --
        hdr = QtWidgets.QHBoxLayout()
        self.en = QtWidgets.QCheckBox()
        self.en.setChecked(eff.enabled)
        self.en.toggled.connect(self._toggle_enabled)
        title = QtWidgets.QLabel(eff.label)
        title.setStyleSheet("font-weight:600;")
        hdr.addWidget(self.en)
        hdr.addWidget(title)
        hdr.addStretch(1)
        for txt, slot in (("▲", lambda: self.move_me.emit(self.eff, -1)),
                          ("▼", lambda: self.move_me.emit(self.eff, 1)),
                          ("✕", lambda: self.remove_me.emit(self.eff))):
            b = QtWidgets.QToolButton()
            b.setText(txt)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            hdr.addWidget(b)
        root.addLayout(hdr)

        self.body = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(self.body)
        body_lay.setContentsMargins(2, 0, 2, 0)
        body_lay.setSpacing(1)
        root.addWidget(self.body)

        # -- common controls --
        self._add_row("Amount", ParamSpec("Amount", 0, 1, eff.amount),
                      eff.amount, lambda v: setattr(eff, "amount", v))

        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["always", "pulse", "gate"])
        self.mode.setCurrentText(eff.beat_mode)
        self.mode.currentTextChanged.connect(self._set_mode)
        moderow = QtWidgets.QHBoxLayout()
        ml = QtWidgets.QLabel("Beat")
        ml.setMinimumWidth(92)
        moderow.addWidget(ml)
        moderow.addWidget(self.mode, 1)
        moderow.addWidget(QtWidgets.QLabel("÷"))
        self.div = QtWidgets.QSpinBox()
        self.div.setRange(1, 16)
        self.div.setValue(eff.beat_div)
        self.div.valueChanged.connect(lambda v: (setattr(eff, "beat_div", v),
                                                 self.changed.emit()))
        moderow.addWidget(self.div)
        body_lay.addLayout(moderow)

        self._hold_row = self._add_row(
            "Hold (s)", ParamSpec("Hold", 0.02, 1.0, eff.hold),
            eff.hold, lambda v: setattr(eff, "hold", v))

        # audio-reactive modulation row
        arow = QtWidgets.QHBoxLayout()
        al = QtWidgets.QLabel("Audio")
        al.setMinimumWidth(92)
        arow.addWidget(al)
        self.mod = QtWidgets.QComboBox()
        self.mod.addItems(["none", "rms", "bass", "mid", "high"])
        self.mod.setCurrentText(eff.mod_source)
        self.mod.currentTextChanged.connect(self._set_mod)
        arow.addWidget(self.mod, 1)
        body_lay.addLayout(arow)
        self._depth_row = self._add_row(
            "Mod depth", ParamSpec("Mod depth", 0.0, 1.0, eff.mod_depth),
            eff.mod_depth, lambda v: setattr(eff, "mod_depth", v))

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet("color:#333;")
        body_lay.addWidget(sep)

        # -- per-effect params --
        for key, spec in eff.PARAMS.items():
            self._add_row(spec.label, spec, eff.v[key],
                          (lambda k: lambda v: eff.v.__setitem__(k, v))(key))

        self._sync_enabled()
        self._sync_hold()
        self._depth_row.setVisible(self.eff.mod_source != "none")

    # body helper
    def _add_row(self, label, spec, value, setter):
        row = ParamRow(label, spec, value, setter)
        row.changed.connect(self.changed.emit)
        self.body.layout().addWidget(row)
        return row

    def _toggle_enabled(self, b):
        self.eff.enabled = b
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self):
        self.body.setEnabled(self.eff.enabled)
        self.setStyleSheet(
            "" if self.eff.enabled
            else "#EffectCard{background:#101016;border:1px solid #1e1e2a;}")

    def _set_mode(self, m):
        self.eff.beat_mode = m
        self._sync_hold()
        self.changed.emit()

    def _sync_hold(self):
        self._hold_row.setVisible(self.eff.beat_mode != "always" and not self.eff.self_gated)
        self.div.setEnabled(self.eff.beat_mode != "always" or self.eff.self_gated)

    def _set_mod(self, src):
        self.eff.mod_source = src
        self._depth_row.setVisible(src != "none")
        self.changed.emit()


class GranularPanel(QtWidgets.QWidget):
    """Auto-built controls for a Granulator's params + seed."""
    changed = QtCore.Signal()

    def __init__(self, granulator):
        super().__init__()
        self.g = granulator
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(1)
        lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        srow = QtWidgets.QHBoxLayout()
        sl = QtWidgets.QLabel("Seed")
        sl.setMinimumWidth(92)
        srow.addWidget(sl)
        self.seed = QtWidgets.QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(granulator.seed)
        self.seed.valueChanged.connect(lambda v: (setattr(self.g, "seed", v),
                                                  self.changed.emit()))
        srow.addWidget(self.seed, 1)
        lay.addLayout(srow)

        for key, spec in self.g.PARAMS.items():
            row = ParamRow(spec.label, spec, self.g.v[key],
                           (lambda k: lambda v: self.g.v.__setitem__(k, v))(key))
            row.changed.connect(self.changed.emit)
            lay.addWidget(row)


class LivePanel(QtWidgets.QWidget):
    """Maps gamepad/MIDI controls to targets on the selected layer."""
    applied = QtCore.Signal()

    def __init__(self, n_rows: int = 6):
        super().__init__()
        self.targets: list = []          # [(label, apply_fn), ...]
        self.rows: list = []             # [(control_combo, target_combo), ...]
        lay = QtWidgets.QVBoxLayout(self)
        lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.dev_lbl = QtWidgets.QLabel("Live input off")
        self.dev_lbl.setWordWrap(True)
        lay.addWidget(self.dev_lbl)
        self.enable = QtWidgets.QCheckBox("Enable gamepad / MIDI")
        lay.addWidget(self.enable)
        lay.addWidget(QtWidgets.QLabel(
            "Map a control to a param of the selected layer:"))

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Control"), 0, 0)
        grid.addWidget(QtWidgets.QLabel("→ Target"), 0, 1)
        for i in range(n_rows):
            cc = QtWidgets.QComboBox()
            cc.addItems(CONTROL_IDS)
            tc = QtWidgets.QComboBox()
            tc.addItem("(none)")
            grid.addWidget(cc, i + 1, 0)
            grid.addWidget(tc, i + 1, 1)
            self.rows.append((cc, tc))
        lay.addLayout(grid)
        lay.addStretch(1)

    def set_targets(self, targets):
        self.targets = targets
        labels = ["(none)"] + [t[0] for t in targets]
        for _cc, tc in self.rows:
            cur = tc.currentText()
            tc.blockSignals(True)
            tc.clear()
            tc.addItems(labels)
            tc.setCurrentIndex(labels.index(cur) if cur in labels else 0)
            tc.blockSignals(False)

    def handle(self, cid: str, val: float):
        hit = False
        for cc, tc in self.rows:
            if cc.currentText() == cid and tc.currentIndex() > 0:
                idx = tc.currentIndex() - 1
                if idx < len(self.targets):
                    self.targets[idx][1](val)
                    hit = True
        if hit:
            self.applied.emit()
