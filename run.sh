#!/usr/bin/env bash
# Launch the Crazy Video Glitch Editor GUI (or pass args for CLI batch render).
cd "$(dirname "$0")"
exec python3 main.py "$@"
