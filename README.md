# process-video

A single-file Python tool for organizing and enriching local movie and TV series libraries on Linux. No pip packages required — pure stdlib, with optional external CLI tools auto-detected at runtime.

## What it does

### Movies
- Detects loose movie files and folders with inconsistent naming
- Renames folders to the canonical `Title (Year)` format using TMDB/OMDB/Cinemeta lookup
- Resolves ambiguous or run-on titles against TMDB search
- Downloads poster art (JPEG) from TMDB, OMDB, iTunes, or Cinemeta
- Cleans up junk files: samples, `.nfo`, `.sfv`, leftover extras

### TV Series
- Parses episode filenames in any common format (`S01E01`, `1x01`, etc.)
- Renames files to clean `S01E01 Episode Title` format
- Strips quality tags, release group tokens, and other noise from filenames
- Organizes loose episode files into per-show folders

### Subtitles
- Downloads Romanian (or any language) subtitles via:
  - **OpenSubtitles.com** REST API (preferred)
  - **subliminal** CLI (fallback)
- Detects and fixes SRT encoding issues (Romanian CP1250 / ISO-8859-2 → UTF-8)
- Skips files that already have a subtitle track or sidecar `.srt`

### MKV remux
- Inspects MKV tracks using `ffprobe` / `mkvmerge`
- Strips unwanted subtitle tracks while keeping the Romanian one
- Muxes in an external `.srt` as a proper subtitle track
- Deduplicates duplicate English subtitle tracks

### TinyMediaManager
- Optionally launches TMM in GUI or CLI mode to scrape full metadata (artwork, NFO, cast, etc.)

---

## Setup

**1. Install dependencies**

```bash
./install.sh
```

Or manually:

```bash
sudo apt install mkvtoolnix ffmpeg python3
pip install subliminal   # optional
```

**2. Configure**

```bash
cp config.example.json config.json
```

Edit `config.json` — it is gitignored and never committed.

| Key | Where to get it |
|-----|----------------|
| `api_keys.tmdb` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| `api_keys.omdb` | [omdbapi.com/apikey](http://www.omdbapi.com/apikey.aspx) |
| `api_keys.opensubtitles_com_api_key` | [opensubtitles.com/en/consumers](https://www.opensubtitles.com/en/consumers) |
| `api_keys.opensubtitles_com_user/password` | Your OpenSubtitles.com login |
| `api_keys.opensubtitles_org_user/password` | Your OpenSubtitles.org login |
| `tools.tmm_dir` | Path to TinyMediaManager install (optional) |
| `defaults.root_dir` | Default media root folder |

**3. Run**

```bash
python3 video_tool.py
```

Launches an interactive menu. Direct subcommands also work:

```bash
python3 video_tool.py movies    # organize movie folders
python3 video_tool.py series    # organize series folders
python3 video_tool.py subs      # download subtitles
```

---

## Interactive menu

```
  1) Run full pipeline      — all steps in sequence
  2) Rename folders         — normalize movie folder names
  3) Rename files           — normalize episode filenames
  4) Clean junk             — remove samples, extras, metadata leftovers
  5) Download subtitles     — fetch missing .srt files
  6) Fix SRT encoding       — convert CP1250/ISO-8859-2 → UTF-8
  7) Remux MKV              — add/strip subtitle tracks
  8) Launch TMM             — open TinyMediaManager
  9) Check dependencies     — report which tools are available
  10) Change folder         — set the working media root
```

---

## Config file location

The tool looks for `config.json` next to the script first, then falls back to `~/.config/process-video/config.json`.

Environment variable overrides (take precedence over config file):

| Env var | Config key |
|---------|-----------|
| `PROCESS_MOVIES_TMDB_API_KEY` | `api_keys.tmdb` |
| `PROCESS_MOVIES_OMDB_API_KEY` | `api_keys.omdb` |
| `PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY` | `api_keys.opensubtitles_com_api_key` |
| `PROCESS_MOVIES_MKVMERGE_DIR` | `tools.mkvmerge_dir` |
| `PROCESS_MOVIES_TMM_DIR` | `tools.tmm_dir` |

---

## External tools

All tools are optional and auto-detected via `shutil.which()` at startup:

| Tool | Package | Purpose |
|------|---------|---------|
| `mkvmerge` | `mkvtoolnix` | Remux MKV subtitle tracks |
| `ffprobe` | `ffmpeg` | Inspect MKV track metadata |
| `subliminal` | `pip install subliminal` | Fallback subtitle downloader |
| `tinyMediaManager` | [tinymediamanager.org](https://www.tinymediamanager.org/download/) | Full metadata scraper GUI |
