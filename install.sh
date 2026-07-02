#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing required packages..."
sudo apt-get update -qq
sudo apt-get install -y mkvtoolnix ffmpeg python3 imagemagick

echo "==> Installing subtitle downloader..."
if command -v pip3 &>/dev/null; then
    pip3 install --user --break-system-packages subliminal 2>/dev/null ||
    pip3 install --user subliminal 2>/dev/null ||
    echo "  subliminal install skipped (try: pip3 install --user subliminal)"
else
    echo "  pip3 not found — installing via apt..."
    sudo apt-get install -y python3-pip python3-subliminal 2>/dev/null ||
    echo "  try: sudo apt install python3-pip && pip3 install --user subliminal"
fi

echo ""
echo "==> Setup complete. Run the tool:"
echo "    python3 video_tool.py"
echo ""
echo "Optional: install TinyMediaManager from https://www.tinymediamanager.org/download/"
echo "          then set tools.tmm_dir in config.json"
