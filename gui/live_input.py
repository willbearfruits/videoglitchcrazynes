"""Live input hub — polls an Xbox-style gamepad (pygame) and MIDI (rtmidi),
emitting normalized control events the GUI maps to params.

Control ids: "axis 0".."axis N" (0..1), "button 0".."button M" (0/1),
"cc <n>" (0..1). Hotplug-aware: a controller plugged in after launch is picked
up. SDL reads /dev/input/event*, so the user must be in the `input` group.
"""
from __future__ import annotations
import os
from PySide6 import QtCore


class InputHub(QtCore.QThread):
    control = QtCore.Signal(str, float)
    status = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self._run = True
        self.joy = None
        self.midi = None

    def stop(self):
        self._run = False

    def _emit_status(self, pygame):
        names = []
        if pygame is not None and pygame.joystick.get_count() > 0:
            try:
                names.append(f"🎮 {pygame.joystick.Joystick(0).get_name()}")
            except Exception:
                names.append("🎮 gamepad")
        if self.midi is not None:
            names.append("🎹 MIDI")
        if not names:
            hint = ""
            if not os.access("/dev/input/event0", os.R_OK):
                hint = "  (no /dev/input access — add user to 'input' group)"
            names.append("no gamepad / MIDI" + hint)
        self.status.emit("  ·  ".join(names))

    def run(self):
        # only force a headless SDL driver if there's genuinely no display
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame = None
        try:
            import pygame as _pg
            pygame = _pg
            pygame.init()
            pygame.joystick.init()
        except Exception:
            pygame = None
        try:
            import rtmidi
            self.midi = rtmidi.MidiIn()
            if self.midi.get_ports():
                self.midi.open_port(0)
            else:
                self.midi = None
        except Exception:
            self.midi = None
        self._emit_status(pygame)

        last = {}
        joy_count = 0
        while self._run:
            if pygame is not None:
                try:
                    pygame.event.pump()
                    c = pygame.joystick.get_count()
                    if c != joy_count:                  # hotplug
                        joy_count = c
                        self.joy = None
                        if c > 0:
                            self.joy = pygame.joystick.Joystick(0)
                            self.joy.init()
                        self._emit_status(pygame)
                    if self.joy is not None:
                        for a in range(self.joy.get_numaxes()):
                            v = self.joy.get_axis(a)
                            cid = f"axis {a}"
                            if abs(v - last.get(cid, -9)) > 0.02:
                                last[cid] = v
                                self.control.emit(cid, (v + 1.0) / 2.0)
                        for b in range(self.joy.get_numbuttons()):
                            v = float(self.joy.get_button(b))
                            cid = f"button {b}"
                            if v != last.get(cid, -9):
                                last[cid] = v
                                self.control.emit(cid, v)
                except Exception:
                    pass
            if self.midi is not None:
                try:
                    msg = self.midi.get_message()
                    while msg:
                        data, _ = msg
                        if len(data) >= 3 and 0xB0 <= data[0] <= 0xBF:
                            self.control.emit(f"cc {data[1]}", data[2] / 127.0)
                        msg = self.midi.get_message()
                except Exception:
                    pass
            self.msleep(16)

        try:
            if self.midi is not None:
                self.midi.close_port()
        except Exception:
            pass


# control ids offered in the mapping dropdowns
CONTROL_IDS = (["(none)"]
               + [f"axis {i}" for i in range(6)]
               + [f"button {i}" for i in range(11)]
               + [f"cc {i}" for i in range(1, 17)])
