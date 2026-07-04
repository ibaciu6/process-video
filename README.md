# process-video

Single-file Python tool for organizing local movie/TV libraries. Pure stdlib — no pip packages. External CLI tools auto-detected at runtime. Cross-platform (Linux/macOS/WSL).

## Features

### Movies
- Sort loose video files into `Year - Title/` folders
- TMDB/Cinemeta/OMDB title resolution and poster download
- Rename folders to `Year - Title` format, rename media files to match folder
- Non-destructive copy-to-Processed mode (leaves originals untouched)
- Handles existing files: skip/overwrite/keep both
- Diacritics stripped from subtitles before remux
- Live progress display for file copy and mkvmerge remux

### Series
- Parse episode filenames (`S01E01`, `1x01`, etc.) → `S01E01` format
- Flatten nested subfolders, rename files, clean junk

### Subtitles
- **Hash-based** search via OpenSubtitles.com REST API (exact match by file hash)
- Hash + name fallback for best coverage
- Name-based OS.com search with season/episode support
- `subliminal` CLI as alternative downloader
- Romanian subtitle sites: titrari.ro, subs.ro, subtitrari-noi.ro
- Encoding auto-detection (CP1250 / ISO-8859-2 → UTF-8 with BOM)
- Diacritic stripping (ăâîșț → aai st) — TV-safe output
- **Hash search runs before remux** (remuxing changes file hash)
- Diacritics stripped from all SRTs before remux phase

### MKV remux
- mkvmerge-based: strip embedded subs, mux sidecar `.srt` as RO track
- Live verbose output during remux
- Re-mux option when SRT stripped but MKV has embedded sub
- ffmpeg fallback when mkvmerge unavailable
- Keep only the best subtitle track (prefer RO, fallback EN)

### Config persistence
API keys, tool paths, and root folder persist to `config.json` — editable from the menu or directly. Environment vars override config at runtime.

## Setup

```bash
./install.sh   # detects apt/dnf/pacman/zypper/brew; no sudo needed for brew
cp config.example.json config.json
# edit config.json with API keys (→ Config → 4 in menu), or use menu
python3 video_tool.py
```

## Usage

### Interactive menu

```
  VIDEO ORGANIZER
  ─────────────────────────────────────────
  /path/to/videos                    mkvmerge=OK  TMM=NO

  [1]  Movies Pipeline       TMDB metadata, posters, subtitles, MKV remux → Processed/
  [2]  Series Pipeline       Flatten folders, subtitles, MKV remux
  [3]  Subtitles             Hash search, fix encoding, strip diacritics, remux
  [4]  Tools                 TMM, MKVToolNix
  [5]  Settings              Folder, API keys, dependencies
  [0]  Exit
```

Subtitles submenu:

```
  SUBTITLES
  ─────────────────────────────────────────
  [1]  Hash Search           OS.com exact match via video hash
  [2]  Download              Subliminal batch download
  [3]  Fix Encoding          Auto-detect cp1250/iso-8859-2 → UTF-8
  [4]  Strip Diacritics      ăâîșț → aai st
  [5]  Remux                 Strip embedded subs + mux sidecar SRT
  [6]  Full Pipeline         hash → fix → strip → remux
  [0]  Back
```

### CLI / scripting (AI-agent-ready)

```bash
# Hash search only
python3 video_tool.py --root /videos --action subs-hash --json

# Hash search + name fallback
python3 video_tool.py --root /videos --action subs-hash-fallback --json

# Full subs pipeline: download missing → fix → strip → remux
python3 video_tool.py --root /videos --action subs-pipeline --json

# Series pipeline
python3 video_tool.py --root /videos/Series --action series --dry-run

# Movies pipeline (all skip flags supported)
python3 video_tool.py --root /videos --action movies --skip-rename --skip-posters
```

Exit codes: `0` all ok, `1` partial failures, `2` all failed, `3` config error.

`--json` prints structured JSON summary to stdout after all human-readable output:

```json
{"ok": 5, "fail": 0, "total": 5, "action": "subs-fix", "elapsed": 1.23, "results": [...]}
```

### Modes

```bash
python3 video_tool.py --mode menu     # interactive menu (default)
python3 video_tool.py --mode series   # series pipeline, non-interactive
python3 video_tool.py --mode movies   # movies pipeline, non-interactive
```

## Configuration

Loaded from `config.json` next to the script → fallback `~/.config/process-video/config.json`. Never committed (gitignored).

Environment vars override config:

| Env var | Config key |
|---------|-----------|
| `PROCESS_MOVIES_TMDB_API_KEY` | `api_keys.tmdb` |
| `PROCESS_MOVIES_OMDB_API_KEY` | `api_keys.omdb` |
| `PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY` | `api_keys.opensubtitles_com_api_key` |
| `PROCESS_MOVIES_OPENSUBTITLES_COM_USER` | `api_keys.opensubtitles_com_user` |
| `PROCESS_MOVIES_OPENSUBTITLES_COM_PASSWORD` | `api_keys.opensubtitles_com_password` |
| `PROCESS_MOVIES_MKVMERGE_DIR` | `tools.mkvmerge_dir` |
| `PROCESS_MOVIES_TMM_DIR` | `tools.tmm_dir` |

API keys can also be set interactively via **Config → 4** (masked input, saved to config.json).

## External tools

| Tool | Package | Purpose |
|------|---------|---------|
| `mkvmerge` | `mkvtoolnix` | Remux MKV subtitle tracks |
| `ffprobe` | `ffmpeg` | Inspect track metadata |
| `subliminal` | `pip install subliminal` | Alt subtitle downloader |
| `tinyMediaManager` | [tinymediamanager.org](https://www.tinymediamanager.org/download/) | Metadata scraper GUI |
| `magick`/`convert` | `imagemagick` | Poster format conversion |
