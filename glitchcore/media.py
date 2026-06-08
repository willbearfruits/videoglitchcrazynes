"""Media helpers: probe, audio extract, and ffmpeg frame-pipe encode/mux."""
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass


@dataclass
class MediaInfo:
    width: int
    height: int
    fps: float
    nframes: int
    duration: float
    has_audio: bool


def probe(path: str) -> MediaInfo:
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", path]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    if v is None:
        raise ValueError("No video stream found")
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    w, h = int(v["width"]), int(v["height"])
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    nframes = int(v.get("nb_frames", 0) or 0)
    if nframes <= 0 and duration > 0:
        nframes = int(round(duration * fps))
    return MediaInfo(w, h, fps, nframes, duration, has_audio)


def extract_audio(path: str, out_wav: str) -> bool:
    """Extract audio to a wav for beat analysis. False if no audio."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "22050", out_wav],
            capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _atempo_chain(speed: float) -> str:
    """atempo only accepts 0.5..2.0; compose multiple to reach extreme speeds."""
    if abs(speed - 1.0) < 1e-3:
        return ""
    factors = []
    s = speed
    while s > 2.0:
        factors.append(2.0); s /= 2.0
    while s < 0.5:
        factors.append(0.5); s /= 0.5
    factors.append(s)
    return ",".join(f"atempo={f:.4f}" for f in factors)


def open_frame_writer(out_path: str, w: int, h: int, fps: float,
                      datamosh: bool, gpu: bool = True):
    """Open an ffmpeg process accepting raw bgr24 frames on stdin.

    datamosh -> mpeg4 AVI with one big GOP and no B-frames (mosh-friendly).
    otherwise -> h264 (nvenc if available) mp4.
    """
    base = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-", "-an"]
    if datamosh:
        # recurring I-frames (~1/sec) give the P-frame bloom something to strip;
        # no B-frames keeps the chunk stream simple for the byte-level mosh.
        gop = max(2, int(round(fps)))
        cmd = base + ["-c:v", "mpeg4", "-q:v", "5", "-g", str(gop),
                      "-bf", "0", "-sc_threshold", "1000000000",
                      "-mbd", "rd", out_path]
    elif gpu:
        cmd = base + ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21",
                      "-pix_fmt", "yuv420p", out_path]
    else:
        cmd = base + ["-c:v", "libx264", "-crf", "20",
                      "-pix_fmt", "yuv420p", out_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def finalize(video_in: str, audio_src: str | None, out_path: str,
             speed: float = 1.0, reencode: bool = False, gpu: bool = True,
             out_format: str = "mp4", height: int = 0):
    """Mux audio + emit the final file in the chosen format/resolution.

    out_format: mp4 | webm | gif (gif is silent).
    height: 0 = source, else scale to this height (even, keep aspect).
    reencode=True transcodes the video (needed after a datamosh AVI pass).
    """
    if out_format == "gif":
        fps = 12
        scale = (f"scale=-2:{int(height)}:flags=lanczos" if height
                 else "scale=iw:-1:flags=lanczos")
        fc = (f"[0:v] fps={fps},{scale},split [a][b];"
              f"[a] palettegen=stats_mode=diff [p];"
              f"[b][p] paletteuse=dither=bayer")
        subprocess.run(["ffmpeg", "-y", "-i", video_in, "-filter_complex", fc,
                        "-an", out_path], capture_output=True, check=True)
        return

    cmd = ["ffmpeg", "-y", "-i", video_in]
    has_audio = bool(audio_src)
    if has_audio:
        cmd += ["-i", audio_src]
    cmd += ["-map", "0:v:0"]
    if has_audio:
        cmd += ["-map", "1:a:0"]
        atempo = _atempo_chain(speed)
        if atempo:
            cmd += ["-filter:a", atempo]
    scaling = bool(height)
    if scaling:
        cmd += ["-vf", f"scale=-2:{int(height)}"]

    if out_format == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32", "-pix_fmt", "yuv420p"]
        if has_audio:
            cmd += ["-c:a", "libopus", "-b:a", "160k"]
    else:  # mp4
        if reencode or scaling:
            if gpu:
                cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21"]
            else:
                cmd += ["-c:v", "libx264", "-crf", "20"]
            cmd += ["-pix_fmt", "yuv420p"]
        else:
            cmd += ["-c:v", "copy"]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-shortest", out_path]
    subprocess.run(cmd, capture_output=True, check=True)
