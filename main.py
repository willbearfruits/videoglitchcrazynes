#!/usr/bin/env python3
"""CRAZY VIDEO GLITCH EDITOR — launcher.

GUI:  python main.py
CLI:  python main.py input.mp4 output.mp4 --preset brainfuck [--datamosh] [--speed 2]
"""
from __future__ import annotations
import sys


def run_cli(argv):
    import argparse
    from glitchcore import presets, beat, media
    from glitchcore.renderer import render, RenderOptions

    ap = argparse.ArgumentParser(description="Crazy video glitch editor (CLI)")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--preset", default="brainfuck", choices=list(presets.PRESETS))
    ap.add_argument("--datamosh", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args(argv)

    import os
    import tempfile
    info = media.probe(args.input)
    beats = []
    if info.has_audio:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav = tf.name
        try:
            if media.extract_audio(args.input, wav):
                beats = beat.detect_beats(wav)["beats"]
        finally:
            os.path.exists(wav) and os.remove(wav)
    if not beats:
        beats = beat.grid_beats(info.duration, 120.0)

    chain = presets.build(args.preset, seed=args.seed)
    dm = args.datamosh or args.preset in presets.WANTS_DATAMOSH
    print(f"Rendering '{args.preset}' (datamosh={dm}, speed={args.speed})…")
    render(args.input, args.output, chain, beats,
           RenderOptions(speed=args.speed, datamosh=dm),
           progress=lambda f, m: print(f"\r{f*100:5.1f}%  {m}", end="", flush=True))
    print(f"\nDone -> {args.output}")


def run_gui():
    from PySide6 import QtWidgets
    from gui.main_window import MainWindow
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Crazy Video Glitch Editor")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # 2+ positional, non-flag args => CLI batch render; otherwise launch GUI.
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(positional) >= 2:
        run_cli(sys.argv[1:])
    else:
        run_gui()
