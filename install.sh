#!/usr/bin/env bash
set -euo pipefail

# Detect OS / package manager
UNAME=$(uname -s)
if [ "$UNAME" = "Darwin" ]; then
    PKG="brew"
    INSTALL="brew install"
    UPDATE="brew update"
    PY_PACKAGES="mkvtoolnix ffmpeg imagemagick"
elif command -v apt-get &>/dev/null; then
    PKG="apt"
    INSTALL="sudo apt-get install -y"
    UPDATE="sudo apt-get update -qq"
    PY_PACKAGES="mkvtoolnix ffmpeg imagemagick unrar"
elif command -v dnf &>/dev/null; then
    PKG="dnf"
    INSTALL="sudo dnf install -y"
    UPDATE="sudo dnf check-update || true"
    PY_PACKAGES="mkvtoolnix ffmpeg ImageMagick unar"
elif command -v pacman &>/dev/null; then
    PKG="pacman"
    INSTALL="sudo pacman -S --noconfirm"
    UPDATE="sudo pacman -Sy"
    PY_PACKAGES="mkvtoolnix-cli ffmpeg imagemagick unrar"
elif command -v zypper &>/dev/null; then
    PKG="zypper"
    INSTALL="sudo zypper install -y"
    UPDATE="sudo zypper refresh"
    PY_PACKAGES="mkvtoolnix ffmpeg ImageMagick unrar"
else
    echo "ERROR: No supported package manager found (apt/dnf/pacman/zypper/brew)."
    echo "Please install manually: mkvtoolnix, ffmpeg, python3, imagemagick"
    exit 1
fi

echo "==> Detected package manager: $PKG"
echo "==> Installing required packages..."
$UPDATE
$INSTALL $PY_PACKAGES

echo "==> Installing subtitle downloader..."
if command -v pip3 &>/dev/null; then
    pip3 install --user --break-system-packages subliminal 2>/dev/null ||
    pip3 install --user subliminal 2>/dev/null ||
    echo "  subliminal install skipped (try: pip3 install --user subliminal)"
else
    echo "  pip3 not found — please install python3-pip and run:"
    echo "    pip3 install --user subliminal"
fi

echo ""
echo "==> Setup complete. Run the tool:"
echo "    python3 video_tool.py"
echo ""
echo "Optional: install TinyMediaManager from https://www.tinymediamanager.org/download/"
echo "          then set tools.tmm_dir in config.json"
