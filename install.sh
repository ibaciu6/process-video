#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing required packages..."
sudo apt-get update -qq
sudo apt-get install -y mkvtoolnix ffmpeg python3

echo "==> Installing optional subtitle downloader..."
if command -v pip3 &>/dev/null; then
    pip3 install --user subliminal
else
    echo "  pip3 not found — skipping subliminal (optional)"
fi

echo ""
echo "==> Setup complete. Run the tool:"
echo "    python3 video_tool.py"
echo ""
echo "Optional: install TinyMediaManager from https://www.tinymediamanager.org/download/"
echo "          then set tools.tmm_dir in config.json"
