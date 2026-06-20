# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running

```bash
python3 video_tool.py          # interactive menu
python3 video_tool.py movies   # organize movies
python3 video_tool.py series   # organize series
python3 video_tool.py subs     # download subtitles
```

## Setup

```bash
./install.sh                   # installs mkvtoolnix, ffmpeg, subliminal
cp config.example.json config.json
# edit config.json with API keys and tool paths
```

## Configuration (`config.json`)

Loaded from the script directory or `~/.config/process-video/config.json`. **Never committed** (gitignored).

Env vars override config: `PROCESS_MOVIES_TMDB_API_KEY`, `PROCESS_MOVIES_OMDB_API_KEY`, `PROCESS_MOVIES_MKVMERGE_DIR`, `PROCESS_MOVIES_TMM_DIR`, etc.

## Architecture

Single-file Python script (`video_tool.py`, ~1600 lines). Pure stdlib — no pip packages. External CLI tools resolved via `shutil.which()` at runtime.

**Config loading** (`_load_config()`): reads `config.json` next to the script → falls back to `~/.config/process-video/config.json` → empty defaults.

**Key subsystems:**
- `movies` — detect/rename/organize movie folders; fetch TMDB/OMDB metadata
- `series` — parse episode filenames; rename to `S01E01` format; organize
- `subs` — download subtitles via OpenSubtitles.com REST API or `subliminal`; fix SRT encoding (Romanian CP1250/ISO-8859-2)
- `remux` — MKVToolNix wrapper to add/strip subtitle tracks
- `tmm` — launch TinyMediaManager for scraping

## External tools (all optional)
- **mkvmerge** (mkvtoolnix) — remuxing; auto-detected via `shutil.which`
- **ffprobe** (ffmpeg) — track inspection; auto-detected via `shutil.which`
- **TinyMediaManager** — metadata scraper GUI; set `tools.tmm_dir` in config
- **subliminal** — alternative subtitle downloader; auto-detected via `shutil.which`
