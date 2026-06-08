"""Background workers: beat detection + full render (each on its own QThread)."""
from __future__ import annotations
import os
import tempfile
from PySide6 import QtCore

from glitchcore import beat as beatmod, media
from glitchcore import audio as audiomod
from glitchcore.chain import Chain
from glitchcore.renderer import render, render_timeline, RenderOptions


class BeatWorker(QtCore.QThread):
    done = QtCore.Signal(dict)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        info = media.probe(self.path)
        result = {"beats": [], "onsets": [], "tempo": 0.0,
                  "duration": info.duration, "env": None}
        if info.has_audio:
            wav = os.path.join(tempfile.gettempdir(), "glitch_beats.wav")
            if media.extract_audio(self.path, wav):
                result.update(beatmod.detect_beats(wav))
                try:
                    import soundfile as sf
                    y, file_sr = sf.read(wav, dtype="float32")
                    if y.ndim > 1:
                        y = y.mean(axis=1)
                    result["env"] = audiomod.AudioEnv.analyze(y, file_sr)
                except Exception:
                    result["env"] = None
        if not result["beats"]:
            # no audio / silent — fall back to a 120bpm grid so beat fx still fire
            result["beats"] = beatmod.grid_beats(info.duration, 120.0)
        self.done.emit(result)


class RenderWorker(QtCore.QThread):
    progress = QtCore.Signal(float, str)
    finished_ok = QtCore.Signal(bool, str)

    def __init__(self, input_path, out_path, chain_dict, beats, opts: RenderOptions):
        super().__init__()
        self.input_path = input_path
        self.out_path = out_path
        self.chain_dict = chain_dict  # serialized so the worker owns its own state
        self.beats = beats
        self.opts = opts
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            chain = Chain().load(self.chain_dict)
            ok = render(self.input_path, self.out_path, chain, self.beats, self.opts,
                        progress=lambda f, m: self.progress.emit(f, m),
                        should_cancel=lambda: self._cancel)
            if ok:
                self.finished_ok.emit(True, self.out_path)
            else:
                self.finished_ok.emit(False, "Cancelled")
        except Exception as e:  # pragma: no cover
            self.finished_ok.emit(False, f"Error: {e}")


class TimelineRenderWorker(QtCore.QThread):
    """Renders a multi-layer Timeline (shared live object; preview is paused)."""
    progress = QtCore.Signal(float, str)
    finished_ok = QtCore.Signal(bool, str)

    def __init__(self, timeline, out_path, beats, opts: RenderOptions,
                 audio_buffer=None, audio_sr=22050, audio_src_path=None,
                 audio_env=None):
        super().__init__()
        self.timeline = timeline
        self.out_path = out_path
        self.beats = beats
        self.opts = opts
        self.audio_buffer = audio_buffer
        self.audio_sr = audio_sr
        self.audio_src_path = audio_src_path
        self.audio_env = audio_env
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            ok = render_timeline(
                self.timeline, self.out_path, self.beats, self.opts,
                progress=lambda f, m: self.progress.emit(f, m),
                should_cancel=lambda: self._cancel,
                audio_buffer=self.audio_buffer, audio_sr=self.audio_sr,
                audio_src_path=self.audio_src_path, audio_env=self.audio_env)
            self.finished_ok.emit(bool(ok), self.out_path if ok else "Cancelled")
        except Exception as e:  # pragma: no cover
            self.finished_ok.emit(False, f"Error: {e}")
