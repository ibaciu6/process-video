#!/usr/bin/env bash
# WSL/Ubuntu launcher — video_tool.py (Movies & Series pipeline)
#
# Usage:
#   ./run_video_tool.sh                      interactive menu (default)
#   ./run_video_tool.sh /path/to/library     interactive menu on path
#   ./run_video_tool.sh --mode series --fetch-subs /path
#   ./run_video_tool.sh -i /path
#
# Env: PM_PYTHON PM_SKIP_DEPS PM_SKIP_APT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PM_PYTHON:-python3}"
PY_SCRIPT="$SCRIPT_DIR/video_tool.py"
ROOT=""
EXTRA_ARGS=()

die() { echo "ERROR: $*" >&2; exit 1; }
have_cmd() { command -v "$1" >/dev/null 2>&1; }

install_apt_packages() {
  local pkgs=("$@")
  ((${#pkgs[@]} > 0)) || return 0
  [[ "${PM_SKIP_APT:-}" != "1" ]] || die "Missing: ${pkgs[*]} (set PM_SKIP_APT=0 or apt install)"
  echo "Installing: ${pkgs[*]} (sudo may ask for password)..."
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -qq
  sudo apt-get install -y "${pkgs[@]}"
}

check_deps() {
  local missing=()
  have_cmd "$PY" || missing+=(python3)
  have_cmd mkvmerge || missing+=(mkvtoolnix)
  ((${#missing[@]} > 0)) && install_apt_packages "${missing[@]}"
  have_cmd "$PY" || die "$PY not found"
}

[[ -f "$PY_SCRIPT" ]] || die "video_tool.py not found in $SCRIPT_DIR"

if [[ "${PM_SKIP_DEPS:-}" != "1" ]]; then
  check_deps
fi

# Collect positional args (path first, then extra flags)
while (($# > 0)); do
  case "${1:-}" in
    -i|--menu|--interactive) ROOT="${2:-.}"; shift 2 || shift 1 || true ;;
    -h|--help) "$PY" "$PY_SCRIPT" --help; exit 0 ;;
    *)
      if [[ -z "$ROOT" ]] && ([[ -d "$1" ]] || [[ "$1" == "." ]] || [[ "$1" == ".." ]]); then
        ROOT="$(readlink -f "$1")"
      else
        EXTRA_ARGS+=("$1")
      fi
      shift
      ;;
  esac
done

# Default to interactive menu (skip superfluous series/movies/exit submenu)
# Only when no mode/action flag is passed by user
has_mode_flag() { local a; for a in "${EXTRA_ARGS[@]}"; do case "$a" in --mode|--check-deps|--install-deps|--help|-h|--interactive|-i|--menu) return 0;; esac; done; return 1; }
if ! has_mode_flag; then
  if [[ -n "$ROOT" ]]; then
    exec "$PY" "$PY_SCRIPT" --root "$ROOT" --interactive "${EXTRA_ARGS[@]}"
  else
    exec "$PY" "$PY_SCRIPT" --interactive "${EXTRA_ARGS[@]}"
  fi
fi
if [[ -n "$ROOT" ]]; then
  exec "$PY" "$PY_SCRIPT" --root "$ROOT" "${EXTRA_ARGS[@]}"
else
  exec "$PY" "$PY_SCRIPT" "${EXTRA_ARGS[@]}"
fi
