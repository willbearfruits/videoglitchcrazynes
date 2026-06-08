"""Motion engine — dense optical flow + flow warping, plus depth estimation.

Optical flow uses OpenCV's DIS (fast, no model, no download). Depth uses a
luminance pseudo-depth by default and optionally a real MiDaS model (torch) when
`enable_midas()` is called — kept off the hot path so previews never hang on a
one-time model download.
"""
from __future__ import annotations
import numpy as np
import cv2

_dis = None
_midas = None
_midas_tf = None
_midas_state = "off"   # off | ok | failed


def flow(prev_gray, cur_gray):
    """Dense optical flow (HxWx2 float32) from prev->cur grayscale frames."""
    global _dis
    if _dis is None:
        _dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    return _dis.calc(prev_gray, cur_gray, None)


def warp_by_flow(img, fl, scale=1.0):
    """Push `img` pixels along the flow field by `scale`."""
    h, w = img.shape[:2]
    gx = np.arange(w, dtype=np.float32)[None, :]
    gy = np.arange(h, dtype=np.float32)[:, None]
    map_x = gx + fl[..., 0] * scale
    map_y = gy + fl[..., 1] * scale
    return cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT)


def gray(frame):
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


# -- depth ------------------------------------------------------------------
def enable_midas():
    """Try to load MiDaS (small) once. Returns True if available."""
    global _midas, _midas_tf, _midas_state
    if _midas_state == "ok":
        return True
    if _midas_state == "failed":
        return False
    try:
        import torch
        _midas = torch.hub.load("intel-isl/MiDaS", "MiDaS_small")
        tfs = torch.hub.load("intel-isl/MiDaS", "transforms")
        _midas_tf = tfs.small_transform
        _midas.eval()
        if torch.cuda.is_available():
            _midas = _midas.to("cuda")
        _midas_state = "ok"
        return True
    except Exception as e:  # pragma: no cover
        print(f"[motion] MiDaS unavailable, using luminance depth: {e}")
        _midas_state = "failed"
        return False


def depth(frame):
    """Return a 0..1 depth map (near=1). MiDaS if enabled, else luminance."""
    if _midas_state == "ok":
        try:
            import torch
            dev = "cuda" if next(_midas.parameters()).is_cuda else "cpu"
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            inp = _midas_tf(rgb).to(dev)
            with torch.no_grad():
                pred = _midas(inp)
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=frame.shape[:2],
                    mode="bicubic", align_corners=False).squeeze()
            d = pred.detach().cpu().numpy().astype(np.float32)
            d -= d.min()
            d /= (d.max() + 1e-6)
            return d
        except Exception:
            pass
    # luminance pseudo-depth (blurred brightness) — instant, always works
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 7)
    g -= g.min()
    g /= (g.max() + 1e-6)
    return g
