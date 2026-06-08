"""Full-quality render: read source frames, run the chain, pipe to ffmpeg,
optionally datamosh, then mux audio back (with tempo for speed)."""
from __future__ import annotations
import os
import shutil
import tempfile
import logging
from dataclasses import dataclass

import cv2
import numpy as np

from . import media as M
from .context import BeatClock
from .chain import Chain
from .datamosh import datamosh

log = logging.getLogger(__name__)


@dataclass
class RenderOptions:
    speed: float = 1.0          # >1 faster, <1 slower (constant rate)
    datamosh: bool = False
    gpu: bool = True
    out_format: str = "mp4"     # mp4 | webm | gif
    height: int = 0             # 0 = source, else scale to this height


def _even(n: int) -> int:
    return n - (n % 2)


def render(input_path: str, out_path: str, chain: Chain, beats,
           opts: RenderOptions, progress=None, should_cancel=None, audio_env=None):
    """progress(frac 0..1, message). should_cancel() -> bool to abort."""
    def report(f, msg):
        if progress:
            progress(max(0.0, min(1.0, f)), msg)

    info = M.probe(input_path)
    fps = info.fps if info.fps > 0 else 30.0
    w, h = _even(info.width), _even(info.height)
    speed = max(0.05, float(opts.speed))

    # beats live on the source timeline; after a tempo change they compress.
    beats_out = [b / speed for b in (beats or [])]
    clock = BeatClock(beats_out, fps)
    env_use = audio_env.scaled(1.0 / speed) if audio_env is not None else None
    chain.reset()

    tmpdir = tempfile.mkdtemp(prefix="glitch_")
    try:
        raw_path = os.path.join(tmpdir, "raw." + ("avi" if opts.datamosh else "mp4"))
        audio_path = os.path.join(tmpdir, "audio.wav")
        has_audio = info.has_audio and M.extract_audio(input_path, audio_path)

        cap = cv2.VideoCapture(input_path)
        writer = M.open_frame_writer(raw_path, w, h, fps, opts.datamosh, opts.gpu)

        total_out = int(info.nframes / speed) if info.nframes else 0
        report(0.0, "Rendering frames…")
        out_idx = 0
        acc = 0.0
        cancelled = False
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame.shape[1] != w or frame.shape[0] != h:
                    frame = frame[:h, :w]
                acc += 1.0
                # constant-rate resample: emit while we've banked >= speed frames
                while acc >= speed:
                    acc -= speed
                    t = out_idx / fps
                    processed = chain.process_frame(frame, out_idx, t, fps, total_out,
                                                    clock, audio=env_use)
                    writer.stdin.write(np.ascontiguousarray(processed).tobytes())
                    out_idx += 1
                    if total_out:
                        report(0.05 + 0.8 * out_idx / total_out, f"Frame {out_idx}/{total_out}")
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                if cancelled:
                    break
        finally:
            cap.release()
            try:
                writer.stdin.close()
            except Exception:
                pass
            writer.wait()

        if cancelled:
            return False
        if writer.returncode not in (0, None):
            raise RuntimeError(
                f"ffmpeg encoder exited {writer.returncode} — the codec may be "
                "unavailable on this machine (e.g. h264_nvenc without an NVIDIA GPU).")

        video_for_mux = raw_path
        reencode = False
        if opts.datamosh:
            report(0.88, "Datamoshing (stripping I-frames)…")
            moshed = os.path.join(tmpdir, "moshed.avi")
            if datamosh(raw_path, moshed):
                video_for_mux = moshed
            reencode = True  # avi -> mp4 always needs a transcode

        report(0.93, "Muxing audio…")
        M.finalize(video_for_mux, audio_path if has_audio else None, out_path,
                   speed=speed, reencode=reencode, gpu=opts.gpu,
                   out_format=opts.out_format, height=opts.height)
        report(1.0, "Done")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def render_timeline(timeline, out_path, beats, opts: RenderOptions,
                    progress=None, should_cancel=None,
                    audio_buffer=None, audio_sr=22050, audio_src_path=None,
                    audio_env=None):
    """Render a multi-layer Timeline. Audio precedence:
    explicit `audio_buffer` (e.g. granular) > `audio_src_path` (a layer file)."""
    def report(f, msg):
        if progress:
            progress(max(0.0, min(1.0, f)), msg)

    fps = timeline.fps or 30.0
    w, h = _even(timeline.width or 640), _even(timeline.height or 360)
    speed = max(0.05, float(opts.speed))
    dur = timeline.duration()
    if dur <= 0:
        return False

    clock = BeatClock([b / speed for b in (beats or [])], fps)
    env_use = audio_env.scaled(1.0 / speed) if audio_env is not None else None
    for layer in timeline.layers:
        layer.chain.reset()

    tmpdir = tempfile.mkdtemp(prefix="glitch_tl_")
    try:
        raw_path = os.path.join(tmpdir, "raw." + ("avi" if opts.datamosh else "mp4"))
        writer = M.open_frame_writer(raw_path, w, h, fps, opts.datamosh, opts.gpu)

        total_out = max(1, int(dur / speed * fps))
        report(0.0, "Compositing…")
        cancelled = False
        try:
            for k in range(total_out):
                t_out = k / fps
                t_content = t_out * speed
                if t_content >= dur:
                    break
                frame = timeline.render_frame(t_content, w, h, clock, t_out=t_out, audio=env_use)
                writer.stdin.write(np.ascontiguousarray(frame).tobytes())
                report(0.05 + 0.8 * k / total_out, f"Frame {k}/{total_out}")
                if should_cancel and should_cancel():
                    cancelled = True
                    break
        finally:
            try:
                writer.stdin.close()
            except Exception:
                pass
            writer.wait()
        if cancelled:
            return False
        if writer.returncode not in (0, None):
            raise RuntimeError(
                f"ffmpeg encoder exited {writer.returncode} — the codec may be "
                "unavailable on this machine (e.g. h264_nvenc without an NVIDIA GPU).")

        video_for_mux, reencode = raw_path, False
        if opts.datamosh:
            report(0.88, "Datamoshing…")
            moshed = os.path.join(tmpdir, "moshed.avi")
            if datamosh(raw_path, moshed):
                video_for_mux = moshed
            reencode = True

        report(0.93, "Muxing audio…")
        fmt, ht = opts.out_format, opts.height
        audio_for_mux = None
        if audio_buffer is not None:
            try:
                import soundfile as sf
                audio_for_mux = os.path.join(tmpdir, "audio.wav")
                sf.write(audio_for_mux, audio_buffer, audio_sr)
                M.finalize(video_for_mux, audio_for_mux, out_path, speed=1.0,
                           reencode=reencode, gpu=opts.gpu, out_format=fmt, height=ht)
            except Exception as e:
                log.warning("granular audio mux failed, rendering silent: %s", e)
                audio_for_mux = None
        if audio_for_mux is None:
            wav = None
            if audio_src_path:
                wav = os.path.join(tmpdir, "src.wav")
                if not M.extract_audio(audio_src_path, wav):
                    wav = None
            M.finalize(video_for_mux, wav, out_path, speed=speed,
                       reencode=reencode, gpu=opts.gpu, out_format=fmt, height=ht)
        report(1.0, "Done")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
