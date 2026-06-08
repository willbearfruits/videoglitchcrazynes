"""Audio beat / onset detection via librosa."""
from __future__ import annotations
import logging
import numpy as np

log = logging.getLogger(__name__)


def detect_beats(audio_path: str, sr: int = 22050) -> dict:
    """Return {'beats':[s], 'onsets':[s], 'tempo':bpm}. Empty on failure."""
    try:
        import librosa
    except Exception:
        return {"beats": [], "onsets": [], "tempo": 0.0}
    try:
        y, sr = librosa.load(audio_path, sr=sr, mono=True)
        if y.size == 0:
            return {"beats": [], "onsets": [], "tempo": 0.0}
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        tempo = float(np.atleast_1d(tempo)[0])
        return {"beats": np.asarray(beats, float).tolist(),
                "onsets": np.asarray(onsets, float).tolist(),
                "tempo": tempo}
    except Exception as e:  # pragma: no cover
        log.warning("beat detection failed: %s", e)
        return {"beats": [], "onsets": [], "tempo": 0.0}


def grid_beats(duration: float, bpm: float = 120.0, offset: float = 0.0) -> list:
    """Fallback: a synthetic beat grid when there's no audio."""
    if bpm <= 0:
        return []
    step = 60.0 / bpm
    n = int((duration - offset) / step) + 1
    return [offset + i * step for i in range(max(0, n))]
