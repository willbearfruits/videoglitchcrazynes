"""Audio: load, granular synthesis sharing the frame grain schedule, and a
simple non-blocking player for live preview (sounddevice)."""
from __future__ import annotations
import numpy as np

from . import media


def load_audio(video_path: str, sr: int = 22050):
    """Extract + load a video's audio as mono float32. (samples, sr) or (None,sr)."""
    import os
    import tempfile
    wav = os.path.join(tempfile.gettempdir(),
                       "glitch_au_" + str(abs(hash(video_path)) % 99999) + ".wav")
    if not media.extract_audio(video_path, wav):
        return None, sr
    try:
        import soundfile as sf
        data, file_sr = sf.read(wav, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data, file_sr
    except Exception:
        return None, sr


def granulate_audio(samples, sr, grains, out_dur: float):
    """Resynthesize audio from the SAME grains the frame granulator used.

    Each grain reads `dur` seconds from `src_frac` at `rate` (negative=reverse),
    Hann-windowed, summed at its onset. Returns mono float32, peak-normalized.
    """
    n = len(samples)
    out = np.zeros(int(out_dur * sr) + sr, dtype=np.float32)
    if n == 0:
        return out
    for g in grains:
        out_len = int(g.dur * sr)
        if out_len < 2:
            continue
        src0 = g.src_frac * n
        idx = src0 + np.arange(out_len) * g.rate          # rate<0 => reverse
        idx = np.clip(idx, 0, n - 1)
        i0 = np.floor(idx).astype(np.int64)
        frac = (idx - i0).astype(np.float32)
        i1 = np.minimum(i0 + 1, n - 1)
        grain = samples[i0] * (1 - frac) + samples[i1] * frac
        win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(out_len) / out_len)
        grain = grain * win.astype(np.float32) * (g.gain * 0.5)
        a = int(g.onset * sr)
        b = min(len(out), a + out_len)
        if b > a:
            out[a:b] += grain[:b - a]
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 1.0:
        out /= peak
    return out


class AudioEnv:
    """Time-series audio feature envelopes (0..1): loudness + freq bands.
    Effects read value(source, t) to modulate their strength."""

    SOURCES = ("none", "rms", "bass", "mid", "high")

    def __init__(self, times, rms, bass, mid, high):
        self.times = np.asarray(times, dtype=np.float32)
        self.data = {"rms": np.asarray(rms, np.float32),
                     "bass": np.asarray(bass, np.float32),
                     "mid": np.asarray(mid, np.float32),
                     "high": np.asarray(high, np.float32)}

    def value(self, source: str, t: float) -> float:
        arr = self.data.get(source)
        if arr is None or self.times.size == 0:
            return 0.0
        return float(np.interp(t, self.times, arr))

    def scaled(self, factor: float):
        """Return a copy with the time axis scaled (for render speed changes)."""
        return AudioEnv(self.times * factor, *self.data.values())

    @classmethod
    def analyze(cls, samples, sr, hop: int = 512):
        if samples is None or len(samples) == 0:
            return None
        try:
            import librosa
            n_fft = 2048
            S = np.abs(librosa.stft(samples, n_fft=n_fft, hop_length=hop))
            freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
            times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
            bass = S[freqs < 250].sum(0)
            mid = S[(freqs >= 250) & (freqs < 4000)].sum(0)
            high = S[freqs >= 4000].sum(0)
            rms = np.sqrt((S ** 2).mean(0))

            def norm(x):
                x = np.asarray(x, np.float32)
                # light smoothing then normalize by 98th pct (ignore spikes)
                if x.size >= 5:
                    k = np.ones(5, np.float32) / 5
                    x = np.convolve(x, k, mode="same")
                p = np.percentile(x, 98) if x.size else 1.0
                return np.clip(x / (p + 1e-9), 0.0, 1.0)

            return cls(times, norm(rms), norm(bass), norm(mid), norm(high))
        except Exception as e:  # pragma: no cover
            print(f"[audio] envelope analysis failed: {e}")
            return None


class AudioPlayer:
    """Plays a numpy buffer from a given time. Best-effort; never raises."""

    def __init__(self):
        self.buf = None
        self.sr = 22050
        self._ok = True
        try:
            import sounddevice  # noqa: F401
        except Exception:
            self._ok = False

    def set_buffer(self, samples, sr):
        self.buf = samples
        self.sr = sr

    def play_from(self, t: float):
        if not self._ok or self.buf is None:
            return
        try:
            import sounddevice as sd
            i = max(0, int(t * self.sr))
            sd.stop()
            if i < len(self.buf):
                sd.play(self.buf[i:], self.sr)
        except Exception:
            self._ok = False

    def stop(self):
        if not self._ok:
            return
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass


class LiveAudioEnv:
    """Real-time audio envelopes from a live input (mic / system loopback).
    Interface-compatible with AudioEnv: value(source, t) + scaled()."""

    def __init__(self, device=None, sr=None, block: int = 1024):
        self.device = device
        if sr is None:                      # use the device's native rate
            try:
                import sounddevice as sd
                info = sd.query_devices(device, "input")
                sr = int(info["default_samplerate"])
            except Exception:
                sr = 48000
        self.sr = int(sr)
        self.block = block
        self._vals = {"rms": 0.0, "bass": 0.0, "mid": 0.0, "high": 0.0}
        self._peak = {"rms": 1e-6, "bass": 1e-6, "mid": 1e-6, "high": 1e-6}
        self._stream = None
        self._win = np.hanning(block).astype(np.float32)
        self._freqs = np.fft.rfftfreq(block, 1.0 / sr)

    def start(self):
        import sounddevice as sd
        self._stream = sd.InputStream(
            samplerate=self.sr, blocksize=self.block, channels=1,
            device=self.device, dtype="float32", callback=self._cb)
        self._stream.start()
        return self

    def _cb(self, indata, frames, t, status):
        x = indata[:, 0]
        if len(x) != self.block:
            x = np.resize(x, self.block)
        sp = np.abs(np.fft.rfft(x * self._win))
        f = self._freqs
        raw = {"bass": float(sp[f < 250].sum()),
               "mid": float(sp[(f >= 250) & (f < 4000)].sum()),
               "high": float(sp[f >= 4000].sum()),
               "rms": float(np.sqrt(np.mean(x ** 2)) * 6.0)}
        for k, val in raw.items():
            pk = max(val, self._peak[k] * 0.999, 1e-6)   # adaptive auto-gain
            self._peak[k] = pk
            norm = min(1.0, val / pk)
            self._vals[k] = self._vals[k] * 0.55 + norm * 0.45

    def value(self, source: str, t: float = 0.0) -> float:
        return float(self._vals.get(source, 0.0))

    def scaled(self, factor: float):
        return self

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
