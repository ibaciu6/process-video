#!/usr/bin/env python3
"""Video organizer — Movies & Series. Single entry point, interactive menu."""

import argparse
import codecs
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

# ===========================================================================
# Config loader — reads config.json next to this script or at
# ~/.config/process-video/config.json.  Never hard-code credentials here.
# Copy config.example.json → config.json and fill in your values.
# ===========================================================================

def _load_config() -> dict:
    candidates = [
        Path(__file__).parent / "config.json",
        Path.home() / ".config" / "process-video" / "config.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}

def _get_config_path() -> Path:
    p = Path(__file__).parent / "config.json"
    if p.exists():
        return p
    p2 = Path.home() / ".config" / "process-video" / "config.json"
    if p2.exists():
        return p2
    return p

def _save_config() -> None:
    p = _get_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_CFG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def _set_api_key(key_name: str, display_name: str) -> None:
    cur = _CFG_KEYS.get(key_name, "")
    masked = cur[:4] + "****" if len(cur) > 4 else "(empty)"
    raw = input(f"  {display_name} [{masked}]: ").strip().strip("\"'")
    if raw:
        _CFG.setdefault("api_keys", {})[key_name] = raw
        _save_config()
        _bullet(f"  {display_name} saved")

_CFG = _load_config()
_CFG_KEYS  = _CFG.get("api_keys", {})
_CFG_TOOLS = _CFG.get("tools", {})
_CFG_DEFS  = _CFG.get("defaults", {})

# ===========================================================================
# Constants
# ===========================================================================

# Tool paths — override in config.json or via env vars
TOOL_DIR_MKVMERGE = _CFG_TOOLS.get("mkvmerge_dir", "")
TOOL_DIR_TMM      = _CFG_TOOLS.get("tmm_dir", "")

# API keys — set in config.json; env vars take precedence
_DEFAULT_TMDB_API_KEY              = _CFG_KEYS.get("tmdb", "")
_DEFAULT_OMDB_API_KEY              = _CFG_KEYS.get("omdb", "")
_DEFAULT_OPENSUBTITLES_COM_API_KEY = _CFG_KEYS.get("opensubtitles_com_api_key", "")
_DEFAULT_OPENSUBTITLES_COM_LOGIN_USER     = _CFG_KEYS.get("opensubtitles_com_user", "")
_DEFAULT_OPENSUBTITLES_COM_LOGIN_PASSWORD = _CFG_KEYS.get("opensubtitles_com_password", "")
_DEFAULT_OPENSUBTITLES_ORG_USER     = _CFG_KEYS.get("opensubtitles_org_user", "")
_DEFAULT_OPENSUBTITLES_ORG_PASSWORD = _CFG_KEYS.get("opensubtitles_org_password", "")

OPENSUBTITLES_COM_API_BASE = "https://api.opensubtitles.com/api/v1"
OPENSUBTITLES_COM_USER_AGENT = "ibaxsub v1.0"

# File extensions
MOVIE_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".m4v"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".mov", ".avi"}
SUBTITLE_EXTENSIONS = {".srt", ".sub", ".idx", ".ass", ".ssa"}
MEDIA_EXTENSIONS = MOVIE_EXTENSIONS | SUBTITLE_EXTENSIONS
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
JUNK_EXTENSIONS = {".sfv", ".tmp", ".ini", ".png", ".nfo", ".jpg", ".idx", ".txt", ".diz"}
JUNK_DIRS = {"subs", "sample"}
JUNK_STEMS = {"clearlogo", "fanart", "movieset-poster", "movieset-fanart"}
OWN_EXTENSIONS = {".py", ".sh"}

# Encoding detection
CODEPAGE_CANDIDATES = ["cp1250", "iso8859-2", "iso8859-16", "cp852", "cp1252"]

# Regex patterns - movies
RE_MOVIE_FOLDER = re.compile(r"^(.*) \((\d{4})\)$")
RE_YEAR_NAME_FOLDER = re.compile(r"^(\d{4}) - (.+)$")
RE_LOOSE_TITLE_YEAR = re.compile(r"^(.+?)\s*\((\d{4})\)")
_RUNON_TRAIL_WORDS = frozenset({
    "again", "back", "bites", "boys", "brother", "city", "club", "daughter",
    "day", "days", "express", "father", "fire", "forever", "game", "games",
    "girl", "high", "home", "hood", "house", "killer", "land", "life", "love",
    "movie", "movies", "night", "park", "party", "pie", "returns", "reunion",
    "rises", "sister", "story", "stories", "strikes", "town", "ultra", "wars",
    "wedding", "world", "zone",
})
_TMDB_JUNK_TITLE_HINTS = (
    "making the ", "making of ", "behind the scenes", "wages of ",
    "the making of", "documentary", "featurette", "b-roll", "b roll",
    "interviews with", "soundtrack:", "music from and inspired",
    "chronicles: ",
)
RE_LOOSE_JUNK_TOKEN = re.compile(
    r"\b(?:"
    r"2160p|1080p|720p|480p|x264|x265|h264|h265|hevc|avc|"
    r"bluray|blu[- ]?ray|uhd|brrip|bdrip|hdrip|dvdrip|"
    r"webrip|web|web[- ]?dl|webdl|hdtv|"
    r"remux|repack|rerip|proper|"
    r"hdr10|hdr|sdr|dv|dovi|dolbyvision|"
    r"ddp|dd\+|eac3|aac|ac3|dts|truehd|flac|lpcm|atmos|"
    r"dual|multi|complete|telesync|ts|cam|hc|"
    r"amzn|nf|dsnp|hmax|pcok|yts(?:\.ag)?"
    r")\b", re.IGNORECASE)
RE_BAD_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Regex patterns - series episodes
RE_EPISODE = re.compile(
    r"^(.+?)" r"[.\s]*[Ss](\d+)[.\s]*[Ee](\d+)" r"(?:[.\s]+(.+?))?\s*$")
RE_JUNK_TITLE = re.compile(r"\s+\d{3,4}p.*$", re.IGNORECASE)
RE_TRAILING_SEP = re.compile(r"\s*[-–]\s*$")
RE_TRAILING_YEAR = re.compile(r"\s+\d{4}$")
RE_MULTI_SPACE = re.compile(r"\s{2,}")
RE_QUALITY_TOKENS = re.compile(
    r"\b(?:"
    r"2160p|1080p|720p|480p|x264|x265|h264|h265|hevc|avc|"
    r"bluray|blu[- ]?ray|uhd|brrip|bdrip|hdrip|dvdrip|"
    r"webrip|web|web[- ]?dl|webdl|hdtv|"
    r"remux|repack|rerip|proper|"
    r"hdr10|hdr|sdr|dv|dovi|dolbyvision|"
    r"ddp|dd[+]|eac3|aac|ac3|dts|truehd|flac|lpcm|atmos|"
    r"dual|multi|complete|"
    r"amzn|nf|dsnp|hmax|pcok|yts(?:\.ag)?"
    r")\b", re.IGNORECASE)

# Subtitle cleaning
DIACRITIC_MAP = {
    "\u0103": "a", "\u0102": "A", "\u00E2": "a", "\u00C2": "A",
    "\u00EE": "i", "\u00CE": "I", "\u0219": "s", "\u0218": "S",
    "\u021B": "t", "\u021A": "T", "\u015F": "s", "\u015E": "S",
    "\u0163": "t", "\u0162": "T", "\u00BA": "s", "\u00AA": "S",
    "\u00FE": "t", "\u00DE": "T", "\u00E3": "a", "\u00C3": "A",
    "\u00B3": "s", "\u00B0": "o",
    "\u00E0": "a", "\u00C0": "A", "\u00E1": "a", "\u00C1": "A",
    "\u00E4": "a", "\u00C4": "A", "\u00E5": "a", "\u00C5": "A",
    "\u00E6": "ae", "\u00C6": "AE", "\u00E7": "c", "\u00C7": "C",
    "\u00E8": "e", "\u00C8": "E", "\u00E9": "e", "\u00C9": "E",
    "\u00EA": "e", "\u00CA": "E", "\u00EB": "e", "\u00CB": "E",
    "\u00EC": "i", "\u00CC": "I", "\u00ED": "i", "\u00CD": "I",
    "\u00EF": "i", "\u00CF": "I", "\u00F0": "d", "\u00D0": "D",
    "\u00F1": "n", "\u00D1": "N", "\u00F2": "o", "\u00D2": "O",
    "\u00F3": "o", "\u00D3": "O", "\u00F4": "o", "\u00D4": "O",
    "\u00F5": "o", "\u00D5": "O", "\u00F6": "o", "\u00D6": "O",
    "\u00F8": "o", "\u00D8": "O", "\u00F9": "u", "\u00D9": "U",
    "\u00FA": "u", "\u00DA": "U", "\u00FB": "u", "\u00DB": "U",
    "\u00FC": "u", "\u00DC": "U", "\u00FD": "y", "\u00DD": "Y",
    "\u00FF": "y",
    "\u0101": "a", "\u0100": "A", "\u0105": "a", "\u0104": "A",
    "\u0107": "c", "\u0106": "C", "\u010D": "c", "\u010C": "C",
    "\u010F": "d", "\u010E": "D", "\u0111": "d", "\u0110": "D",
    "\u0113": "e", "\u0112": "E", "\u0117": "e", "\u0116": "E",
    "\u0119": "e", "\u0118": "E", "\u011B": "e", "\u011A": "E",
    "\u011F": "g", "\u011E": "G", "\u0123": "g", "\u0122": "G",
    "\u012B": "i", "\u012A": "I", "\u012F": "i", "\u012E": "I",
    "\u0131": "i", "\u0130": "I", "\u0137": "k", "\u0136": "K",
    "\u013A": "l", "\u0139": "L", "\u013C": "l", "\u013B": "L",
    "\u013E": "l", "\u013D": "L", "\u0142": "l", "\u0141": "L",
    "\u0144": "n", "\u0143": "N", "\u0146": "n", "\u0145": "N",
    "\u0148": "n", "\u0147": "N", "\u0151": "o", "\u0150": "O",
    "\u0155": "r", "\u0154": "R", "\u0159": "r", "\u0158": "R",
    "\u015B": "s", "\u015A": "S", "\u0161": "s", "\u0160": "S",
    "\u0165": "t", "\u0164": "T", "\u016B": "u", "\u016A": "U",
    "\u016F": "u", "\u016E": "U", "\u0171": "u", "\u0170": "U",
    "\u0173": "u", "\u0172": "U", "\u017A": "z", "\u0179": "Z",
    "\u017C": "z", "\u017B": "Z", "\u017E": "z", "\u017D": "Z",
    "\u00DF": "ss",
}
_DIAC_TRANS = str.maketrans(DIACRITIC_MAP)
PUNCT_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201A": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"',
    "\u00AB": '"', "\u00BB": '"', "\u2039": "'", "\u203A": "'",
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2026": "...", "\u00A0": " ", "\u202F": " ",
    "\u2009": " ", "\u200A": " ",
}
_PUNCT_TRANS = str.maketrans(PUNCT_MAP)
INVISIBLE_CHARS = (
    "\u200B\u200C\u200D\uFEFF\u2060\u00AD\u200E\u200F\u202A\u202B\u202C"
    "\u202D\u202E\u2066\u2067\u2068\u2069\u0000\uFFFD"
)
RE_INVISIBLE = re.compile("[" + re.escape(INVISIBLE_CHARS) + "]")
RE_GARBAGE = re.compile("[\u0080-\u009F\uFFFD]")
RE_MOJIBAKE = re.compile(r"[ºþÃãÞª]")
RE_RO_DIACRITICS = re.compile(r"[ăâîșțĂÂÎȘȚşţŞŢ]")
RE_ASS_NEWLINE = re.compile(r"\\[Nn]")
RE_ASS_HARDSPACE = re.compile(r"\\h")
RE_ASS_DRAWING = re.compile(r"\{\\p[1-9][^}]*\}.*?(?:\{\\p0\}|$)", re.DOTALL)
RE_ASS_OVERRIDES = re.compile(r"\{[^}]*\}")
RE_HTML_TAGS = re.compile(r"<[^>]+>")
RE_LEFTOVER_BRACES = re.compile(r"[{}]")
RE_LEFTOVER_ANGLES = re.compile(r"<[^>]*>")
RE_MUSIC_NOTES = re.compile(r"[\u266A-\u266F\u2669]+")
RE_SRT_MULTI_SPACE = re.compile(r"[^\S\r\n]{2,}")
RE_EMPTY_CUE = re.compile(
    r"\d+\s*\r?\n\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}[^\r\n]*\r?\n(?:\s*\r?\n)+",
    re.MULTILINE)
RE_EXCESS_BLANKS = re.compile(r"(\r?\n){3,}")

# Console
_SECTION_WIDTH = 62
_SECTION_RULE = "=" * _SECTION_WIDTH

# Verbose logging
_VERBOSE = True

def _v(msg: str) -> None:
    if _VERBOSE:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        print(f"  [{ts}] {msg}")

def _vv(msg: str) -> None:
    if _VERBOSE:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        print(f"  [{ts}]   {msg}")

def _log_cmd(cmd: list[str]) -> None:
    if _VERBOSE:
        _vv(f"CMD: {' '.join(str(c) for c in cmd)[:300]}")

def _timer_start() -> float:
    return datetime.now().timestamp()

def _timer_elapsed_raw(start: float) -> float:
    return datetime.now().timestamp() - start

def _timer_elapsed(start: float, label: str) -> None:
    if _VERBOSE:
        elapsed = _timer_elapsed_raw(start)
        _vv(f"[TIMING] {label}: {elapsed:.2f}s")

# Ffprobe language for muxed tracks
MKV_SIDECAR_SRT_LANGUAGE = "ro"

_DEFAULT_ROOT = _CFG_DEFS.get("root_dir", "")
TMM_EXE_NAMES = ("tinyMediaManager", "TinyMediaManager", "tmm")
TMM_CMD_EXE_NAMES = ("tinyMediaManagerCMD", "tinyMediaManager")

# ===========================================================================
# Console helpers
# ===========================================================================

def _heading(title: str) -> None:
    print(f"\n{_SECTION_RULE}\n  {title}\n{_SECTION_RULE}")

def _bullet(msg: str) -> None:
    print(f"  \xB7 {msg}")

def _indent(msg: str) -> None:
    print(f"    {msg}")

def set_window_title(title: str) -> None:
    print(f"\033]0;{title}\007", end="", flush=True)

# ===========================================================================
# Path / tool resolution
# ===========================================================================

def sanitize_path(raw: str) -> Path:
    raw = raw.strip().strip('"').rstrip("/\\").strip()
    return Path(raw).resolve()

def _coalesce_tool_dir(cli: str, env_key: str, builtin: str) -> str:
    c = (cli or "").strip()
    return c.strip().strip('"') if c else (os.environ.get(env_key) or "").strip() or builtin

def resolve_mkvmerge_exe(mkvmerge_dir_cli: str = "") -> str | None:
    w = shutil.which("mkvmerge")
    if w: return w
    base = _coalesce_tool_dir(mkvmerge_dir_cli, "PROCESS_MOVIES_MKVMERGE_DIR", TOOL_DIR_MKVMERGE)
    if base:
        c = Path(base) / "mkvmerge"
        if c.is_file() and os.access(c, os.X_OK): return str(c)
    return None

def resolve_tmm_exe(tmm_dir_cli: str = "") -> Path | None:
    w = shutil.which("tinyMediaManager") or shutil.which("tmm")
    if w: return Path(w)
    base = _coalesce_tool_dir(tmm_dir_cli, "PROCESS_MOVIES_TMM_DIR", TOOL_DIR_TMM)
    if base:
        for n in TMM_EXE_NAMES:
            c = Path(base) / n
            if c.is_file() and os.access(c, os.X_OK): return c
    return None

def resolve_tmm_cmd_exe(tmm_dir_cli: str = "") -> Path | None:
    w = shutil.which("tinyMediaManagerCMD")
    if w: return Path(w)
    base = _coalesce_tool_dir(tmm_dir_cli, "PROCESS_MOVIES_TMM_DIR", TOOL_DIR_TMM)
    if base:
        for n in TMM_CMD_EXE_NAMES:
            c = Path(base) / n
            if c.is_file() and os.access(c, os.X_OK): return c
    return None

def resolve_subliminal_exe(cli_path: str = "") -> str | None:
    for raw in ((cli_path or "").strip(), (os.environ.get("PROCESS_MOVIES_SUBLIMINAL") or "").strip()):
        if raw:
            p = Path(raw.strip('"'))
            if p.is_file(): return str(p)
    return shutil.which("subliminal")

def is_own_file(fp: Path, root: Path) -> bool:
    return fp.parent == root and fp.suffix.lower() in OWN_EXTENSIONS

# ===========================================================================
# MKV helpers
# ===========================================================================

def _mkvmerge_identify(path: Path, *, exe: str) -> dict:
    _v(f"Identify MKV: {path.name}")
    _log_cmd([exe, "-J", str(path)])
    proc = subprocess.run([exe, "-J", str(path)], capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip())
    data = json.loads(proc.stdout)
    if data.get("errors"): raise RuntimeError("; ".join(str(e) for e in data["errors"]))
    return data

def _mkv_track_language(props: dict) -> str:
    ietf = props.get("language_ietf")
    if isinstance(ietf, str) and ietf.strip(): return ietf.strip()
    lang = props.get("language")
    return lang.strip() if isinstance(lang, str) and lang.strip() else ""

def _mkv_is_english_audio(props: dict) -> bool:
    c = _mkv_track_language(props).strip().lower().replace("_", "-")
    if not c: return False
    if c in ("eng", "en", "english"): return True
    if c.startswith("en-"): return True
    if len(c) >= 2 and c[:2] == "en": return True
    name = props.get("track_name")
    if isinstance(name, str) and "english" in name.lower(): return True
    return False

def _mkv_is_romanian_subtitle(props: dict) -> bool:
    c = _mkv_track_language(props).strip().lower().replace("_", "-")
    if c in ("ro", "rum", "ron"): return True
    if c.startswith("ro-") or c.startswith("ron-"): return True
    if len(c) >= 2 and c[:2] == "ro": return True
    name = props.get("track_name")
    if isinstance(name, str) and "romanian" in name.lower(): return True
    return False

def _has_romanian_subtitle(video_path: Path) -> bool:
    _vv(f"ffprobe RO check: {video_path.name}")
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(video_path)],
            capture_output=True, timeout=30)
        if proc.returncode != 0:
            _vv(f"  ffprobe failed rc={proc.returncode}")
            return False
        for s in json.loads(proc.stdout).get("streams", []):
            if s.get("codec_type") != "subtitle": continue
            lang = (s.get("tags") or {}).get("language", "").lower()
            if lang in ("ro", "rum", "ron"):
                _vv(f"  found RO subtitle track")
                return True
        _vv(f"  no RO subtitle track")
        return False
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired) as e:
        _vv(f"  ffprobe error: {e}")
        return False

def _has_romanian_subtitle_sidecar(video_path: Path) -> bool:
    """Check if a sidecar .srt file exists with Romanian content.

    Returns True if there's a sidecar .srt file or embedded Romanian subtitles.
    """
    # Check for sidecar .srt file
    srt_path = video_path.with_suffix(".srt")
    if srt_path.is_file():
        # For now, assume sidecar files are Romanian
        # Could be enhanced with actual content checking
        return True

    # Also check for embedded Romanian subtitles
    if _has_romanian_subtitle(video_path):
        return True

    return False

def _download_from_romanian_subtitles_better(query: str, dest: Path, *, lang: str = "romanian", tmdb_api_key: str = "", tmdb_id: int | None = None) -> bool:
    """Download subtitles from Romanian subtitle sites.

    Fallback chain (1→2→3):
    1. titrari.ro — via IMDB ID lookup (PHPSESSID cookie, raw/ZIP/RAR)
    2. subs.ro — AJAX search with antispam token, ZIP download
    3. subtitrari-noi.ro — detail page ZIP (currently dead)

    Returns True on successful download.
    """
    _v(f"Romanian subtitle sites: query={query} tmdb_id={tmdb_id}")
    import urllib.request
    import urllib.parse
    import json
    import re
    import tempfile
    import zipfile
    import io
    import http.cookiejar

    _ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    # 1. titrari.ro via IMDB ID (needs PHPSESSID cookie)
    if tmdb_api_key and tmdb_id:
        _vv("  trying titrari.ro via IMDB ID...")
        try:
            url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={tmdb_api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": _ua})
            with urllib.request.urlopen(req, timeout=15) as resp:
                md = json.loads(resp.read())
            imdb_id = md.get("imdb_id", "")
            imdb_num = imdb_id.replace("tt", "") if imdb_id else ""
            _vv(f"  IMDB ID: {imdb_id}")
            if imdb_num:
                cj = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                opener.addheaders = [("User-Agent", _ua)]
                opener.open(urllib.request.Request("https://titrari.ro/"), timeout=10).close()
                detail_url = f"https://titrari.ro/index.php?page=cautamainaltaparte&z8=1&z5={imdb_num}"
                _vv(f"  fetching detail page: {detail_url}")
                req2 = urllib.request.Request(detail_url, headers={"Referer": "https://titrari.ro/"})
                with opener.open(req2, timeout=30) as resp2:
                    html = resp2.read().decode("utf-8", errors="replace")
                dl_ids = re.findall(r'href=get\.php\?id=(\d+)', html)
                _vv(f"  found {len(dl_ids)} download IDs")
                for dl_id in dl_ids[:5]:
                    _vv(f"    trying dl_id={dl_id}")
                    dl_headers = {"Referer": detail_url}
                    req3 = urllib.request.Request(
                        f"https://titrari.ro/get.php?id={dl_id}", headers=dl_headers
                    )
                    with opener.open(req3, timeout=60) as resp3:
                        content = resp3.read()
                    if not content or len(content) < 100:
                        continue
                    srt_data = None
                    if content[:1] == b'1' and b'-->' in content[:200]:
                        srt_data = content
                    elif content[:2] == b'PK':
                        with zipfile.ZipFile(io.BytesIO(content)) as zf:
                            for name in zf.namelist():
                                if name.lower().endswith('.srt'):
                                    srt_data = zf.read(name)
                                    break
                    elif content[:4] == b'Rar!' or b'Rar!' in content[:100]:
                        extract_dir = tempfile.mkdtemp(prefix=f"titrari_{dl_id}_")
                        rar_path = Path(extract_dir) / f"{dl_id}.rar"
                        try:
                            rar_path.write_bytes(content)
                            subprocess.run(
                                ["unrar", "e", str(rar_path), extract_dir],
                                capture_output=True, timeout=30
                            )
                            for f in Path(extract_dir).iterdir():
                                if f.suffix.lower() == '.srt' and f.stat().st_size > 100:
                                    srt_data = f.read_bytes()
                                    break
                        finally:
                            shutil.rmtree(extract_dir, ignore_errors=True)
                    if srt_data and len(srt_data) > 100:
                        dest.write_bytes(srt_data)
                        return True
        except Exception:
            pass

    # 2. Try subs.ro (AJAX search + ZIP download)
    _vv("  trying subs.ro...")
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [("User-Agent", _ua)]

        # Step 2a: Get antispam token from search page
        search_url = f"https://subs.ro/cautare?termen-general={urllib.parse.quote(query)}"
        _vv(f"  subs.ro search: {search_url}")
        req = urllib.request.Request(search_url, headers={"Referer": "https://subs.ro/subtitrari/"})
        with opener.open(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        antispam = None
        m = re.search(r'name="antispam" value="([^"]+)"', html)
        if m:
            antispam = m.group(1)
        _vv(f"  antispam token: {antispam}")
        if not antispam:
            _vv("  no antispam token, skipping subs.ro")
            raise RuntimeError("no antispam token")

        # Step 2b: AJAX search for download links
        data = urllib.parse.urlencode({
            "termen-general": query, "type": "subtitrari", "antispam": antispam
        }).encode()
        req2 = urllib.request.Request(
            "https://subs.ro/ajax/search",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": search_url,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        with opener.open(req2, timeout=15) as resp2:
            ajax_html = resp2.read().decode("utf-8", errors="replace")
        dl_links = re.findall(r'href="([^"]*descarca[^"]*)"', ajax_html)

        # Step 2c: Download ZIP and extract .srt
        for link in dl_links[:3]:
            if not link.startswith("http"):
                link = "https://subs.ro" + ("/" if not link.startswith("/") else "") + link
            detail_url = link.replace("/descarca/", "/")
            req3 = urllib.request.Request(link, headers={"Referer": detail_url})
            with opener.open(req3, timeout=60) as resp3:
                content = resp3.read()
            if len(content) < 100 or content[:2] != b'PK':
                continue
            best = None
            best_size = 0
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith('.srt'):
                        info = zf.getinfo(name)
                        if info.file_size > best_size:
                            best = (name, zf.read(name))
                            best_size = info.file_size
            if best:
                dest.write_bytes(best[1])
                return True
    except Exception:
        pass

    # 3. Try subtitrari-noi.ro via detail page ID
    _vv("  trying subtitrari-noi.ro...")
    try:
        base_url = "https://www.subtitrari-noi.ro"
        search_url = f"{base_url}/?s={urllib.parse.quote(query)}"
        _vv(f"  search: {search_url}")
        req = urllib.request.Request(search_url, headers={"User-Agent": _ua})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Find detail page links (format: Subtitrari-{year}/{title}/{id})
        detail_ids = re.findall(r'/Subtitrari-\d{4}/[^"\'/]+/(\d+)', html)
        _vv(f"  found {len(detail_ids)} detail IDs")
        for detail_id in detail_ids[:10]:
            try:
                detail_url = f"{base_url}/index.php?page=movie_details&act=1&id={detail_id}"
                req2 = urllib.request.Request(detail_url, headers={"User-Agent": _ua})
                with urllib.request.urlopen(req2, timeout=15) as resp2:
                    detail_html = resp2.read().decode("utf-8", errors="replace")
                zip_links = re.findall(r'href=["\']([^"\']*\.zip)["\']', detail_html, re.I)
                for zlink in zip_links[:3]:
                    full_zip = zlink if zlink.startswith("http") else f"{base_url}{zlink}"
                    req3 = urllib.request.Request(full_zip, headers={"User-Agent": _ua})
                    with urllib.request.urlopen(req3, timeout=60) as resp3:
                        content = resp3.read()
                    if len(content) > 100:
                        with zipfile.ZipFile(io.BytesIO(content)) as zf:
                            for name in zf.namelist():
                                if name.lower().endswith('.srt'):
                                    with zf.open(name) as srt_file:
                                        dest.write_bytes(srt_file.read())
                                    return True
            except Exception:
                continue
    except Exception:
        pass

    # 4. titrari.ro legacy search (via /cauta/ path — often 404)
    _vv("  trying titrari.ro legacy search...")
    try:
        base_url = "https://www.titrari.ro"
        for path in [f"/cauta/{urllib.parse.quote(query)}", f"/search/{urllib.parse.quote(query)}"]:
            req = urllib.request.Request(f"{base_url}{path}", headers={"User-Agent": _ua})
            try:
                _vv(f"  fetching {path}")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
                srt_links = re.findall(r'(/ro/downloads/[^"\']+\.srt)', html)
                _vv(f"  found {len(srt_links)} SRT links")
                for rel_path in srt_links[:3]:
                    full_url = f"{base_url}{rel_path}"
                    _vv(f"    downloading {full_url}")
                    dl_req = urllib.request.Request(full_url, headers={"User-Agent": _ua})
                    with urllib.request.urlopen(dl_req, timeout=60) as dl_resp:
                        srt_content = dl_resp.read()
                    if len(srt_content) > 100:
                        _vv(f"    OK ({len(srt_content)} bytes)")
                        dest.write_bytes(srt_content)
                        return True
            except Exception as e:
                _vv(f"    {path} failed: {e}")
                continue
    except Exception:
        pass

    return False

def _safe_replace_file(tmp: Path, target: Path, *, bak_suffix: str = ".bak") -> bool:
    """Atomically replace target with tmp. Backs up target first."""
    bak = target.with_name(target.stem + bak_suffix + target.suffix)
    bak.unlink(missing_ok=True)
    try:
        target.rename(bak)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    try:
        tmp.rename(target)
        bak.unlink()
        return True
    except OSError:
        tmp.unlink(missing_ok=True)
        if bak.exists():
            bak.rename(target)
        return False

def _find_embedded_subs(video_path: Path, *, mkvmerge_exe: str | None) -> tuple[int | None, int | None]:
    """Return (ro_track_id, en_track_id) from embedded subs. Skips forced/HI."""
    exe = mkvmerge_exe or shutil.which("mkvmerge")
    if not exe or video_path.suffix.lower() != ".mkv":
        return None, None
    try:
        info = _mkvmerge_identify(video_path, exe=exe)
    except (RuntimeError, OSError):
        return None, None
    ro_id = en_id = None
    for t in info.get("tracks") or []:
        if t.get("type") != "subtitles":
            continue
        props = t.get("properties") or {}
        if props.get("forced_track") or props.get("hearing_impaired"):
            continue
        lang = (props.get("language_ietf") or props.get("language") or "").strip().lower().replace("_", "-")
        if not lang:
            continue
        tid = int(t["id"])
        if lang in ("ro", "rum", "ron") or lang.startswith("ro-") or (len(lang) >= 2 and lang[:2] == "ro"):
            ro_id = tid
            break
        elif lang in ("eng", "en", "english") or lang.startswith("en-") or (len(lang) >= 2 and lang[:2] == "en"):
            if en_id is None:
                en_id = tid
    return ro_id, en_id

def _remux_keep_sub_track(video_path: Path, *, track_id: int, mkvmerge_exe: str | None) -> bool:
    """Remux keeping video, audio, and only the specified subtitle track."""
    _v(f"Remux keep sub track_id={track_id}: {video_path.name}")
    exe = mkvmerge_exe or shutil.which("mkvmerge")
    if not exe:
        _vv("  mkvmerge not found")
        return False
    # Skip remux if target sub is the only sub track
    try:
        info = _mkvmerge_identify(video_path, exe=exe)
        sub_ids = [t["id"] for t in info.get("tracks") or [] if t.get("type") == "subtitles"]
        if len(sub_ids) <= 1:
            return True
    except (RuntimeError, OSError):
        pass
    tmp = video_path.with_name(video_path.stem + ".keep" + video_path.suffix)
    if tmp.exists():
        tmp = video_path.with_name(video_path.stem + ".keep." + uuid.uuid4().hex + video_path.suffix)
    bak = video_path.with_name(video_path.stem + ".bak" + video_path.suffix)
    bak.unlink(missing_ok=True)
    cmd = [exe, "-o", str(tmp), "--subtitle-tracks", str(track_id), str(video_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=3600)
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            return False
        video_path.rename(bak)
        try:
            tmp.rename(video_path)
            bak.unlink()
            return True
        except Exception:
            if bak.exists() and not video_path.exists():
                bak.rename(video_path)
            tmp.unlink(missing_ok=True)
            return False
    except (OSError, subprocess.TimeoutExpired):
        tmp.unlink(missing_ok=True)
        return False

def _mkv_sidecar_srt(mkv_path: Path) -> Path | None:
    srt = mkv_path.with_suffix(".srt")
    return srt if srt.is_file() else None

def _mkv_strip_log(log_path: Path, message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh: fh.write(f"{ts}  {message}\n")
    except OSError: pass

# ===========================================================================
# Subtitle encoding fix
# ===========================================================================

def _score_text(text: str) -> int:
    r = text.count("\uFFFD")
    c1 = sum(1 for ch in text if 0x80 <= ord(ch) <= 0x9F)
    cnt = sum(1 for ch in text if ord(ch) < 32 and ch not in ("\r", "\n", "\t"))
    moji = len(RE_MOJIBAKE.findall(text))
    ro = len(RE_RO_DIACRITICS.findall(text))
    return r * 1000 + c1 * 500 + moji * 10 + cnt - ro * 5

def _detect_srt_encoding(raw: bytes) -> str | None:
    if raw[:3] == b"\xef\xbb\xbf":
        try:
            t = raw[3:].decode("utf-8")
            if _score_text(t) < 1000: return t
        except UnicodeDecodeError: pass
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            t = raw.decode("utf-16" if raw[:2] == b"\xff\xfe" else "utf-16-be")
            if _score_text(t) < 1000: return t
        except UnicodeDecodeError: pass
    best_text: str | None = None
    best_score = 10**9
    try:
        t = raw.decode("utf-8"); s = _score_text(t)
        if s < best_score: best_score, best_text = s, t
    except UnicodeDecodeError: pass
    for enc in CODEPAGE_CANDIDATES:
        try:
            t = raw.decode(enc)
        except (UnicodeDecodeError, LookupError): continue
        s = _score_text(t)
        if s < best_score: best_score, best_text = s, t
    return best_text if best_text is not None else raw.decode("latin-1", errors="replace")

def fix_srt_file(srt_path: Path) -> bool:
    _v(f"Fix SRT encoding: {srt_path.name}")
    try: raw = srt_path.read_bytes()
    except OSError:
        _vv("  read error")
        return False
    text = _detect_srt_encoding(raw)
    if text is None:
        _vv("  encoding detection failed")
        return False
    _vv(f"  raw size={len(raw)} detected={len(text)} chars")
    text = RE_GARBAGE.sub("", text)
    _vv(f"  after garbage strip={len(text)} chars")
    tmp = srt_path.with_name(srt_path.stem + ".tmpfix" + srt_path.suffix)
    if tmp.exists():
        tmp = srt_path.with_name(srt_path.stem + ".tmpfix." + uuid.uuid4().hex + srt_path.suffix)
    try:
        tmp.write_bytes(codecs.BOM_UTF8 + text.encode("utf-8"))
    except OSError:
        _vv("  write error")
        return False
    if _safe_replace_file(tmp, srt_path):
        _vv("  OK")
        return True
    _vv("  replace error")
    return False

def strip_srt_diacritics(srt_path: Path) -> bool:
    _v(f"Strip diacritics: {srt_path.name}")
    try:
        raw = srt_path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        _vv("  read error")
        return False
    before = sum(1 for c in text if c in DIACRITIC_MAP)
    if not before:
        _vv("  no diacritics found")
        return True
    cleaned = text.translate(_DIAC_TRANS)
    tmp = srt_path.with_name(srt_path.stem + ".tmpdiac" + srt_path.suffix)
    if tmp.exists():
        tmp = srt_path.with_name(srt_path.stem + ".tmpdiac." + uuid.uuid4().hex + srt_path.suffix)
    try:
        tmp.write_bytes(codecs.BOM_UTF8 + cleaned.encode("utf-8"))
    except OSError:
        _vv("  write error")
        return False
    if _safe_replace_file(tmp, srt_path):
        _vv(f"  removed {before} diacritics, OK")
        return True
    _vv("  replace error")
    return False

def _find_video_srt_pairs(root: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for ext in VIDEO_EXTENSIONS:
        for vp in root.rglob(f"*{ext}"):
            if not vp.is_file():
                continue
            if any(m in vp.stem.lower() for m in (".keep", ".remux", ".dedup", ".bak")):
                continue
            srtp = vp.with_suffix(".srt")
            if srtp.is_file():
                pairs.append((vp, srtp))
        for vp in root.rglob(f"*{ext.upper()}"):
            if not vp.is_file():
                continue
            if any(m in vp.stem.lower() for m in (".keep", ".remux", ".dedup", ".bak")):
                continue
            srtp = vp.with_suffix(".srt")
            if srtp.is_file():
                pairs.append((vp, srtp))
    return sorted(set(pairs))

def _find_video_files(root: Path) -> list[Path]:
    """Find all video files under root, excluding temp/marks."""
    videos: list[Path] = []
    for ext in VIDEO_EXTENSIONS:
        for vp in root.rglob(f"*{ext}"):
            if vp.is_file() and not any(m in vp.stem.lower() for m in (".keep", ".remux", ".dedup", ".bak")):
                videos.append(vp)
        for vp in root.rglob(f"*{ext.upper()}"):
            if vp.is_file() and not any(m in vp.stem.lower() for m in (".keep", ".remux", ".dedup", ".bak")):
                videos.append(vp)
    return sorted(set(videos))

# ===========================================================================
# Cleanup
# ===========================================================================

def _cleanup_folder(folder: Path, root: Path) -> None:
    if not folder.is_dir():
        _vv(f"  cleanup skip: {folder} not a dir")
        return
    _v(f"Cleanup folder: {folder.name}")
    removed = renamed_video = renamed_subs = 0
    for fp in list(folder.iterdir()):
        if is_own_file(fp, root): continue
        if fp.is_file():
            if fp.suffix.lower() in JUNK_EXTENSIONS:
                fp.unlink(missing_ok=True); removed += 1
                _vv(f"  removed junk: {fp.name}")
                continue
            if fp.stem.lower().startswith("sample") and fp.suffix.lower() in (VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS):
                fp.unlink(missing_ok=True); removed += 1
                _vv(f"  removed sample: {fp.name}")
                continue
        elif fp.is_dir() and fp.name.lower() in JUNK_DIRS:
            shutil.rmtree(fp, ignore_errors=True)
            _vv(f"  removed junk dir: {fp.name}")
    fname = folder.name
    fv = next((fp for fp in sorted(folder.iterdir()) if fp.is_file() and not is_own_file(fp, root) and fp.suffix.lower() in VIDEO_EXTENSIONS), None)
    if fv is not None:
        t = fv.with_name(fname + fv.suffix)
        if fv.name != t.name and not t.exists():
            try:
                fv.rename(t)
                renamed_video += 1
                _vv(f"  renamed video: {fv.name} -> {t.name}")
            except OSError:
                _vv(f"  rename video error: {fv.name}")
                pass
    for fp in list(folder.iterdir()):
        if fp.is_file() and fp.suffix.lower() in SUBTITLE_EXTENSIONS:
            t = fp.with_name(fname + fp.suffix)
            if fp.name != t.name and not t.exists():
                try:
                    fp.rename(t)
                    renamed_subs += 1
                    _vv(f"  renamed sub: {fp.name} -> {t.name}")
                except OSError:
                    _vv(f"  rename sub error: {fp.name}")
                    pass
    _v(f"  Folder {folder.name}: removed {removed}, renamed {renamed_video} video(s), {renamed_subs} sub(s)")

def _flatten_folders(root: Path, dry_run: bool = False) -> int:
    _v(f"Flatten folders: root={root} dry_run={dry_run}")
    moved = 0
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        _vv(f"  checking: {child.name}")
        vids = [fp for ext in VIDEO_EXTENSIONS for fp in child.glob(f"*{ext}")] + \
               [fp for ext in VIDEO_EXTENSIONS for fp in child.glob(f"*{ext.upper()}")]
        srt_files = list(child.glob("*.srt")) + list(child.glob("*.SRT"))
        if not vids and not srt_files and not any(True for _ in child.iterdir()):
            continue
        for fp in vids + srt_files:
            set_window_title(f"Flatten: {fp.name}")
            dest = root / fp.name
            if dest.exists():
                continue
            if dry_run:
                _indent(f"would move: {fp.name} -> {dest.name}")
            else:
                fp.rename(dest)
            moved += 1
        if dry_run:
            _indent(f"would delete folder: {child.name}")
        else:
            shutil.rmtree(child, ignore_errors=True)
    return moved

# ===========================================================================
# Series-specific: episode parsing + OpenSubtitles download + remux
# ===========================================================================

def _clean_show_name(raw: str) -> str:
    s = raw.replace(".", " ").replace("_", " ").strip()
    s = RE_TRAILING_YEAR.sub("", s).strip()
    s = RE_TRAILING_SEP.sub("", s).strip()
    return s

def _clean_episode_title(raw: str) -> str:
    if not raw: return ""
    s = raw.replace(".", " ").replace("_", " ").strip()
    s = RE_JUNK_TITLE.sub("", s).strip()
    s = RE_QUALITY_TOKENS.sub("", s).strip()
    s = RE_MULTI_SPACE.sub(" ", s).strip()
    s = RE_TRAILING_SEP.sub("", s).strip()
    return s.lstrip("-– ").strip()

def parse_episode_stem(stem: str) -> tuple[str, int, int, str] | None:
    m = RE_EPISODE.match(stem.strip())
    if not m: return None
    show = _clean_show_name(m.group(1))
    season, episode = int(m.group(2)), int(m.group(3))
    title_raw = m.group(4)
    title = _clean_episode_title(title_raw) if title_raw else ""
    if not title or RE_QUALITY_TOKENS.fullmatch(title.strip()): title = ""
    return show, season, episode, title

def _os_headers(api_key: str) -> dict[str, str]:
    return {"User-Agent": OPENSUBTITLES_COM_USER_AGENT, "Api-Key": api_key.strip(), "Accept": "application/json"}

def _compute_opensubtitles_hash(path: Path) -> tuple[str, int] | None:
    """OpenSubtitles hash: 64-bit from first/last 64KB + file size.

    Returns (hex_hash, file_size_in_bytes) or None on error.
    """
    chunk_size = 65536
    try:
        size = path.stat().st_size
        if size < chunk_size * 2:
            return None
        with path.open("rb") as f:
            head = f.read(chunk_size)
            f.seek(-chunk_size, os.SEEK_END)
            tail = f.read(chunk_size)
    except OSError:
        return None
    data = head + tail
    lo = size & 0xFFFFFFFF
    hi = (size >> 32) & 0xFFFFFFFF
    max32 = 0x100000000
    for i in range(0, len(data), 8):
        chunk = data[i:i+8]
        if len(chunk) < 8:
            chunk = chunk + b"\x00" * (8 - len(chunk))
        a, b, c, d, e, f, g, h = chunk
        lo = (lo + a + (b << 8) + (c << 16) + (d << 24))
        hi = (hi + e + (f << 8) + (g << 16) + (h << 24))
        if lo >= max32:
            hi += lo >> 32
            lo &= 0xFFFFFFFF
        if hi >= max32:
            hi &= 0xFFFFFFFF
    return f"{hi:08x}{lo:08x}", size

def opensubtitles_download(query: str, dest: Path, *, api_key: str, lang: str = "ro", season: int | None = None, episode: int | None = None) -> bool:
    key = (api_key or "").strip()
    if not key: return False
    params: dict[str, str] = {"query": query, "languages": lang}
    if season is not None: params["season_number"] = str(season)
    if episode is not None: params["episode_number"] = str(episode)
    if season is not None and episode is not None: params["type"] = "episode"
    url = f"{OPENSUBTITLES_COM_API_BASE}/subtitles?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers=_os_headers(key))
        with urllib.request.urlopen(req, timeout=45) as resp: data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    items = data.get("data") or []
    if not items: return False
    file_id: int | None = None
    for item in items:
        files = (item.get("attributes") or {}).get("files") or []
        if files and files[0].get("file_id") is not None: file_id = int(files[0]["file_id"]); break
    if file_id is None: return False
    try:
        dreq = urllib.request.Request(
            f"{OPENSUBTITLES_COM_API_BASE}/download", data=json.dumps({"file_id": file_id}).encode("utf-8"),
            method="POST", headers={**_os_headers(key), "Content-Type": "application/json"})
        with urllib.request.urlopen(dreq, timeout=45) as resp: dresp = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    link = dresp.get("link")
    if not link or not isinstance(link, str): return False
    try:
        with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": OPENSUBTITLES_COM_USER_AGENT}), timeout=120) as resp:
            blob = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): return False
    if len(blob) < 50: return False
    try: dest.write_bytes(blob); return True
    except OSError: return False

def _os_download_file_id(file_id: int, dest: Path, *, api_key: str) -> bool:
    key = (api_key or "").strip()
    if not key:
        return False
    try:
        dreq = urllib.request.Request(
            f"{OPENSUBTITLES_COM_API_BASE}/download",
            data=json.dumps({"file_id": file_id}).encode("utf-8"),
            method="POST",
            headers={**_os_headers(key), "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(dreq, timeout=45) as resp:
            dresp = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return False
    link = dresp.get("link")
    if not link or not isinstance(link, str):
        return False
    try:
        with urllib.request.urlopen(
            urllib.request.Request(link, headers={"User-Agent": OPENSUBTITLES_COM_USER_AGENT}),
            timeout=120,
        ) as resp:
            blob = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False
    if len(blob) < 50:
        return False
    try:
        dest.write_bytes(blob)
        return True
    except OSError:
        return False

def opensubtitles_search_and_download_by_hash(video_path: Path, dest: Path, *, api_key: str, lang: str = "ro") -> bool:
    """Hash-based subtitle search via OpenSubtitles.com REST API.

    Computes file hash, queries OS.com for exact-match subtitle,
    downloads best match (preferring Romanian, non-HI, trusted).
    Returns True on success.
    """
    key = (api_key or "").strip()
    if not key:
        _vv("  no API key")
        return False
    h = _compute_opensubtitles_hash(video_path)
    if h is None:
        _vv("  hash computation failed (file too small?)")
        return False
    movie_hash, file_size = h
    _vv(f"  OS hash={movie_hash} size={file_size}")
    params = urllib.parse.urlencode({
        "moviehash": movie_hash,
        "moviebytesize": str(file_size),
        "languages": lang,
    })
    url = f"{OPENSUBTITLES_COM_API_BASE}/subtitles?{params}"
    try:
        req = urllib.request.Request(url, headers=_os_headers(key))
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        _vv(f"  search error: {e}")
        return False
    items = data.get("data") or []
    if not items:
        _vv("  no subtitle found by hash")
        return False
    _vv(f"  found {len(items)} subtitle(s) by hash")
    scored: list[tuple[int, int]] = []
    for item in items:
        attr = item.get("attributes") or {}
        files = attr.get("files") or []
        if not files or files[0].get("file_id") is None:
            continue
        fid = int(files[0]["file_id"])
        score = 0
        sub_lang = (attr.get("language") or "").lower()
        if sub_lang in ("ro", "rum", "ron"):
            score += 100
        if attr.get("trusted"):
            score += 50
        if attr.get("hd"):
            score += 20
        if attr.get("hearing_impaired"):
            score -= 30
        scored.append((score, fid))
    if not scored:
        _vv("  no downloadable files")
        return False
    scored.sort(key=lambda x: -x[0])
    best_fid = scored[0][1]
    _vv(f"  best file_id={best_fid} (score={scored[0][0]})")
    return _os_download_file_id(best_fid, dest, api_key=key)

def download_subtitles_by_hash_with_fallback(video_path: Path, dest: Path, *, api_key: str, lang: str = "ro") -> bool:
    """Try hash-based search first, fall back to name-based OS.com download.

    Uses the source video's original hash (before remuxing) for exact match.
    If hash finds nothing, falls back to filename-based search.
    Returns True if a subtitle was downloaded.
    """
    h = _compute_opensubtitles_hash(video_path)
    if h:
        _v(f"  try hash: {h[0]}")
        if opensubtitles_search_and_download_by_hash(video_path, dest, api_key=api_key, lang=lang):
            _bullet(f"  ✓ hash match: {dest.name}")
            return True
        _v(f"  hash miss, trying name fallback...")
    else:
        _v(f"  hash computation failed, trying name fallback...")
    # Fallback: name-based search using filename
    stem = video_path.stem
    query = stem.replace(".", " ").replace("_", " ").replace("-", " ")
    # Strip common tags like [1080p], WEBRip, etc.
    query = re.sub(r"\[.*?\]", "", query)
    query = re.sub(r"\b\d{3,4}p\b", "", query)
    query = re.sub(r"\b(WEB[- ]?DL|WEBRip|BluRay|BrRip|x264|x265|HEVC|DD5\.1|DDP5\.1|Atmos|H\.264|YIFY|YTS|GalaxyRG|BONE|MA)\b", "", query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip()
    # Strip leading year
    query = re.sub(r"^\d{4}\s+", "", query).strip()
    # Strip trailing year
    query = re.sub(r"\s+\d{4}$", "", query).strip()
    if query:
        _v(f"  name search: '{query}'")
        if opensubtitles_download(query, dest, api_key=api_key, lang=lang):
            _bullet(f"  ✓ name match: {dest.name}")
            return True
    # Last resort: try original stem as-is
    _v(f"  name search (raw stem): '{video_path.stem}'")
    if opensubtitles_download(video_path.stem, dest, api_key=api_key, lang=lang):
        _bullet(f"  ✓ name match (raw): {dest.name}")
        return True
    _bullet(f"  ✗ no subtitles found for {video_path.name}")
    return False

def download_via_subliminal(video: Path, *, subliminal_exe: str, lang: str = "ro", opensubtitlescom_user: str = "", force: bool = False) -> bool:
    exe = resolve_subliminal_exe(subliminal_exe)
    if not exe: return False
    pw = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_PASSWORD") or "").strip()
    cmd: list[str] = [exe]
    if opensubtitlescom_user and pw: cmd.extend(["--opensubtitlescom", opensubtitlescom_user, pw])
    cmd.extend(["download", "-l", lang, "-s", str(video)])
    if force: cmd.append("-f")
    # Tell subliminal to write directly to Processed/ instead of copying back
    cmd.extend(["--output-dir", str(video.parent / "Processed")])
    try: return subprocess.run(cmd, timeout=300, capture_output=True).returncode == 0
    except subprocess.TimeoutExpired: return False

def remux_series_video(video_path: Path, srt_path: Path, *, mkvmerge_exe: str | None, lang: str = "ro") -> bool:
    _v(f"Remux: {video_path.name} + {srt_path.name} (lang={lang})")
    ext = video_path.suffix.lower()
    is_mkv = ext == ".mkv"
    use_mkvmerge = mkvmerge_exe is not None
    out_suffix = ".mkv" if use_mkvmerge else ext
    tmp = video_path.with_name(video_path.stem + ".remux" + out_suffix)
    if tmp.exists(): tmp = video_path.with_name(video_path.stem + ".remux." + uuid.uuid4().hex + out_suffix)
    bak = video_path.with_name(video_path.stem + ".bak" + video_path.suffix)
    bak.unlink(missing_ok=True)
    lang_map = {"ro": "rum", "en": "eng"}
    lang_name = {"ro": "Romanian", "en": "English"}
    mkv_lang = lang_map.get(lang, lang)
    ff_lang_name = lang_name.get(lang, lang.upper())
    try:
        if use_mkvmerge:
            cmd = [mkvmerge_exe, "-o", str(tmp), "-S", str(video_path), "--language", f"0:{lang}", "--track-name", f"0:{ff_lang_name}", str(srt_path)]
        else:
            cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(srt_path), "-map", "0:v", "-map", "0:a", "-map", "1", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", f"language={mkv_lang}", "-metadata:s:s:0", f"title={ff_lang_name}", str(tmp)]
        _log_cmd(cmd)
        _vv("  running muxer (may take a while)...")
        proc = subprocess.run(cmd, capture_output=True, timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip() or f"exited with {proc.returncode}")
        target = video_path if is_mkv or not use_mkvmerge else video_path.with_suffix(".mkv")
        video_path.rename(bak)
        try: tmp.rename(target); bak.unlink()
        except Exception:
            if bak.exists() and not target.exists(): bak.rename(video_path)
            if tmp.exists(): tmp.unlink()
            raise
        return True
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        if tmp.exists(): tmp.unlink()
        if bak.exists() and not video_path.exists(): bak.rename(video_path)
        _bullet(f"ERROR remuxing {video_path.name}: {exc}")
        return False

# ===========================================================================
# HTTP helpers (shared)
# ===========================================================================

def _http_get_json(url: str, *, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "VIDEO_TOOL/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp: return json.loads(resp.read().decode("utf-8"))

def _http_get_bytes(url: str, *, timeout: int = 90, user_agent: str | None = None) -> bytes:
    ua = user_agent or "Mozilla/5.0 (compatible; VIDEO_TOOL/1.1)"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=timeout) as resp:
        return resp.read()

# ===========================================================================
# Movies-specific: title parsing
# ===========================================================================

def clean_title_for_fs(raw: str) -> str:
    s = RE_BAD_FS_CHARS.sub("", raw)
    s = RE_INVISIBLE.sub("", s)
    s = RE_MULTI_SPACE.sub(" ", s).strip()
    return s.strip(" .")

def parse_loose_movie_stem(stem: str) -> tuple[str, str] | None:
    m = RE_LOOSE_TITLE_YEAR.match(stem.strip())
    if not m: return None
    title_raw, year = m.group(1).strip(), m.group(2)
    if not title_raw: return None
    try:
        if not (1900 <= int(year) <= 2100): return None
    except ValueError: return None
    title = clean_title_for_fs(title_raw)
    return (title, year) if title else None

def _insert_letter_digit_spaces(s: str) -> str:
    s = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", s)
    s = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", s)
    return s

def _split_runon_trailing_word(token: str) -> str:
    if " " in token or not token.isalpha() or len(token) < 8: return token
    tl = token.lower()
    for w in sorted(_RUNON_TRAIL_WORDS, key=len, reverse=True):
        if tl.endswith(w):
            prefix = tl[:-len(w)]
            if len(prefix) >= 4 and prefix.isalpha(): return f"{prefix} {w}"
    return token

def guess_loose_title_without_year(stem: str) -> str | None:
    s = stem.strip().replace(".", " ").replace("_", " ")
    s = RE_LOOSE_JUNK_TOKEN.sub(" ", s)
    s = re.split(r"\s[-–]\s", s, maxsplit=1)[0]
    s = _insert_letter_digit_spaces(s)
    s = RE_MULTI_SPACE.sub(" ", s).strip(" .-_")
    if s: s = " ".join(_split_runon_trailing_word(p) for p in s.split())
    s = RE_MULTI_SPACE.sub(" ", s).strip(" .-_")
    return clean_title_for_fs(s) or None

def _split_loose_stem_tokens(stem: str) -> list[str]:
    return [p for p in re.split(r"[._\s]+", stem.strip()) if p]

def _token_signals_release_quality(tok: str) -> bool:
    t = tok.lower()
    if RE_LOOSE_JUNK_TOKEN.search(t): return True
    if re.fullmatch(r"(?:usa|uk|gbr|aus|ger|fra|esp|ita|pol|jpn|kor|chi|rus|ce{2}|french|german|italian|spanish|multi|dual)", t): return True
    if re.fullmatch(r"h\d{3}", t) or re.fullmatch(r"x\d{3}", t): return True
    if t.startswith("ddp") or t in {"atmos", "sdr", "hdr", "dv", "truehd", "dts-hd.ma", "dts"}: return True
    if re.fullmatch(r"ddp\d(?:\.\d)?", t): return True
    if re.fullmatch(r"(?:dvd5|dvd9|ntsc|pal)", t): return True
    return False

def _looks_like_non_movie_event(tokens: list[str]) -> bool:
    if any(re.fullmatch(r"\d{8}", t) for t in tokens): return True
    if tokens and tokens[0].lower() in {"cctv", "aiqiyi"}: return True
    return False

def parse_loose_release_year_stem(stem: str) -> tuple[str, str] | None:
    tokens = _split_loose_stem_tokens(stem)
    if _looks_like_non_movie_event(tokens) or len(tokens) < 2: return None
    for i, tok in enumerate(tokens):
        if i == 0: continue
        if not re.fullmatch(r"(?:19|20)\d{2}", tok): continue
        try: y = int(tok)
        except ValueError: continue
        if not (1900 <= y <= 2100): continue
        if tokens[i+1:] and not any(_token_signals_release_quality(x) for x in tokens[i+1:]): continue
        title = clean_title_for_fs(" ".join(tokens[:i]).replace(".", " ").replace("_", " "))
        if not title: continue
        return title, tok
    return None

def _cinemeta_release_matches_year(release_info: str, year: str) -> bool:
    ri = (release_info or "").strip()
    if not ri: return False
    if ri.startswith(year): return True
    return re.split(r"[\u2013\u2014\-]", ri, maxsplit=1)[0].strip() == year

def cinemeta_fetch_poster_jpg(title: str, year: str, dest: Path) -> bool:
    q = urllib.parse.quote(title)
    try: data = _http_get_json(f"https://v3-cinemeta.strem.io/catalog/movie/top/search={q}.json", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    for m in (data.get("metas") or []):
        if not _cinemeta_release_matches_year(str(m.get("releaseInfo") or ""), year): continue
        poster = m.get("poster")
        if not poster or not isinstance(poster, str) or not poster.startswith("http"): continue
        if "media-amazon.com" in poster and "_SX" in poster: poster = re.sub(r"_SX\d+_", "_SX500_", poster, count=1)
        try: blob = _http_get_bytes(poster, timeout=90)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): continue
        if len(blob) < 1000: continue
        try: dest.write_bytes(blob); return True
        except OSError: return False
    return False

def omdb_fetch_poster_jpg(api_key: str, title: str, year: str, dest: Path) -> bool:
    params = urllib.parse.urlencode({"apikey": api_key, "t": title, "y": year, "r": "json"})
    try: data = _http_get_json(f"https://www.omdbapi.com/?{params}", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    if str(data.get("Response", "")).lower() == "false": return False
    pu = data.get("Poster")
    if not pu or pu == "N/A": return False
    try: blob = _http_get_bytes(str(pu), timeout=90)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): return False
    if len(blob) < 1000: return False
    try: dest.write_bytes(blob); return True
    except OSError: return False

def itunes_fetch_poster_jpg(title: str, year: str, dest: Path) -> bool:
    term = urllib.parse.quote(f"{title} {year}")
    try: data = _http_get_json(f"https://itunes.apple.com/search?term={term}&media=movie&entity=movie&limit=10", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    y_int = int(year)
    for r in (data.get("results") or []):
        if r.get("trackYear") is not None and int(r["trackYear"]) != y_int: continue
        art = r.get("artworkUrl100") or r.get("artworkUrl512")
        if not art or not isinstance(art, str): continue
        hi = art.replace("100x100bb", "600x600bb").replace("100x100", "600x600bb")
        try: blob = _http_get_bytes(hi, timeout=90)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): continue
        if len(blob) < 1000: continue
        try: dest.write_bytes(blob); return True
        except OSError: return False
    return False

def tmdb_fetch_poster_jpg(api_key: str, title: str, year: str, dest: Path) -> bool:
    key_q = urllib.parse.quote(api_key, safe="")
    q = urllib.parse.quote(title)
    try: data = _http_get_json(f"https://api.themoviedb.org/3/search/movie?api_key={key_q}&query={q}&year={year}", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    results = data.get("results") or []
    if not results: return False
    pp = results[0].get("poster_path")
    if not pp or not isinstance(pp, str): return False
    try: blob = _http_get_bytes(f"https://image.tmdb.org/t/p/w780{pp}", timeout=90)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): return False
    if len(blob) < 1000: return False
    try: dest.write_bytes(blob); return True
    except OSError: return False

def fetch_movie_poster_open_sources(dest: Path, title: str, year: str, *, tmdb_key: str, omdb_key: str) -> tuple[bool, str]:
    _v(f"Fetch poster: {title} ({year})")
    if tmdb_key and tmdb_fetch_poster_jpg(tmdb_key, title, year, dest):
        _vv("  TMDB OK"); return True, "TMDB"
    _vv("  TMDB failed")
    if omdb_key and omdb_fetch_poster_jpg(omdb_key, title, year, dest):
        _vv("  OMDb OK"); return True, "OMDb"
    _vv("  OMDb failed")
    if cinemeta_fetch_poster_jpg(title, year, dest):
        _vv("  Cinemeta OK"); return True, "Cinemeta"
    _vv("  Cinemeta failed")
    if itunes_fetch_poster_jpg(title, year, dest):
        _vv("  iTunes OK"); return True, "iTunes"
    _vv("  iTunes failed")
    return False, ""

def _tmdb_search_result_score(rough_title: str, year_s: str, r: dict) -> float:
    title = str(r.get("title") or r.get("original_title") or "")
    tl = title.lower()
    pop = float(r.get("popularity") or 0)
    votes = float(r.get("vote_count") or 0)
    score = pop + math.log1p(max(votes, 0.0)) * 0.6
    for bad in _TMDB_JUNK_TITLE_HINTS:
        if bad in tl: score -= 85.0
    if isinstance(r.get("genre_ids") or [], list) and 99 in r["genre_ids"]: score -= 30.0
    rd = str(r.get("release_date") or "")
    if year_s and rd.startswith(year_s): score += 250.0
    rough_l = rough_title.lower()
    title_l = title.lower()
    qtok = set(re.findall(r"[a-z0-9]+", rough_l))
    ttok = set(re.findall(r"[a-z0-9]+", title_l))
    if qtok and ttok: score += min(float(len(qtok & ttok)) * 14.0, 55.0)
    rnq = re.sub(r"[^a-z0-9]+", "", rough_l)
    rnt = re.sub(r"[^a-z0-9]+", "", title_l)
    if rnq and rnt and (rnq in rnt or rnt in rnq): score += 28.0
    return score

def tmdb_resolve_movie_title_year_and_id(api_key: str, rough_title: str, year: str | None = None) -> tuple[str, str, int] | None:
    _v(f"TMDB resolve: '{rough_title}' year={year}")
    if not (api_key or "").strip():
        _vv("  no API key")
        return None
    year_s = (year or "").strip()
    key_q = urllib.parse.quote(api_key.strip(), safe="")
    q = urllib.parse.quote(rough_title)
    url = f"https://api.themoviedb.org/3/search/movie?api_key={key_q}&query={q}"
    if year_s: url += f"&year={year_s}"
    _vv(f"  searching TMDB...")
    try: data = _http_get_json(url, timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        _vv(f"  TMDB search error: {e}")
        return None
    results = data.get("results") or []
    _vv(f"  {len(results)} result(s)")
    best: dict | None = None
    for r in results:
        if year_s and str(r.get("release_date") or "").startswith(year_s): best = r; break
    if best is None and results:
        if year_s: best = results[0]
        else:
            pool = results[:20]
            scored = [(_tmdb_search_result_score(rough_title, year_s, r), r) for r in pool]
            scored.sort(key=lambda t: t[0], reverse=True)
            best = scored[0][1]
    if not best:
        _vv(f"  no match found")
        return None
    mid = best.get("id")
    if mid is None: return None
    mid_int = int(mid)
    _vv(f"  best match: id={mid_int} title={best.get('title')}")
    try: detail = _http_get_json(f"https://api.themoviedb.org/3/movie/{mid_int}?api_key={key_q}&language=en-US", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        _vv(f"  detail fetch failed")
        return None
    name = detail.get("title") or detail.get("original_title")
    if not name or not isinstance(name, str):
        _vv(f"  no name in detail")
        return None
    cleaned = clean_title_for_fs(name.strip())
    if not cleaned:
        _vv(f"  cleaned name empty")
        return None
    rd = str(detail.get("release_date") or best.get("release_date") or "")
    release_year = rd[:4] if re.match(r"^\d{4}", rd) else (year_s or None)
    if not release_year:
        _vv(f"  no release year")
        return None
    tid = detail.get("id")
    _vv(f"  resolved: {cleaned} ({release_year}) id={tid or mid_int}")
    return cleaned, release_year, int(tid) if tid is not None else mid_int

def tmdb_resolve_movie_title_and_id(api_key: str, rough_title: str, year: str) -> tuple[str, int] | None:
    r = tmdb_resolve_movie_title_year_and_id(api_key, rough_title, year)
    return (r[0], r[2]) if r else None

def cinemeta_lookup_canonical_title(rough_title: str, year: str) -> str | None:
    q = urllib.parse.quote(rough_title)
    try: data = _http_get_json(f"https://v3-cinemeta.strem.io/catalog/movie/top/search={q}.json", timeout=30)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return None
    for m in (data.get("metas") or []):
        if not _cinemeta_release_matches_year(str(m.get("releaseInfo") or ""), year): continue
        name = m.get("name")
        if isinstance(name, str) and name.strip(): return clean_title_for_fs(name.strip()) or None
    return None

def opensubtitles_com_download_romanian_srt(consumer_api_key: str, tmdb_movie_id: int, dest_srt: Path) -> bool:
    """Download Romanian subtitle from OpenSubTitles.com API.

    Uses TMDB movie ID to find the subtitle.
    Returns True on successful download.
    """
    _v(f"OS.com download: tmdb_id={tmdb_movie_id} -> {dest_srt.name}")
    if not consumer_api_key.strip():
        _vv("  no API key")
        return False
    q = urllib.parse.urlencode({"languages": "ro", "tmdb_id": str(tmdb_movie_id), "order_by": "download_count", "order_direction": "desc"})
    _vv(f"  searching OS.com for tmdb_id={tmdb_movie_id}...")
    try:
        req = urllib.request.Request(f"{OPENSUBTITLES_COM_API_BASE}/subtitles?{q}", headers=_os_headers(consumer_api_key))
        with urllib.request.urlopen(req, timeout=45) as resp: data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        _vv(f"  search error: {e}")
        return False
    items = data.get("data") or []
    _vv(f"  found {len(items)} subtitle(s)")
    if not items:
        _vv(f"  no subtitles found")
        return False
    file_id = next((int(files[0]["file_id"]) for item in items for files in [(item.get("attributes") or {}).get("files") or []] if files and files[0].get("file_id") is not None), None)
    if file_id is None:
        _vv(f"  no file_id found")
        return False
    _vv(f"  file_id={file_id}")
    try:
        dreq = urllib.request.Request(f"{OPENSUBTITLES_COM_API_BASE}/download", data=json.dumps({"file_id": file_id}).encode("utf-8"), method="POST", headers={**_os_headers(consumer_api_key), "Content-Type": "application/json"})
        with urllib.request.urlopen(dreq, timeout=45) as resp: dresp = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError): return False
    link = dresp.get("link")
    if not link or not isinstance(link, str): return False
    try:
        with urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": OPENSUBTITLES_COM_USER_AGENT}), timeout=120) as resp: blob = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError): return False
    if len(blob) < 50: return False
    try: dest_srt.write_bytes(blob); return True
    except OSError: return False

def opensubtitles_com_try_romanian_for_videos(videos_with_tmdb: list[tuple[Path, int | None]], *, consumer_api_key: str) -> int:
    key = (consumer_api_key or "").strip()
    if not key: return 0
    ok = 0
    for video, tmdb_mid in videos_with_tmdb:
        if tmdb_mid is None: continue
        # When organizing movies, dest is in source folder
        # We want to check if subtitle exists in destination (Processed/ folder)
        dest = video.with_suffix(".srt")
        if dest.is_file(): continue
        # Download to source location for check, but will be moved later
        if opensubtitles_com_download_romanian_srt(key, tmdb_mid, dest): ok += 1
    return ok

# ===========================================================================
# Movies-specific: organize loose + pipeline steps 0-6
# ===========================================================================

def iter_loose_movie_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.is_file():
            if is_own_file(p, root): continue
            if p.suffix.lower() in MOVIE_EXTENSIONS: out.append(p)
        elif p.is_dir() and not RE_YEAR_NAME_FOLDER.match(p.name):
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in MOVIE_EXTENSIONS: out.append(child)
    return out

def organize_loose_videos_in_root(root: Path, *, tmdb_api_key: str = "", omdb_api_key: str = "", auto_fetch_ro_subtitles: bool = True, subliminal_exe: str = "", opensubtitlescom_user: str = "") -> None:
    t0 = _timer_start()
    _v(f"organize_loose_videos_in_root: root={root}")
    tmdb_k = (tmdb_api_key or os.environ.get("PROCESS_MOVIES_TMDB_API_KEY", "") or _DEFAULT_TMDB_API_KEY).strip()
    omdb_k = (omdb_api_key or os.environ.get("PROCESS_MOVIES_OMDB_API_KEY", "") or _DEFAULT_OMDB_API_KEY).strip()
    _v(f"TMDB key={'set' if tmdb_k else 'NOT set'}, OMDB key={'set' if omdb_k else 'NOT set'}")
    _heading("Step 0 - Sort loose movie files into folders")
    loose = list(iter_loose_movie_files(root))
    _v(f"Found {len(loose)} loose movie file(s)")
    if not loose: _bullet("No loose movie files found."); return
    moved = pattern_misses = skipped = posters = 0
    videos_with_tmdb: list[tuple[Path, int | None]] = []
    for i, fp in enumerate(loose):
        _v(f"[{i+1}/{len(loose)}] {fp.name}")
        set_window_title(f"Organize: {fp.name}")
        orig_stem = fp.stem
        parsed = parse_loose_movie_stem(orig_stem)
        if parsed: title, year = parsed; _vv(f"  parsed as: {title} ({year})")
        else:
            pd = parse_loose_release_year_stem(orig_stem)
            if pd: title, year = pd; _vv(f"  release-year parse: {title} ({year})")
            else:
                guessed = guess_loose_title_without_year(orig_stem)
                if not guessed: pattern_misses += 1; _vv(f"  UNRECOGNIZED"); continue
                title, year = guessed, ""
                _vv(f"  guessed: {title}")
        tm_mid = None
        tr = tmdb_resolve_movie_title_year_and_id(tmdb_k, title, year or None)
        if tr:
            title, year, tm_mid = tr
            _vv(f"  TMDB resolved: {title} ({year}) id={tm_mid}")
        elif year:
            cx = cinemeta_lookup_canonical_title(title, year); title = cx if cx else title
            _vv(f"  Cinemeta resolved: {title} ({year})")
        else:
            pattern_misses += 1; _vv(f"  NO TMDB match"); continue
        folder_name = f"{year} - {title}"
        dest_dir = root / folder_name
        dest_video = dest_dir / f"{title}{fp.suffix.lower()}"
        _vv(f"  dest: {dest_dir.name}/{dest_video.name}")
        if dest_video.exists() and dest_video.resolve() != fp.resolve():
            skipped += 1
            _vv(f"  EXISTS, skipping")
            videos_with_tmdb.append((dest_video, tm_mid))
            continue
        dest_dir.mkdir(parents=False, exist_ok=True)
        old_parent = fp.parent
        try:
            if dest_video.resolve() != fp.resolve():
                fp.rename(dest_video); moved += 1
                _vv(f"  moved video -> {dest_video.name}")
        except OSError:
            _vv(f"  MOVE ERROR"); skipped += 1; continue
        if old_parent != root and old_parent.is_dir() and old_parent.resolve() != dest_dir.resolve() and not any(old_parent.iterdir()):
            try: old_parent.rmdir(); _vv(f"  removed old dir: {old_parent.name}")
            except OSError: pass
        poster_path = dest_dir / "poster.jpg"
        if not poster_path.exists() and fetch_movie_poster_open_sources(poster_path, title, year, tmdb_key=tmdb_k, omdb_key=omdb_k):
            posters += 1
            _vv(f"  downloaded poster")
        videos_with_tmdb.append((dest_video, tm_mid))
    _bullet(f"Moved: {moved}, unrecognized: {pattern_misses}, skipped: {skipped}, posters: {posters}")
    filtered = [(vp, mid) for vp, mid in videos_with_tmdb if vp.is_file() and not _has_romanian_subtitle(vp)]
    os_rest_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    if auto_fetch_ro_subtitles and filtered:
        # Phase 0: Hash search on source file (same hash after move)
        if os_rest_key:
            _heading("Step 0a - Hash-based subtitle search")
            hash_ok = 0
            for vp, _ in filtered:
                srt_path = vp.with_suffix(".srt")
                if srt_path.exists():
                    continue
                if download_subtitles_by_hash_with_fallback(vp, srt_path, api_key=os_rest_key, lang="ro"):
                    hash_ok += 1
            if hash_ok:
                _bullet(f"Hash search: {hash_ok} downloaded")
        # Subliminal for remaining
        still_needed = [(vp, mid) for vp, mid in filtered if vp.is_file() and not _has_romanian_subtitle(vp)]
        _heading("Step 0b - Romanian subtitles (Subliminal)")
        fetch_subtitles_subliminal(root, languages=["ro"], subliminal_exe=subliminal_exe, opensubtitlescom_user=opensubtitlescom_user, force=False, paths=[v[0] for v in still_needed])
        # OS.com API for remaining
        still_needed_2 = [(vp, mid) for vp, mid in still_needed if vp.is_file() and not _has_romanian_subtitle(vp)]
        if still_needed_2 and os_rest_key:
            _heading("Step 0c - OpenSubtitles.com API")
            opensubtitles_com_try_romanian_for_videos(still_needed_2, consumer_api_key=os_rest_key)

def organize_loose_to_processed(root: Path, *, tmdb_api_key: str = "", omdb_api_key: str = "", auto_fetch_ro_subtitles: bool = True, subliminal_exe: str = "", opensubtitlescom_user: str = "", mkvmerge_exe: str | None = None) -> None:
    """Copy movies to Processed/<year> - <title>/ without touching originals.

    Non-destructive: reads from root, writes to root/Processed/.
    Each movie gets its own folder with video, poster, and Romanian subtitle.
    """
    t0 = _timer_start()
    _v(f"organize_loose_to_processed: root={root}")
    tmdb_k = (tmdb_api_key or os.environ.get("PROCESS_MOVIES_TMDB_API_KEY", "") or _DEFAULT_TMDB_API_KEY).strip()
    omdb_k = (omdb_api_key or os.environ.get("PROCESS_MOVIES_OMDB_API_KEY", "") or _DEFAULT_OMDB_API_KEY).strip()
    os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    _v(f"TMDB={'set' if tmdb_k else 'NOT SET'}, OMDB={'set' if omdb_k else 'NOT SET'}, OS_API={'set' if os_api_key else 'NOT SET'}")
    _heading("Process movies to Processed/ (non-destructive)")
    loose = list(iter_loose_movie_files(root))
    _v(f"Found {len(loose)} loose movie file(s)")
    if not loose:
        _bullet("No loose movie files found.")
        return
    processed_dir = root / "Processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    _v(f"Processed dir: {processed_dir}")
    copied = pattern_misses = skipped = posters = subs = srt_fixed = remuxed_count = 0
    need_subs: list[tuple[Path, int | None]] = []
    for i, fp in enumerate(loose):
        _v(f"[{i+1}/{len(loose)}] {fp.name}")
        set_window_title(f"Process: {fp.name}")
        orig_stem = fp.stem
        parsed = parse_loose_movie_stem(orig_stem)
        if parsed:
            title, year = parsed
            _vv(f"  parsed: {title} ({year})")
        else:
            pd = parse_loose_release_year_stem(orig_stem)
            if pd:
                title, year = pd
                _vv(f"  release-year parse: {title} ({year})")
            else:
                guessed = guess_loose_title_without_year(orig_stem)
                if not guessed:
                    pattern_misses += 1
                    _bullet(f"  ? {fp.name} \u2014 unrecognized")
                    continue
                title, year = guessed, ""
                _vv(f"  guessed: {title}")
        tm_mid = None
        tr = tmdb_resolve_movie_title_year_and_id(tmdb_k, title, year or None)
        if tr:
            title, year, tm_mid = tr
            _vv(f"  TMDB: {title} ({year}) id={tm_mid}")
        elif year:
            cx = cinemeta_lookup_canonical_title(title, year)
            title = cx if cx else title
            _vv(f"  Cinemeta: {title} ({year})")
        else:
            pattern_misses += 1
            _bullet(f"  ? {fp.name} \u2014 no TMDB match")
            continue
        folder_name = f"{year} - {title}"
        dest_dir = processed_dir / folder_name
        dest_video = dest_dir / f"{title}{fp.suffix.lower()}"
        dest_srt = dest_dir / f"{title}.srt"
        _vv(f"  dest_folder={folder_name}")
        if dest_video.exists():
            _bullet(f"  = {folder_name} \u2014 exists")
            _vv(f"  video exists: {dest_video.name}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(fp, dest_video)
                copied += 1
                _bullet(f"  + {folder_name}")
                _vv(f"  copied: {fp.name} ({fp.stat().st_size / 1024 / 1024:.1f} MB)")
            except OSError as e:
                skipped += 1
                _bullet(f"  ! {fp.name} \u2014 copy error: {e}")
                continue
        # Download poster
        poster_path = dest_dir / "poster.jpg"
        if not poster_path.exists():
            if fetch_movie_poster_open_sources(poster_path, title, year, tmdb_key=tmdb_k, omdb_key=omdb_k):
                posters += 1
                _vv(f"  poster downloaded")
            else:
                _vv(f"  poster download failed")
        # Track for subtitle download
        has_ro = _has_romanian_subtitle_sidecar(dest_video)
        _vv(f"  has_romanian_subtitle={has_ro}, dest_srt_exists={dest_srt.exists()}")
        if auto_fetch_ro_subtitles and not dest_srt.exists() and not has_ro:
            need_subs.append((dest_video, tm_mid))
    # Batch subtitle download
    if auto_fetch_ro_subtitles and need_subs:
        _bullet(f"Fetching subtitles for {len(need_subs)} movie(s)...")
        _v(f"Subtitle download phase: {len(need_subs)} need subs")
        pre_subs = subs
        # Phase 0: Hash search on source copy (same hash as original)
        _v(f"Phase 0: Hash-based search on video file")
        for p, _ in need_subs:
            srt_path = p.with_suffix(".srt")
            if srt_path.exists():
                continue
            if os_api_key and p.is_file():
                _vv(f"  trying hash for {p.name}")
                if opensubtitles_search_and_download_by_hash(p, srt_path, api_key=os_api_key, lang="ro"):
                    subs += 1
                    _vv(f"  hash download OK")
                    if fix_srt_file(srt_path):
                        srt_fixed += 1
                else:
                    _vv(f"  hash download failed")
        # Phase 1: OpenSubtitles API for movies with TMDB IDs
        still_needed_1 = [p for p, _ in need_subs if not p.with_suffix(".srt").exists()]
        _v(f"Phase 1: OpenSubtitles.com API via TMDB ID ({len(still_needed_1)} left)")
        for p in still_needed_1:
            tm_mid = None
            for pp, tmid in need_subs:  # re-find the tmdb id
                if pp == p: tm_mid = tmid; break
            if tm_mid and os_api_key:
                srt_path = p.with_suffix(".srt")
                _vv(f"  trying OS.com for {p.name} (TMDB id={tm_mid})")
                if not srt_path.exists() and opensubtitles_com_download_romanian_srt(os_api_key, tm_mid, srt_path):
                    subs += 1
                    _vv(f"  OS.com download OK")
                    if fix_srt_file(srt_path):
                        srt_fixed += 1
                else:
                    _vv(f"  OS.com download failed")
        # Phase 2: subliminal for remaining
        still_needed = [p for p, _ in need_subs if not p.with_suffix(".srt").exists()]
        _v(f"Phase 2: subliminal ({len(still_needed)} still needed)")
        if still_needed:
            sub_exe = resolve_subliminal_exe(subliminal_exe)
            if sub_exe:
                fps = [p for p in still_needed if p.is_file()]
                if fps:
                    com_user = (opensubtitlescom_user or os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_USER", "") or _DEFAULT_OPENSUBTITLES_COM_LOGIN_USER).strip()
                    com_pw = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_PASSWORD", "") or _DEFAULT_OPENSUBTITLES_COM_LOGIN_PASSWORD).strip()
                    cmd: list[str] = [sub_exe]
                    if com_user and com_pw:
                        cmd.extend(["--opensubtitlescom", com_user, com_pw])
                    cmd.extend(["download", "-l", "ro"])
                    if tmdb_k:
                        cmd.extend(["-rr", "tmdb"])
                    cmd.extend(["-p", "opensubtitlescom", "-pp", "podnapisi"])
                    cmd.extend(["-s"] + [str(p) for p in fps])
                    _log_cmd(cmd)
                    _vv(f"  running subliminal for {len(fps)} file(s)...")
                    try:
                        proc = subprocess.run(cmd, timeout=3*3600, capture_output=True)
                        log = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
                        _vv(f"  subliminal stdout ({len(log)} chars)")
                        if log:
                            for line in log.splitlines():
                                if "Downloaded" in line or "Skipped" in line or "Error" in line.lower() or "WARNING" in line:
                                    _indent(line)
                                elif "[E]" in line:
                                    _indent(line)
                    except subprocess.TimeoutExpired:
                        _bullet(f"  ! subliminal timed out")
                # Count newly downloaded subs
                for p in fps:
                    srt_path = p.with_suffix(".srt")
                    if srt_path.exists() and srt_path.stat().st_size > 50:
                        subs += 1
                        _vv(f"  subliminal downloaded: {srt_path.name}")
                        if fix_srt_file(srt_path):
                            srt_fixed += 1
                    else:
                        _vv(f"  subliminal no sub for: {p.name}")
        # Phase 3: Romanian sites (pass TMDB ID for titrari.ro)
        _v(f"Phase 3: Romanian subtitle sites ({len([1 for p,_ in need_subs if not p.with_suffix('.srt').exists()])} still needed)")
        for p, tm_mid in need_subs:
            srt_path = p.with_suffix(".srt")
            if srt_path.exists():
                continue
            query = p.stem
            _vv(f"  trying Romanian sites for: {query}")
            if _download_from_romanian_subtitles_better(query, srt_path, tmdb_api_key=tmdb_k, tmdb_id=tm_mid):
                subs += 1
                _vv(f"  Romanian site download OK")
                if fix_srt_file(srt_path):
                    srt_fixed += 1
                _bullet(f"  ~ Romanian: {srt_path.name}")
            else:
                _vv(f"  Romanian sites failed")
        if subs > pre_subs:
            _bullet(f"  downloaded {subs - pre_subs} subtitle(s)")
    # Remux: embed .srt into MKV where possible
    remuxed_count = 0
    if mkvmerge_exe:
        _v(f"Remux phase: scanning for video files in Processed/")
        remuxable = sorted(processed_dir.rglob("*.[mM][kK][vv]")) + sorted(processed_dir.rglob("*.[mM][pP]4"))
        _v(f"  Found {len(remuxable)} video file(s) to check")
        for vp in remuxable:
            srtp = vp.with_suffix(".srt")
            _vv(f"  checking: {vp.name} (srt_exists={srtp.is_file()})")
            if not srtp.is_file():
                _vv(f"    no sidecar SRT, skipping")
                continue
            if _has_romanian_subtitle(vp):
                _vv(f"    already has embedded RO sub, skipping")
                continue
            if remux_series_video(vp, srtp, mkvmerge_exe=mkvmerge_exe):
                remuxed_count += 1
                _bullet(f"  ~ remuxed: {vp.parent.name}/{vp.name}")
        if remuxed_count:
            _bullet(f"Remuxed {remuxed_count} file(s)")
        else:
            _v("  No files remuxed")
    _timer_elapsed(t0, "organize_loose_to_processed")
    _heading("Summary")
    _bullet(f"Copied: {copied}, unrecognized: {pattern_misses}, skipped: {skipped}")
    _bullet(f"Posters: {posters}, subtitles: {subs}, SRT fixed: {srt_fixed}, remuxed: {remuxed_count}")

# ===========================================================================
# Movies: Steps 1-3 (rename folders, rename files, clean)
# ===========================================================================

def rename_folders(root: Path) -> None:
    _v(f"rename_folders: root={root}")
    folders = []
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames: folders.append(Path(dirpath) / d)
    folders.sort(key=lambda p: len(p.parts), reverse=True)
    _v(f"  Found {len(folders)} total folders")
    renamed = 0
    for folder in folders:
        set_window_title(f"Rename folder: {folder.name}")
        if not folder.exists(): continue
        m = RE_MOVIE_FOLDER.match(folder.name)
        if not m:
            _vv(f"  skip {folder.name} (no match)")
            continue
        new_path = folder.parent / f"{m.group(2)} - {m.group(1)}"
        if new_path.exists():
            _vv(f"  skip {folder.name} -> {new_path.name} (exists)")
            continue
        _vv(f"  rename: {folder.name} -> {new_path.name}")
        try:
            folder.rename(new_path); renamed += 1
            _vv(f"    OK")
        except OSError:
            # Fallback: try shell mv (WSL /mnt/ permission workaround)
            import subprocess as _sp
            try:
                _sp.run(["mv", str(folder), str(new_path)], check=True, capture_output=True)
                renamed += 1
                _vv(f"    OK (shell mv)")
            except Exception as e:
                _vv(f"    FAILED: {e}")
                pass
    _bullet(f"Renamed {renamed} folder(s)")

def rename_media_files(root: Path) -> None:
    _v(f"rename_media_files: root={root}")
    renamed = already_ok = errors = 0
    for dirpath, _, filenames in os.walk(root):
        dp = Path(dirpath)
        m = RE_YEAR_NAME_FOLDER.match(dp.name)
        if not m:
            _vv(f"  skip dir {dp.name} (no year-name match)")
            continue
        if not os.access(dirpath, os.R_OK):
            errors += 1
            _vv(f"  no access: {dirpath}")
            continue
        target_stem = m.group(2)
        _vv(f"  dir: {dp.name} -> target_stem={target_stem}")
        for fname in filenames:
            set_window_title(f"Rename media: {fname}")
            fp = dp / fname
            ext = fp.suffix
            if ext.lower() not in MEDIA_EXTENSIONS:
                _vv(f"    skip {fname} (not media)")
                continue
            target_name = f"{target_stem}{ext}"
            if fp.name == target_name:
                already_ok += 1
                _vv(f"    {fname} already OK")
                continue
            target_path = dp / target_name
            if target_path.exists():
                _vv(f"    {fname} -> {target_name} exists, skipping")
                continue
            try:
                fp.rename(target_path)
                renamed += 1
                _vv(f"    {fname} -> {target_name}")
            except OSError as e:
                errors += 1
                _vv(f"    error renaming {fname}: {e}")
    _bullet(f"Renamed: {renamed}, already ok: {already_ok}{', errors: ' + str(errors) if errors else ''}")

def clean_files(root: Path) -> None:
    removed = 0
    for dirpath, _, filenames in os.walk(root):
        dp = Path(dirpath)
        for fname in filenames:
            set_window_title(f"Clean: {fname}")
            fp = dp / fname
            if is_own_file(fp, root): continue
            sl = fp.stem.lower()
            el = fp.suffix.lower()
            if sl in JUNK_STEMS or (el in IMAGE_EXTENSIONS and fname.lower() != "poster.jpg" and not sl.endswith("-poster")):
                try: fp.unlink(); removed += 1
                except OSError: pass
    _bullet(f"Removed {removed} file(s)")

FOLDER_NAME_RE = re.compile(r"^(?:\((\d{4})\)\s*)?(.+)$|^(\d{4})\s*[-–]\s*(.+)$")

def _folder_title_year(folder: Path) -> tuple[str, str] | None:
    name = folder.name.strip()
    m = FOLDER_NAME_RE.match(name)
    if m:
        if m.group(1) and m.group(2): return m.group(2).strip(), m.group(1)
        if m.group(3) and m.group(4): return m.group(4).strip(), m.group(3)
    return None

def convert_posters(root: Path, *, tmdb_api_key: str = "", omdb_api_key: str = "") -> None:
    tmdb_k = (tmdb_api_key or os.environ.get("PROCESS_MOVIES_TMDB_API_KEY", "") or _DEFAULT_TMDB_API_KEY).strip()
    omdb_k = (omdb_api_key or os.environ.get("PROCESS_MOVIES_OMDB_API_KEY", "") or _DEFAULT_OMDB_API_KEY).strip()
    convert_exe = shutil.which("magick") or shutil.which("convert")
    downloaded = 0; converted = 0; skipped = 0
    for folder in sorted(root.iterdir()):
        if not folder.is_dir(): continue
        ty = _folder_title_year(folder)
        if not ty: continue
        title, year = ty
        poster_jpg = folder / "poster.jpg"
        # Rename existing *-poster.jpg → poster.jpg (TMM downloads this format)
        if not poster_jpg.exists():
            for f in folder.iterdir():
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS and f.stem.endswith("-poster"):
                    try:
                        f.rename(poster_jpg); skipped += 1; break
                    except OSError:
                        pass
        if poster_jpg.exists(): continue
        existing = None
        for ext in IMAGE_EXTENSIONS:
            fp = folder / f"poster{ext}"
            if fp.exists(): existing = fp; break
        if existing and existing.suffix.lower() == ".jpg":
            continue
        if tmdb_k or omdb_k:
            if fetch_movie_poster_open_sources(poster_jpg, title, year, tmdb_key=tmdb_k, omdb_key=omdb_k):
                downloaded += 1; _indent(f"{title} ({year}): poster downloaded")
                continue
        if existing and convert_exe:
            jpg = existing.with_suffix(".jpg")
            r = subprocess.run([convert_exe, str(existing), "-quality", "90", str(jpg)], capture_output=True, timeout=60)
            if r.returncode == 0:
                try: existing.unlink(); converted += 1; _indent(f"{existing.name} -> poster.jpg")
                except OSError: pass
            else: skipped += 1
        else: skipped += 1
    _bullet(f"Posters: {downloaded} downloaded, {converted} converted, {skipped} skipped/missing")

# ===========================================================================
# Movies: Step 5 - Fix subtitles (full cleaning)
# ===========================================================================

def _read_text(filepath: str) -> str:
    raw = Path(filepath).read_bytes()
    if raw[:3] == b"\xef\xbb\xbf": return raw[3:].decode("utf-8")
    if raw[:2] == b"\xff\xfe": return raw[2:].decode("utf-16-le")
    if raw[:2] == b"\xfe\xff": return raw[2:].decode("utf-16-be")
    try: return raw.decode("utf-8")
    except UnicodeDecodeError: pass
    best_text, best_score = None, float("inf")
    for enc in CODEPAGE_CANDIDATES:
        try: text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError): continue
        score = text.count("\uFFFD") * 1000 + len(RE_MOJIBAKE.findall(text)) * 10 + sum(1 for ch in text if ord(ch) < 32 and ch not in ("\r","\n","\t")) - len(RE_RO_DIACRITICS.findall(text))
        if score < best_score: best_score, best_text = score, text
    return best_text if best_text is not None else raw.decode("latin-1")

def _clean_subtitle_text(text: str) -> str:
    text = RE_ASS_HARDSPACE.sub(" ", text)
    text = RE_ASS_NEWLINE.sub("\n", text)
    text = RE_ASS_DRAWING.sub("", text)
    text = RE_ASS_OVERRIDES.sub("", text)
    text = RE_HTML_TAGS.sub("", text)
    text = RE_LEFTOVER_BRACES.sub("", text)
    text = RE_LEFTOVER_ANGLES.sub("", text)
    text = RE_INVISIBLE.sub("", text)
    text = RE_GARBAGE.sub("", text)
    text = text.translate(_PUNCT_TRANS)
    text = RE_MUSIC_NOTES.sub("", text)
    text = text.translate(_DIAC_TRANS)
    lines = [RE_SRT_MULTI_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\r\n".join(lines)
    text = RE_EMPTY_CUE.sub("", text)
    text = RE_EXCESS_BLANKS.sub("\r\n\r\n", text)
    return text.strip() + "\r\n"

def _fix_subtitle(path: Path) -> None:
    try:
        text = _read_text(str(path))
    except OSError:
        return
    fixed = _clean_subtitle_text(text)
    tmp = path.with_name(path.stem + ".tmpfix" + path.suffix)
    if tmp.exists():
        tmp = path.with_name(path.stem + ".tmpfix." + uuid.uuid4().hex + path.suffix)
    try:
        tmp.write_bytes(codecs.BOM_UTF8 + fixed.encode("utf-8"))
    except OSError:
        tmp.unlink(missing_ok=True)
        return
    _safe_replace_file(tmp, path)

def fix_subtitles(root: Path) -> None:
    subs = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".srt", ".sub") and ".fixed." not in p.name and ".bak" not in p.suffixes and ".tmpfix" not in p.name)
    if not subs: _bullet("No .srt/.sub files found."); return
    _bullet(f"Checking {len(subs)} subtitle file(s)...")
    for f in subs: set_window_title(f"Fix sub: {f.name}"); _fix_subtitle(f)

# ===========================================================================
# Movies: Subliminal download
# ===========================================================================

def _parse_subliminal_log(text: str) -> tuple[int | None, int | None]:
    vc = re.search(r"(\d+)\s+videos?\s+collected", text, re.IGNORECASE)
    sd = re.search(r"Downloaded\s+(\d+)\s+subtitle", text, re.IGNORECASE)
    return (int(vc.group(1)) if vc else None, int(sd.group(1)) if sd else None)

def fetch_subtitles_subliminal(root: Path, *, languages: list[str], subliminal_exe: str = "", opensubtitlescom_user: str = "", force: bool = False, paths: list[Path] | None = None) -> None:
    exe = resolve_subliminal_exe(subliminal_exe)
    if not exe: _bullet("Subliminal not installed."); return
    com_user = (opensubtitlescom_user or os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_USER", "") or _DEFAULT_OPENSUBTITLES_COM_LOGIN_USER).strip()
    com_pw = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_PASSWORD", "") or _DEFAULT_OPENSUBTITLES_COM_LOGIN_PASSWORD).strip()
    org_user = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_ORG_USER", "") or _DEFAULT_OPENSUBTITLES_ORG_USER).strip()
    org_pw = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_ORG_PASSWORD", "") or _DEFAULT_OPENSUBTITLES_ORG_PASSWORD).strip()
    cmd: list[str] = [exe]
    if com_user and com_pw: cmd.extend(["--opensubtitlescom", com_user, com_pw])
    if org_user and org_pw: cmd.extend(["--opensubtitles", org_user, org_pw])
    cmd.append("download")
    for lang in languages: cmd.extend(["-l", lang])
    tmdb_k = (os.environ.get("PROCESS_MOVIES_TMDB_API_KEY", "") or _DEFAULT_TMDB_API_KEY).strip()
    if tmdb_k: cmd.extend(["-rr", "tmdb"])
    cmd.extend(["-p", "opensubtitlescom", "-pp", "podnapisi"])
    if org_user and org_pw: cmd.extend(["-pp", "opensubtitles"])
    cmd.append("-s")
    if paths:
        ps = [str(p.resolve()) for p in paths if p.is_file()]
        if not ps: return
        fps = [p for p in ps if not _has_romanian_subtitle(Path(p))]
        if not fps: _bullet("All videos already have embedded Romanian subs."); return
        cmd.extend(fps)
    else: cmd.append(str(root.resolve()))
    if force: cmd.append("-f")
    try:
        proc = subprocess.run(cmd, timeout=3*3600, env={**os.environ} | ({"TMDB_API_KEY": tmdb_k} if tmdb_k else {}), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired: return
    log = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    vc, dc = _parse_subliminal_log(log)
    if dc is not None: _bullet(f"Subliminal: checked {vc or '?'} video(s), downloaded {dc} subtitle(s).")
    elif log and len(log) < 800:
        for line in log.splitlines():
            if line.strip(): _indent(line)

# ===========================================================================
# Movies: Step 6 - MKV remux
# ===========================================================================

def _mkv_select_romanian_subtitle_ids(tracks: list) -> list[int]:
    return sorted(int(t["id"]) for t in tracks if t.get("type") == "subtitles" and _mkv_is_romanian_subtitle(t.get("properties") or {}))

def _mkv_select_audio_ids(tracks: list) -> tuple[list[int], str]:
    audio = [t for t in tracks if t.get("type") == "audio"]
    if not audio: return [], "no audio"
    if len(audio) == 1:
        lang = _mkv_track_language(audio[0].get("properties") or {})
        return [int(audio[0]["id"])], f"single id={audio[0]['id']} lang={lang or 'unknown'}"
    eng = [int(t["id"]) for t in audio if _mkv_is_english_audio(t.get("properties") or {})]
    if eng: return sorted(eng), f"{len(audio)} tracks, keeping English ids={eng}"
    return [], f"{len(audio)} tracks, no English"

def _mkv_needs_remux(info: dict, keep_audio_ids: list[int], sidecar_srt: Path | None) -> bool:
    tracks = info.get("tracks") or []
    if sorted(int(t["id"]) for t in tracks if t.get("type") == "audio") != sorted(keep_audio_ids): return True
    if any(t.get("type") == "buttons" for t in tracks): return True
    if info.get("attachments"): return True
    ro_ids = _mkv_select_romanian_subtitle_ids(tracks)
    sub_ids = sorted(int(t["id"]) for t in tracks if t.get("type") == "subtitles")
    if sidecar_srt is not None: return not sub_ids or set(sub_ids) != set(ro_ids) or len(ro_ids) != 1
    return set(sub_ids) != set(ro_ids)

def _mkv_remux_strip(mkv_path: Path, audio_ids: list[int], sidecar_srt: Path | None, romanian_sub_ids: list[int], *, mkvmerge_exe: str, output_path: Path | None = None) -> None:
    """Remux mkv_path writing to output_path (or in-place if output_path is None).

    When output_path is set, original files are never touched — the remuxed
    file lands at output_path and anything temporary lives beside it.
    """
    _v(f"MKV remux strip: {mkv_path.name} -> {output_path or 'in-place'}")
    is_mkv = mkv_path.suffix.lower() == ".mkv"
    out_suffix = ".mkv"
    inplace = output_path is None
    if inplace:
        out_tmp = mkv_path.with_name(mkv_path.stem + ".mkvstrip.tmp" + out_suffix)
        if out_tmp.exists(): out_tmp = mkv_path.with_name(mkv_path.stem + ".mkvstrip.tmp." + uuid.uuid4().hex + out_suffix)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out_tmp = output_path.with_name(output_path.stem + ".tmp" + out_suffix)
        if out_tmp.exists(): out_tmp = output_path.with_name(output_path.stem + ".tmp." + uuid.uuid4().hex + out_suffix)
    if is_mkv:
        a_csv = ",".join(str(i) for i in sorted(audio_ids))
        cmd = [mkvmerge_exe, "-o", str(out_tmp), "-B", "-M", "-a", a_csv]
        if sidecar_srt is not None: cmd.extend(["-S", str(mkv_path), "--language", f"0:{MKV_SIDECAR_SRT_LANGUAGE}", str(sidecar_srt)])
        elif romanian_sub_ids: cmd.extend(["--subtitle-tracks", ",".join(str(i) for i in sorted(romanian_sub_ids)), str(mkv_path)])
        else: cmd.extend(["-S", str(mkv_path)])
    else:
        cmd = [mkvmerge_exe, "-o", str(out_tmp)]
        if sidecar_srt is not None: cmd.extend(["-S", str(mkv_path), "--language", f"0:{MKV_SIDECAR_SRT_LANGUAGE}", str(sidecar_srt)])
        else: cmd.append(str(mkv_path))
    _log_cmd(cmd)
    _vv("  running mkvmerge...")
    proc = subprocess.run(cmd, capture_output=True, timeout=3600)
    if proc.returncode != 0:
        out_tmp.unlink(missing_ok=True)
        raise RuntimeError((proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip())
    if inplace:
        target = mkv_path if is_mkv else mkv_path.with_suffix(".mkv")
        bak = mkv_path.with_name(mkv_path.stem + ".mkvstrip.bak" + mkv_path.suffix)
        bak.unlink(missing_ok=True)
        try:
            mkv_path.rename(bak)
            try: out_tmp.rename(target); bak.unlink(missing_ok=True)
            except Exception:
                if bak.exists() and not target.exists(): bak.rename(mkv_path)
                out_tmp.unlink(missing_ok=True); raise
        except Exception:
            out_tmp.unlink(missing_ok=True); raise
    else:
        out_tmp.rename(output_path)

def strip_mkvs(root: Path, log_path: Path, *, mkvmerge_dir: str = "") -> None:
    t0 = _timer_start()
    _v(f"Step 6 - MKV remux: scanning {root}")
    exe = resolve_mkvmerge_exe(mkvmerge_dir)
    if not exe: _bullet("mkvmerge not found, skipping Step 6."); _mkv_strip_log(log_path, "SKIP: mkvmerge not found"); return
    videos = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in MOVIE_EXTENSIONS and ".mkvstrip.tmp" not in p.name and ".mkvstrip.bak" not in p.name)
    _v(f"Found {len(videos)} video file(s)")
    if not videos: _bullet("No videos found."); _mkv_strip_log(log_path, "No videos"); return
    processed_dir = root / "Processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    ok = skipped = errors = 0
    for i, path in enumerate(videos):
        _v(f"[{i+1}/{len(videos)}] Processing: {path.name}")
        try: rel = path.relative_to(root)
        except ValueError: rel = path
        set_window_title(f"Strip MKV: {rel}")
        # Skip if already processed — output exists in Processed/
        out_path = (processed_dir / rel).with_suffix(".mkv")
        if out_path.exists():
            skipped += 1
            _mkv_strip_log(log_path, f"SKIP {rel}: already in Processed")
            continue
        is_mkv = path.suffix.lower() == ".mkv"
        try: info = _mkvmerge_identify(path, exe=exe)
        except Exception as exc: errors += 1; _mkv_strip_log(log_path, f"ERROR identify {rel}: {exc}"); continue
        tracks = info.get("tracks") or []
        if not any(t.get("type") == "video" for t in tracks): skipped += 1; _mkv_strip_log(log_path, f"SKIP {rel}: no video"); continue
        sidecar = _mkv_sidecar_srt(path)
        if not is_mkv:
            if sidecar is None: skipped += 1; _mkv_strip_log(log_path, f"SKIP {rel}: no sidecar .srt"); continue
            if _has_romanian_subtitle(path): skipped += 1; _mkv_strip_log(log_path, f"SKIP {rel}: already has RO"); continue
            try: _mkv_remux_strip(path, [], sidecar, [], mkvmerge_exe=exe, output_path=out_path); ok += 1; _mkv_strip_log(log_path, f"OK {rel}: remuxed with {sidecar.name} -> Processed")
            except Exception as exc: errors += 1; _mkv_strip_log(log_path, f"ERROR remux {rel}: {exc}")
            continue
        keep_audio, audio_note = _mkv_select_audio_ids(tracks)
        if not keep_audio: skipped += 1; _mkv_strip_log(log_path, f"SKIP {rel}: {audio_note}"); continue
        ro_sub_ids = _mkv_select_romanian_subtitle_ids(tracks)
        if not _mkv_needs_remux(info, keep_audio, sidecar): skipped += 1; _mkv_strip_log(log_path, f"SKIP {rel}: already correct ({audio_note})"); continue
        try: _mkv_remux_strip(path, keep_audio, sidecar, ro_sub_ids, mkvmerge_exe=exe, output_path=out_path); ok += 1; _mkv_strip_log(log_path, f"OK {rel}: {audio_note} -> Processed")
        except Exception as exc: errors += 1; _mkv_strip_log(log_path, f"ERROR remux {rel}: {exc}")
    _bullet(f"MKV: {ok} remuxed to Processed/, {skipped} skipped, {errors} error(s)")

# ===========================================================================
# Dependencies
# ===========================================================================

def _dep_mkvmerge(mkvmerge_dir_cli: str = "") -> tuple[bool, str]:
    exe = resolve_mkvmerge_exe(mkvmerge_dir_cli)
    if not exe: return False, "not found"
    try:
        v = subprocess.run([exe, "--version"], capture_output=True, timeout=10)
        line = (v.stdout or v.stderr or b"").decode("utf-8", errors="replace").splitlines()[0] if v.returncode == 0 else exe
        return True, line.strip() or exe
    except (OSError, subprocess.TimeoutExpired, IndexError): return True, exe

def _dep_tmm(tmm_dir_cli: str = "") -> tuple[bool, str]:
    exe = resolve_tmm_exe(tmm_dir_cli)
    return (True, str(exe)) if exe else (False, "not found")

def _dep_tmm_cmd(tmm_dir_cli: str = "") -> tuple[bool, str]:
    exe = resolve_tmm_cmd_exe(tmm_dir_cli)
    return (True, str(exe)) if exe else (False, "not found")

def _dep_subliminal(subliminal_cli: str = "") -> tuple[bool, str]:
    exe = resolve_subliminal_exe(subliminal_cli)
    return (True, exe) if exe else (False, "not in PATH")

def _dep_ffprobe() -> tuple[bool, str]:
    exe = shutil.which("ffprobe")
    if exe:
        try:
            v = subprocess.run([exe, "-version"], capture_output=True, timeout=10)
            line = (v.stdout or v.stderr or b"").decode("utf-8", errors="replace").splitlines()[0] if v.returncode == 0 else exe
            return True, line.strip()[:80] or exe
        except (OSError, subprocess.TimeoutExpired): return True, exe
    return False, "not found (apt install ffmpeg)"

def _dep_convert() -> tuple[bool, str]:
    for exe_name in ("magick", "convert"):
        exe = shutil.which(exe_name)
        if exe:
            try:
                v = subprocess.run([exe, "--version"], capture_output=True, timeout=10)
                line = (v.stdout or v.stderr or b"").decode("utf-8", errors="replace").splitlines()[0] if v.returncode == 0 else exe
                return True, line.strip()[:80] or exe
            except (OSError, subprocess.TimeoutExpired): return True, exe
    return False, "not found (apt install imagemagick)"

def dependency_rows(mkvmerge_dir_cli: str = "", tmm_dir_cli: str = "", subliminal_cli: str = "") -> tuple[list[tuple[str, bool, str]], bool]:
    rows: list[tuple[str, bool, str]] = []
    ok_m, d_m = _dep_mkvmerge(mkvmerge_dir_cli); rows.append(("mkvmerge (required)", ok_m, d_m))
    ok_ff, d_ff = _dep_ffprobe(); rows.append(("ffprobe (required)", ok_ff, d_ff))
    ok_t, d_t = _dep_tmm(tmm_dir_cli); rows.append(("TMM GUI", ok_t, d_t))
    ok_tc, d_tc = _dep_tmm_cmd(tmm_dir_cli); rows.append(("TMM CLI", ok_tc, d_tc))
    ok_sub, d_sub = _dep_subliminal(subliminal_cli); rows.append(("subliminal", ok_sub, d_sub))
    ok_cv, d_cv = _dep_convert(); rows.append(("ImageMagick", ok_cv, d_cv))
    return rows, ok_m

def print_dependency_report(mkvmerge_dir_cli: str = "", tmm_dir_cli: str = "", subliminal_cli: str = "") -> tuple[list[tuple[str, bool, str]], bool]:
    rows, ok_m = dependency_rows(mkvmerge_dir_cli, tmm_dir_cli, subliminal_cli)
    _bullet(f"Python {sys.version.split()[0]}")
    for label, ok, detail in rows: _bullet(f"{'OK' if ok else 'NO'} {label}: {detail}")
    _bullet(f"mkvmerge={'OK' if ok_m else 'MISSING'}")
    return rows, ok_m

def try_install_mkvtoolnix() -> tuple[bool, str]:
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    def run_cmd(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if shutil.which("apt-get"):
        for updater in (["sudo", "apt-get", "update", "-qq"], ["sudo", "apt-get", "install", "-y", "mkvtoolnix"]):
            r = run_cmd(updater, timeout=900)
            if r.returncode != 0: return False, "apt failed"
        return True, "apt OK"
    if shutil.which("dnf"):
        r = run_cmd(["sudo", "dnf", "install", "-y", "mkvtoolnix"], timeout=900)
        return (True, "dnf OK") if r.returncode == 0 else (False, "dnf failed")
    if shutil.which("pacman"):
        r = run_cmd(["sudo", "pacman", "-S", "--noconfirm", "mkvtoolnix"], timeout=900)
        return (True, "pacman OK") if r.returncode == 0 else (False, "pacman failed")
    if shutil.which("brew"):
        r = run_cmd(["brew", "install", "mkvtoolnix"], timeout=900)
        return (True, "brew OK") if r.returncode == 0 else (False, "brew failed")
    return False, "unsupported package manager (supported: apt/dnf/pacman/brew)"

# ===========================================================================
# Movies: run_pipeline + run_single_step + interactive_menu
# ===========================================================================

def run_pipeline(root: Path, *, mkvmerge_dir: str = "", tmm_dir: str = "", tmm_run_movies: bool = False, tmm_run_tvshows: bool = False, organize_loose: bool = False, tmdb_api_key: str = "", omdb_api_key: str = "", organize_auto_fetch_subs: bool = True, fetch_subs: bool = False, subs_lang: str = "ro", subs_force: bool = False, subliminal_exe: str = "", opensubtitlescom_user: str = "", skip_rename: bool = False, skip_rename_files: bool = False, skip_clean: bool = False, skip_posters: bool = False, skip_subtitles: bool = False, skip_mkv_strip: bool = False, mkv_strip_log: str = "") -> None:
    t0 = _timer_start()
    _v(f"run_pipeline: root={root}")
    _v(f"  flags: tmdb={'set' if tmdb_api_key else 'no'} omdb={'set' if omdb_api_key else 'no'}")
    _v(f"  skip: rename={skip_rename} files={skip_rename_files} clean={skip_clean} posters={skip_posters} subs={skip_subtitles} mkv={skip_mkv_strip}")
    _bullet(f"Library: {root}")
    tmm_ran = False
    # Phase 0: TMM headless — organizes files, creates folders, downloads posters
    if tmm_run_movies and not skip_rename:
        tmm_exe = resolve_tmm_cmd_exe(tmm_dir)
        if tmm_exe:
            try:
                _heading("Step 0 - TMM headless (organize + scrape + posters)")
                _v("Running TMM headless for movies...")
                run_tmm_cli_sync(tmm_dir, movies=True, tvshows=False)
                tmm_ran = True
            except RuntimeError as e: _indent(f"TMM skipped: {e}")
    if organize_loose:
        set_window_title("Organize loose"); _v("Step 0 - Organize loose files"); organize_loose_videos_in_root(root, tmdb_api_key=tmdb_api_key, omdb_api_key=omdb_api_key, auto_fetch_ro_subtitles=organize_auto_fetch_subs, subliminal_exe=subliminal_exe, opensubtitlescom_user=opensubtitlescom_user)
    if not skip_rename: set_window_title("Rename folders"); _heading("Step 1 - Rename folders"); _v("Starting rename_folders"); rename_folders(root); _timer_elapsed(t0, "step1")
    if not skip_rename_files: set_window_title("Rename media"); _heading("Step 2 - Rename media"); _v("Starting rename_media_files"); rename_media_files(root); _timer_elapsed(t0, "step2")
    if not skip_clean: set_window_title("Clean junk"); _heading("Step 3 - Clean junk"); _v("Starting clean_files"); clean_files(root); _timer_elapsed(t0, "step3")
    if not skip_posters: set_window_title("Posters"); _heading("Step 4 - Posters"); _v("Starting convert_posters"); convert_posters(root, tmdb_api_key=tmdb_api_key, omdb_api_key=omdb_api_key); _timer_elapsed(t0, "step4")
    if fetch_subs:
        set_window_title("Download subs")
        _heading("Step 4b - Download subs")
        langs = [x.strip() for x in subs_lang.replace(",", " ").split() if x.strip()]
        _v(f"Download subs: lang={langs}")
        fetch_subtitles_subliminal(root, languages=langs, subliminal_exe=subliminal_exe, opensubtitlescom_user=opensubtitlescom_user, force=subs_force)
    if not skip_subtitles: set_window_title("Fix subtitles"); _heading("Step 5 - Fix subtitles"); _v("Starting fix_subtitles"); fix_subtitles(root); _timer_elapsed(t0, "step5")
    if not skip_mkv_strip:
        set_window_title("MKV remux")
        _heading("Step 6 - MKV remux")
        log_mkv = sanitize_path(mkv_strip_log) if mkv_strip_log else (root / "mkv_strip.log")
        _v(f"Starting strip_mkvs (log={log_mkv})")
        strip_mkvs(root, log_mkv, mkvmerge_dir=mkvmerge_dir)
        _timer_elapsed(t0, "step6")
    _timer_elapsed(t0, "run_pipeline total")

def run_single_step(step: int, root: Path, *, mkv_strip_log: str, mkvmerge_dir: str = "", tmm_dir: str = "", tmm_run_movies: bool = False, tmm_run_tvshows: bool = False, organize_loose: bool = False, tmdb_api_key: str = "", omdb_api_key: str = "", organize_auto_fetch_subs: bool = True, fetch_subs: bool = False, subs_lang: str = "ro", subs_force: bool = False, subliminal_exe: str = "", opensubtitlescom_user: str = "") -> None:
    if step < 1 or step > 6: return
    run_pipeline(root, mkvmerge_dir=mkvmerge_dir, tmm_dir=tmm_dir, tmm_run_movies=tmm_run_movies and step == 1, tmm_run_tvshows=tmm_run_tvshows and step == 1, organize_loose=organize_loose and step == 1, tmdb_api_key=tmdb_api_key, omdb_api_key=omdb_api_key, organize_auto_fetch_subs=organize_auto_fetch_subs, fetch_subs=fetch_subs and step in (5, 6), subs_lang=subs_lang, subs_force=subs_force, subliminal_exe=subliminal_exe, opensubtitlescom_user=opensubtitlescom_user, skip_rename=step != 1, skip_rename_files=step != 2, skip_clean=step != 3, skip_posters=step != 4, skip_subtitles=step != 5, skip_mkv_strip=step != 6, mkv_strip_log=mkv_strip_log)

def _status_line(mkvmerge_dir: str, tmm_dir: str, subliminal_exe: str) -> str:
    parts = []
    ok_m, d_m = _dep_mkvmerge(mkvmerge_dir)
    parts.append(f"mkvmerge={'OK' if ok_m else 'NO'}")
    ok_t, d_t = _dep_tmm(tmm_dir)
    parts.append(f"TMM={'OK' if ok_t else 'NO'}")
    ok_s, d_s = _dep_subliminal(subliminal_exe)
    parts.append(f"subliminal={'OK' if ok_s else 'NO'}")
    ok_c, d_c = _dep_convert()
    parts.append(f"convert={'OK' if ok_c else 'NO'}")
    return " | ".join(parts)

def _menu_subtitles_submenu(root: Path, args: argparse.Namespace) -> None:
    while True:
        print()
        _heading("Subtitles")
        print(f"   Folder: {root}")
        print()
        print("   1) Search by hash & download (OS.com — exact match)")
        print("   2) Download subtitles (subliminal)")
        print("   3) Fix SRT encoding (auto-detect cp1250/iso-8859-2 → UTF-8)")
        print("   4) Strip Romanian diacritics (ăâîșț → aai st)")
        print("   5) Remux: strip embedded subs + mux sidecar SRT")
        print("   6) Full pipeline: hash search → fix → strip diacritics → remux")
        print("   0) Back")
        print("  " + "-" * 50)
        try: c = input("\n  Choice [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt): print(); return
        if c == "0": return
        if not root.is_dir():
            _bullet(f"ERROR: {root} not a directory"); input("  Press Enter..."); continue
        mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)

        if c == "1":
            os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
            if not os_api_key:
                _bullet("No OpenSubtitles.com API key configured.")
            else:
                videos = _find_video_files(root)
                if not videos:
                    _bullet("No video files found.")
                else:
                    ok = fail = skip = 0
                    for vp in videos:
                        srtp = vp.with_suffix(".srt")
                        if srtp.is_file():
                            skip += 1; continue
                        _v(f"  Hash search: {vp.parent.name}/{vp.name}")
                        if opensubtitles_search_and_download_by_hash(vp, srtp, api_key=os_api_key, lang=args.subs_lang):
                            ok += 1
                            _bullet(f"    Downloaded: {srtp.name}")
                        else:
                            fail += 1
                            _bullet(f"    No match by hash: {vp.name}")
                    _bullet(f"Searched by hash: {ok} downloaded, {fail} no match, {skip} already have SRT")
            input("  Press Enter...")

        elif c == "2":
            langs = [x.strip() for x in args.subs_lang.replace(",", " ").split() if x.strip()]
            fetch_subtitles_subliminal(root, languages=langs or ["ro"], subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user, force=args.subs_force)
            input("  Press Enter...")

        elif c == "3":
            pairs = _find_video_srt_pairs(root)
            if not pairs:
                _bullet("No SRT files found alongside videos.")
            else:
                ok = fail = 0
                for vp, srtp in pairs:
                    if fix_srt_file(srtp): ok += 1
                    else: fail += 1
                _bullet(f"Fixed {ok} SRT(s)" + (f", {fail} failed" if fail else ""))
            input("  Press Enter...")

        elif c == "4":
            pairs = _find_video_srt_pairs(root)
            if not pairs:
                _bullet("No SRT files found alongside videos.")
            else:
                ok = skip = fail = 0
                for vp, srtp in pairs:
                    if strip_srt_diacritics(srtp): ok += 1
                    else: fail += 1
                _bullet(f"Stripped diacritics from {ok} SRT(s)" + (f", {fail} failed" if fail else ""))
            input("  Press Enter...")

        elif c == "5":
            pairs = _find_video_srt_pairs(root)
            if not pairs:
                _bullet("No video+SRT pairs found.")
            elif not mkv_exe:
                _bullet("mkvmerge not found — can't remux.")
            else:
                ok = fail = 0
                for vp, srtp in pairs:
                    if remux_series_video(vp, srtp, mkvmerge_exe=mkv_exe, lang=args.subs_lang):
                        ok += 1; _bullet(f"  Remuxed: {vp.parent.name}/{vp.name}")
                    else: fail += 1
                _bullet(f"Remuxed {ok} file(s)" + (f", {fail} failed" if fail else ""))
            input("  Press Enter...")

        elif c == "6":
            os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
            videos = _find_video_files(root)
            if not videos:
                _bullet("No video files found.")
            elif not mkv_exe:
                _bullet("mkvmerge not found — can't remux.")
            else:
                ok = fail = no_srt = 0
                for vp in videos:
                    srtp = vp.with_suffix(".srt")
                    if not srtp.is_file():
                        _v(f"  No SRT, trying download: {vp.parent.name}/{vp.name}")
                        if os_api_key:
                            download_subtitles_by_hash_with_fallback(vp, srtp, api_key=os_api_key, lang=args.subs_lang)
                    if not srtp.is_file():
                        no_srt += 1
                        _bullet(f"  No SRT, skipping: {vp.parent.name}/{vp.name}")
                        continue
                    ok_here = 0
                    if fix_srt_file(srtp): ok_here += 1
                    if strip_srt_diacritics(srtp): ok_here += 1
                    if remux_series_video(vp, srtp, mkvmerge_exe=mkv_exe, lang=args.subs_lang):
                        ok_here += 1
                    if ok_here == 3: ok += 1
                    else: fail += 1
                parts = [f"Pipeline: {ok} OK"]
                if fail: parts.append(f"{fail} failed")
                if no_srt: parts.append(f"{no_srt} skipped (no SRT)")
                _bullet(", ".join(parts))
            input("  Press Enter...")

def _menu_tools_submenu(args: argparse.Namespace) -> None:
    while True:
        print()
        _heading("Tools")
        print("   1) Launch TMM GUI")
        print("   2) TMM headless — movies")
        print("   3) TMM headless — TV")
        print("   4) Set MKVToolNix folder")
        print("   5) Set TMM folder")
        print("   0) Back")
        print("  " + "-" * 50)
        try: c = input("\n  Choice [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt): print(); return
        if c == "0": return
        elif c == "1":
            exe = resolve_tmm_exe(args.tmm_dir)
            if exe:
                try: subprocess.Popen([str(exe)], cwd=str(exe.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                except OSError as e: _bullet(f"Error: {e}")
            else: _bullet("TMM not found")
            input("  Press Enter...")
        elif c == "2":
            try: run_tmm_cli_sync(args.tmm_dir, movies=True, tvshows=False)
            except RuntimeError as e: _bullet(f"ERROR: {e}")
            input("  Press Enter...")
        elif c == "3":
            try: run_tmm_cli_sync(args.tmm_dir, movies=False, tvshows=True)
            except RuntimeError as e: _bullet(f"ERROR: {e}")
            input("  Press Enter...")
        elif c == "4":
            cur = args.mkvmerge_dir or _coalesce_tool_dir("", "PROCESS_MOVIES_MKVMERGE_DIR", TOOL_DIR_MKVMERGE)
            raw = input(f"  MKVToolNix dir [{cur}]: ").strip()
            if raw:
                val = raw.strip().strip('"')
                args.mkvmerge_dir = val
                _CFG.setdefault("tools", {})["mkvmerge_dir"] = val
                _save_config()
                _bullet("  MKVToolNix dir saved to config.json")
        elif c == "5":
            cur = args.tmm_dir or _coalesce_tool_dir("", "PROCESS_MOVIES_TMM_DIR", TOOL_DIR_TMM)
            raw = input(f"  TMM dir [{cur}]: ").strip()
            if raw:
                val = raw.strip().strip('"')
                args.tmm_dir = val
                _CFG.setdefault("tools", {})["tmm_dir"] = val
                _save_config()
                _bullet("  TMM dir saved to config.json")

def _menu_api_keys_submenu() -> None:
    keys = [
        ("tmdb", "TMDB API key"),
        ("omdb", "OMDB API key"),
        ("opensubtitles_com_api_key", "OS.com API key"),
        ("opensubtitles_com_user", "OS.com username"),
        ("opensubtitles_com_password", "OS.com password"),
        ("opensubtitles_org_user", "OS.org username"),
        ("opensubtitles_org_password", "OS.org password"),
    ]
    while True:
        print()
        _heading("API Keys")
        for i, (kn, dn) in enumerate(keys, 1):
            v = _CFG_KEYS.get(kn, "")
            disp = v[:4] + "****" if len(v) > 4 else ("(set)" if v else "(empty)")
            print(f"   {i}) {dn:<26} {disp}")
        print("   0) Back")
        print("  " + "-" * 50)
        try: c = input("\n  Choice [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt): print(); return
        if c == "0": return
        if c.isdigit() and 1 <= int(c) <= len(keys):
            kn, dn = keys[int(c) - 1]
            _set_api_key(kn, dn)

def _menu_config_submenu(root: Path, args: argparse.Namespace) -> Path:
    while True:
        print()
        _heading("Config")
        print(f"   Root: {root}")
        print(f"   MKV:  {args.mkvmerge_dir or TOOL_DIR_MKVMERGE or '(auto)'}")
        print(f"   TMM:  {args.tmm_dir or TOOL_DIR_TMM or '(auto)'}")
        print(f"   Lang: {args.subs_lang}")
        print()
        print("   1) Change root folder")
        print("   2) Install mkvmerge")
        print("   3) Check dependencies")
        print("   4) API keys — TMDB, OMDB, OpenSubtitles")
        print("   0) Back")
        print("  " + "-" * 50)
        try: c = input("\n  Choice [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt): print(); return root
        if c == "0": return root
        elif c == "1":
            raw = input(f"  Folder [{root}]: ").strip()
            if raw:
                root = sanitize_path(raw)
                _CFG.setdefault("defaults", {})["root_dir"] = str(root)
                _save_config()
                _bullet("  Root folder saved to config.json")
        elif c == "2":
            if _dep_mkvmerge(args.mkvmerge_dir)[0]: _bullet("mkvmerge already available.")
            else: ok, msg = try_install_mkvtoolnix(); _bullet(msg)
            input("  Press Enter...")
        elif c == "3":
            print_dependency_report(args.mkvmerge_dir, args.tmm_dir, args.subliminal)
            input("  Press Enter...")
        elif c == "4":
            _menu_api_keys_submenu()

def interactive_menu(args: argparse.Namespace) -> None:
    set_window_title("Video Organizer")
    root = sanitize_path(args.root)
    mkv_log = args.mkv_strip_log
    first = True
    while True:
        if first: first = False
        else: print()
        _heading("VIDEO ORGANIZER")
        if not root.is_dir():
            _bullet(f"ERROR: {root} is not a directory")
        else:
            _bullet(f"Folder: {root}")
            _indent(_status_line(args.mkvmerge_dir, args.tmm_dir, args.subliminal))
        print()
        print("   1) Series  — full pipeline (flatten + subs + remux)")
        print("   2) Movies  — full pipeline (rename + organize + posters + subs + remux)")
        print("   3) Movies  — single step")
        print("   4) Movies  — organize loose files")
        print("   5) Subtitles — fix, strip diacritics, remux")
        print("   6) Tools   — TMM, MKVToolNix")
        print("   7) Config  — folder, deps, paths")
        print("   8) Movies  — Process to Processed/ (non-destructive)")
        print("   0) Exit")
        print("  " + "-" * 50)
        try: c = input("\n  Choice [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt): print(); return
        if c == "0": return
        elif c == "1":
            if not root.is_dir(): continue
            mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
            series_pipeline(root, mkvmerge_exe=mkv_exe, fetch_subs=args.fetch_subs, subs_lang=args.subs_lang, use_subliminal=args.use_subliminal, subliminal_exe=args.subliminal)
            input("  Press Enter...")
        elif c == "2":
            if not root.is_dir(): continue
            use_tmm = args.tmm_run_movies or bool(resolve_tmm_cmd_exe(args.tmm_dir))
            run_pipeline(root, mkvmerge_dir=args.mkvmerge_dir, tmm_dir=args.tmm_dir, tmm_run_movies=use_tmm, tmm_run_tvshows=args.tmm_run_tvshows, organize_loose=args.organize_loose, tmdb_api_key=args.tmdb_api_key, omdb_api_key=args.omdb_api_key, organize_auto_fetch_subs=not args.no_auto_fetch_subs, fetch_subs=args.fetch_subs, subs_lang=args.subs_lang, subs_force=args.subs_force, subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user, skip_rename=False, skip_rename_files=False, skip_clean=False, skip_posters=False, skip_subtitles=False, skip_mkv_strip=False, mkv_strip_log=mkv_log)
            input("  Press Enter...")
        elif c == "3":
            if not root.is_dir(): continue
            print("   1) Rename folders  2) Rename files  3) Clean  4) Posters  5) Fix subs  6) MKV")
            s = input("   Step [cancel]: ").strip()
            if not s.isdigit() or not (1 <= int(s) <= 6): continue
            st = int(s)
            run_single_step(st, root, mkv_strip_log=mkv_log, mkvmerge_dir=args.mkvmerge_dir, tmm_dir=args.tmm_dir, tmm_run_movies=args.tmm_run_movies, tmm_run_tvshows=args.tmm_run_tvshows, organize_loose=args.organize_loose, tmdb_api_key=args.tmdb_api_key, omdb_api_key=args.omdb_api_key, organize_auto_fetch_subs=not args.no_auto_fetch_subs, fetch_subs=args.fetch_subs, subs_lang=args.subs_lang, subs_force=args.subs_force, subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user)
            input("  Press Enter...")
        elif c == "4":
            if not root.is_dir(): continue
            organize_loose_videos_in_root(root, tmdb_api_key=args.tmdb_api_key, omdb_api_key=args.omdb_api_key, auto_fetch_ro_subtitles=not args.no_auto_fetch_subs, subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user)
            input("  Press Enter...")
        elif c == "5":
            _menu_subtitles_submenu(root, args)
        elif c == "6":
            _menu_tools_submenu(args)
        elif c == "7":
            root = _menu_config_submenu(root, args)
        elif c == "8":
            if not root.is_dir(): continue
            mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
            organize_loose_to_processed(root, tmdb_api_key=args.tmdb_api_key, omdb_api_key=args.omdb_api_key, auto_fetch_ro_subtitles=not args.no_auto_fetch_subs, subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user, mkvmerge_exe=mkv_exe)
            input("  Press Enter...")

# ===========================================================================
# Series: pipeline
# ===========================================================================

def series_pipeline(root: Path, *, mkvmerge_exe: str | None, fetch_subs: bool = False, subs_lang: str = "ro", use_subliminal: bool = False, subliminal_exe: str = "", dry_run: bool = False, skip_flatten: bool = False, skip_cleanup: bool = False) -> None:
    t0 = _timer_start()
    _v(f"series_pipeline: root={root} fetch_subs={fetch_subs} subs_lang={subs_lang}")
    os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    os_user = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_USER") or "").strip()
    _v(f"OS.com API key={'set' if os_api_key else 'NOT SET'}")
    # Flatten first: move videos from subfolders to root
    if not skip_flatten:
        set_window_title("Series: flatten")
        _v("Flatten phase: moving videos from subfolders to root")
        fl = _flatten_folders(root, dry_run=dry_run)
        if fl: _bullet(f"Flattened: moved {fl} file(s) from subfolders" if not dry_run else f"Would flatten: {fl} file(s) from subfolders")
    # Then collect videos (all at root level after flatten)
    videos: list[Path] = []
    for ext in VIDEO_EXTENSIONS:
        videos.extend(sorted(root.rglob(f"*{ext}")))
        videos.extend(sorted(root.rglob(f"*{ext.upper()}")))
    videos = sorted(set(videos))
    TEMP_MARKS = (".keep", ".remux", ".dedup", ".bak")
    videos = [v for v in videos if v.is_file() and not is_own_file(v, root) and not any(m in v.stem.lower() for m in TEMP_MARKS)]
    if not videos: _bullet("No video files found."); return
    _bullet(f"Found {len(videos)} video(s).")
    _v(f"Collected {len(videos)} videos after filtering")
    if not dry_run and not skip_cleanup:
        cleaned = 0
        for i, video in enumerate(videos):
            folder = video.parent
            if folder == root: continue
            if any(v.parent == folder for v in videos[:i]): continue
            _cleanup_folder(folder, root); cleaned += 1
        if cleaned: _bullet(f"Cleaned {cleaned} folder(s).")
    downloaded = srt_fixed = srt_errors = video_done = video_errors = video_skipped = 0
    for i, video in enumerate(videos):
        _v(f"[{i+1}/{len(videos)}] {video.name}")
        rel = video.relative_to(root)
        set_window_title(f"Series: {rel}")
        _bullet(f"[{rel}]")
        if dry_run:
            _bullet(f"Would strip subs, keep best available")
            video_done += 1
            continue
        ro_id, en_id = _find_embedded_subs(video, mkvmerge_exe=mkvmerge_exe)
        if ro_id is not None:
            if _remux_keep_sub_track(video, track_id=ro_id, mkvmerge_exe=mkvmerge_exe):
                video_done += 1; _bullet("Kept RO subtitle")
            else: video_errors += 1
            continue
        srt_path = video.with_suffix(".srt")
        have_sub = False
        if fetch_subs:
            stem = video.stem
            have_sub = os_api_key and opensubtitles_search_and_download_by_hash(video, srt_path, api_key=os_api_key, lang=subs_lang)
            if have_sub:
                downloaded += 1
                _bullet(f"Downloaded (hash): {srt_path.name}")
            elif use_subliminal:
                ok = download_via_subliminal(video, subliminal_exe=subliminal_exe, lang=subs_lang, opensubtitlescom_user=os_user)
                if ok and srt_path.is_file(): downloaded += 1; have_sub = True; _bullet(f"Downloaded: {srt_path.name}")
                else: _bullet("No subs (subliminal)")
            else:
                parsed = parse_episode_stem(stem)
                query = stem; season = None; episode = None
                if parsed:
                    show_name, season, episode, ep_title = parsed
                    query = f"{show_name} S{season:02d}E{episode:02d}"
                    if ep_title: query += f" {ep_title}"
                ok = opensubtitles_download(query, srt_path, api_key=os_api_key, lang=subs_lang, season=season, episode=episode)
                if ok and srt_path.is_file(): downloaded += 1; have_sub = True; _bullet(f"Downloaded: {srt_path.name}")
                else: _bullet(f"OpenSubtitles: no {subs_lang}")
        if have_sub:
            if fix_srt_file(srt_path): srt_fixed += 1
            else: srt_errors += 1; continue
            if remux_series_video(video, srt_path, mkvmerge_exe=mkvmerge_exe, lang=subs_lang):
                video_done += 1; _bullet(f"Remuxed {subs_lang.upper()}")
            else: video_errors += 1
        elif en_id is not None:
            if _remux_keep_sub_track(video, track_id=en_id, mkvmerge_exe=mkvmerge_exe):
                video_done += 1; _bullet("Kept EN subtitle")
            else: video_errors += 1
        else:
            if fetch_subs:
                eng_srt = video.with_suffix(".en.srt")
                stem = video.stem
                eng_ok = False
                eng_ok = os_api_key and opensubtitles_search_and_download_by_hash(video, eng_srt, api_key=os_api_key, lang="en")
                if eng_ok:
                    downloaded += 1
                    _bullet(f"Downloaded EN (hash): {eng_srt.name}")
                elif use_subliminal:
                    ok = download_via_subliminal(video, subliminal_exe=subliminal_exe, lang="en", opensubtitlescom_user=os_user)
                    if ok and eng_srt.is_file(): downloaded += 1; eng_ok = True; _bullet(f"Downloaded EN: {eng_srt.name}")
                else:
                    parsed = parse_episode_stem(stem)
                    query = stem; season = None; episode = None
                    if parsed:
                        show_name, season, episode, ep_title = parsed
                        query = f"{show_name} S{season:02d}E{episode:02d}"
                        if ep_title: query += f" {ep_title}"
                    ok = opensubtitles_download(query, eng_srt, api_key=os_api_key, lang="en", season=season, episode=episode)
                    if ok and eng_srt.is_file(): downloaded += 1; eng_ok = True; _bullet(f"Downloaded EN: {eng_srt.name}")
                if eng_ok:
                    if fix_srt_file(eng_srt): srt_fixed += 1
                    else: srt_errors += 1; continue
                    if remux_series_video(video, eng_srt, mkvmerge_exe=mkvmerge_exe, lang="en"):
                        video_done += 1; _bullet("Remuxed EN")
                    else: video_errors += 1
                else: video_skipped += 1
            else: video_skipped += 1
    _heading("Summary")
    if downloaded: _bullet(f"Downloaded: {downloaded}")
    _bullet(f"SRT fixed: {srt_fixed}")
    if srt_errors: _bullet(f"SRT errors: {srt_errors}")
    _bullet(f"Processed: {video_done}, skipped: {video_skipped}")
    if video_errors: _bullet(f"Errors: {video_errors}")

# ===========================================================================
# TMM CLI (lazy import to avoid dependency)
# ===========================================================================

def run_tmm_cli_sync(tmm_dir_cli: str, *, movies: bool, tvshows: bool, timeout_sec: int = 4*3600) -> None:
    exe = resolve_tmm_cmd_exe(tmm_dir_cli)
    if not exe: raise RuntimeError("TMM CLI not found")
    cwd = str(exe.parent)
    for do, module, title in ((movies, "movie", "TMM MOVIES"), (tvshows, "tvshow", "TMM TV")):
        if not do: continue
        _heading(title)
        _bullet(f"Running: {exe.name} {module} -u -n -r")
        proc = subprocess.run([str(exe), module, "-u", "-n", "-r"], cwd=cwd, timeout=timeout_sec, text=True)
        if proc.returncode != 0: raise RuntimeError(f"TMM {module} exited with {proc.returncode}")

_ACTION_RESULTS: list[dict] = []

def _action_result(status: str, file: str = "", detail: str = "") -> None:
    r = {"status": status, "file": file}
    if detail: r["detail"] = detail
    _ACTION_RESULTS.append(r)

def _run_action_videos(root: Path, action_fn, *, label: str, api_key: str = "", lang: str = "ro", mkv_exe: str | None = None) -> dict:
    videos = _find_video_files(root)
    if not videos:
        return {"ok": 0, "fail": 0, "skipped": 0, "total": 0}
    ok = fail = skipped = 0
    for vp in videos:
        srtp = vp.with_suffix(".srt")
        if srtp.exists():
            skipped += 1
            continue
        try:
            if action_fn(vp, srtp, api_key=api_key, lang=lang, mkv_exe=mkv_exe):
                ok += 1
                _action_result("ok", file=str(vp))
            else:
                fail += 1
                _action_result("fail", file=str(vp))
        except Exception as e:
            fail += 1
            _action_result("fail", file=str(vp), detail=str(e))
    return {"ok": ok, "fail": fail, "skipped": skipped, "total": len(videos)}

def _action_subs_hash(root: Path, args: argparse.Namespace) -> dict:
    os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    if not os_api_key:
        return {"error": "No OS.com API key"}
    def fn(vp, srtp, **kw):
        return opensubtitles_search_and_download_by_hash(vp, srtp, api_key=kw["api_key"], lang=kw["lang"])
    return _run_action_videos(root, fn, label="subs-hash", api_key=os_api_key, lang=args.subs_lang)

def _action_subs_hash_fallback(root: Path, args: argparse.Namespace) -> dict:
    os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    if not os_api_key:
        return {"error": "No OS.com API key"}
    def fn(vp, srtp, **kw):
        return download_subtitles_by_hash_with_fallback(vp, srtp, api_key=kw["api_key"], lang=kw["lang"])
    return _run_action_videos(root, fn, label="subs-hash-fallback", api_key=os_api_key, lang=args.subs_lang)

def _action_subs_download(root: Path, args: argparse.Namespace) -> dict:
    langs = [x.strip() for x in args.subs_lang.replace(",", " ").split() if x.strip()]
    fetch_subtitles_subliminal(root, languages=langs or ["ro"], subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user, force=args.subs_force)
    return {"ok": 0, "fail": 0, "total": 0}

def _action_subs_fix(root: Path, args: argparse.Namespace) -> dict:
    pairs = _find_video_srt_pairs(root)
    ok = fail = 0
    for _, srtp in pairs:
        if fix_srt_file(srtp):
            ok += 1
            _action_result("ok", file=str(srtp))
        else:
            fail += 1
            _action_result("fail", file=str(srtp))
    return {"ok": ok, "fail": fail, "total": len(pairs)}

def _action_subs_strip(root: Path, args: argparse.Namespace) -> dict:
    pairs = _find_video_srt_pairs(root)
    ok = fail = 0
    for _, srtp in pairs:
        if strip_srt_diacritics(srtp):
            ok += 1
            _action_result("ok", file=str(srtp))
        else:
            fail += 1
            _action_result("fail", file=str(srtp))
    return {"ok": ok, "fail": fail, "total": len(pairs)}

def _action_subs_remux(root: Path, args: argparse.Namespace) -> dict:
    mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
    if not mkv_exe:
        return {"error": "mkvmerge not found"}
    pairs = _find_video_srt_pairs(root)
    ok = fail = 0
    for vp, srtp in pairs:
        if remux_series_video(vp, srtp, mkvmerge_exe=mkv_exe, lang=args.subs_lang):
            ok += 1
            _action_result("ok", file=str(vp))
        else:
            fail += 1
            _action_result("fail", file=str(vp))
    return {"ok": ok, "fail": fail, "total": len(pairs)}

def _action_subs_pipeline(root: Path, args: argparse.Namespace) -> dict:
    os_api_key = (os.environ.get("PROCESS_MOVIES_OPENSUBTITLES_COM_API_KEY", "") or _DEFAULT_OPENSUBTITLES_COM_API_KEY).strip()
    mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
    if not mkv_exe:
        return {"error": "mkvmerge not found"}
    videos = _find_video_files(root)
    ok = fail = 0
    for vp in videos:
        srtp = vp.with_suffix(".srt")
        if not srtp.exists():
            if os_api_key:
                download_subtitles_by_hash_with_fallback(vp, srtp, api_key=os_api_key, lang=args.subs_lang)
        if not srtp.exists():
            _action_result("skip", file=str(vp), detail="no SRT")
            continue
        ok_here = 0
        if fix_srt_file(srtp): ok_here += 1
        if strip_srt_diacritics(srtp): ok_here += 1
        if remux_series_video(vp, srtp, mkvmerge_exe=mkv_exe, lang=args.subs_lang): ok_here += 1
        if ok_here == 3:
            ok += 1
            _action_result("ok", file=str(vp))
        else:
            fail += 1
            _action_result("fail", file=str(vp), detail=f"{ok_here}/3 steps ok")
    return {"ok": ok, "fail": fail, "total": len(videos)}

# Action dispatch table
_ACTIONS: dict[str, tuple[str, callable]] = {
    "subs-hash": ("Hash search via OS.com", _action_subs_hash),
    "subs-hash-fallback": ("Hash search + name fallback", _action_subs_hash_fallback),
    "subs-download": ("Download subs via subliminal", _action_subs_download),
    "subs-fix": ("Fix SRT encoding", _action_subs_fix),
    "subs-strip": ("Strip diacritics", _action_subs_strip),
    "subs-remux": ("Remux sidecar SRT", _action_subs_remux),
    "subs-pipeline": ("Full pipeline: hash → fix → strip → remux", _action_subs_pipeline),
}

# ===========================================================================
# Main — unified entry point
# ===========================================================================

def _run_action(root: Path, args: argparse.Namespace) -> dict | None:
    """Dispatch to action handler and return JSON-serializable result."""
    action = args.action
    if action not in _ACTIONS:
        return None
    name, fn = _ACTIONS[action]
    _heading(name)
    t0 = _timer_start()
    result = fn(root, args)
    result["action"] = action
    result["elapsed"] = round(_timer_elapsed_raw(t0), 2)
    result["results"] = _ACTION_RESULTS
    # Print JSON summary to stdout after all human output
    if args.json:
        print("\n" + json.dumps(result, ensure_ascii=False))
    else:
        _bullet(f"Done. {result.get('ok', 0)} ok, {result.get('fail', 0)} fail"
                   f"{', ' + str(result.get('skipped', 0)) + ' skipped' if result.get('skipped') else ''}")
    return result

def _exit_code(result: dict) -> int:
    if result.get("error"):
        return 3
    fail = result.get("fail", 0)
    ok = result.get("ok", 0)
    if fail and not ok:
        return 2
    if fail:
        return 1
    return 0

def main() -> None:
    ap = argparse.ArgumentParser(description="Video organizer: Movies & Series pipeline.", formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""
Actions (--action):
  subs-hash           Hash search via OS.com (exact match)
  subs-hash-fallback  Hash search + name fallback
  subs-download       Download subs via subliminal
  subs-fix            Fix SRT encoding (cp1250/iso-8859-2 → UTF-8)
  subs-strip          Strip Romanian diacritics
  subs-remux          Remux sidecar SRT into video
  subs-pipeline       Full pipeline: hash → fix → strip → remux
  series              Full series pipeline
  movies              Full movies pipeline

Examples:
  %% python3 video_tool.py --root /path --action subs-pipeline --json
  %% python3 video_tool.py --root /path --action subs-hash --json
  %% python3 video_tool.py --root /path --action subs-pipeline
""")
    ap.add_argument("--root", default=".", help="Root path (default: current dir; resolves '.' and '..')")
    ap.add_argument("--no-prompt", action="store_true", help="Skip path prompt, use default root")
    ap.add_argument("--mode", choices=["movies", "series", "menu"], default="menu", help="Run mode (default: interactive menu)")
    ap.add_argument("--action", default="", choices=list(_ACTIONS.keys()), help="Non-interactive action for AI/scripting use")
    ap.add_argument("--json", action="store_true", help="JSON output (machine-readable)")

    # Series flags
    ap.add_argument("--fetch-subs", action="store_true", help="Download missing subtitles")
    ap.add_argument("--use-subliminal", action="store_true", help="Use subliminal for downloads")
    ap.add_argument("--subliminal", default="", metavar="EXE", help="subliminal executable path")
    ap.add_argument("--subs-lang", default="ro", metavar="LANG", help="Preferred subtitle language (default: ro)")
    ap.add_argument("--mkvmerge-dir", default="", metavar="DIR", help=f"MKVToolNix dir (default: {TOOL_DIR_MKVMERGE})")
    ap.add_argument("--dry-run", action="store_true", help="Preview only")
    ap.add_argument("--skip-flatten", action="store_true", help="Skip moving video files from subfolders to root")
    ap.add_argument("--skip-cleanup", action="store_true", help="Skip junk deletion and file renaming")

    # Movies flags
    ap.add_argument("-i", "--interactive", "--menu", action="store_true", help="Interactive menu")
    ap.add_argument("--check-deps", action="store_true", help="Print dependencies")
    ap.add_argument("--install-deps", action="store_true", help="Install mkvtoolnix")
    ap.add_argument("--tmm-dir", default="", metavar="DIR", help=f"TMM folder ({TOOL_DIR_TMM})")
    ap.add_argument("--tmm-run-movies", action="store_true", help="TMM CLI movies -u -n -r")
    ap.add_argument("--tmm-run-tvshows", action="store_true", help="TMM CLI tvshow -u -n -r")
    ap.add_argument("--organize-loose", action="store_true", help="Loose files -> folders + poster + subs")
    ap.add_argument("--tmdb-api-key", default="", help="TMDB API key")
    ap.add_argument("--omdb-api-key", default="", help="OMDb API key")
    ap.add_argument("--no-auto-fetch-subs", action="store_true", help="Skip auto RO sub download with --organize-loose")
    ap.add_argument("--subs-force", action="store_true", help="Force overwrite existing subs")
    ap.add_argument("--opensubtitlescom-user", default="", help="OS.com username")
    ap.add_argument("--skip-rename", action="store_true", help="Skip folder renaming")
    ap.add_argument("--skip-rename-files", action="store_true", help="Skip file renaming")
    ap.add_argument("--skip-clean", action="store_true", help="Skip file cleaning")
    ap.add_argument("--skip-posters", action="store_true", help="Skip poster conversion")
    ap.add_argument("--skip-subtitles", action="store_true", help="Skip subtitle fixing")
    ap.add_argument("--skip-mkv-strip", action="store_true", help="Skip MKV remux")
    ap.add_argument("--mkv-strip-log", default="", help="MKV log path")
    ap.add_argument("--to-processed", action="store_true", help="Non-destructive: copy movies to Processed/")

    args = ap.parse_args()

    # Path resolution
    if args.root == "." and not args.no_prompt and not args.check_deps and not args.install_deps:
        if args.mode == "menu" and not args.interactive:
            try: inp = input(f"Path [{_DEFAULT_ROOT}]: ").strip()
            except (EOFError, OSError): inp = ""
            args.root = inp or _DEFAULT_ROOT
        else:
            args.root = _DEFAULT_ROOT or "."
    root = sanitize_path(args.root)
    if root.is_file(): root = root.parent
    if not root.is_dir() and not args.check_deps and not args.install_deps:
        print(f"ERROR: '{root}' is not a directory."); sys.exit(1)

    # Action dispatch (AI/scripting mode)
    if args.action:
        result = _run_action(root, args)
        if result is None:
            print(f"ERROR: unknown action '{args.action}'")
            sys.exit(3)
        sys.exit(_exit_code(result))

    # Dispatch
    if args.check_deps:
        _, ok_m = print_dependency_report(args.mkvmerge_dir, args.tmm_dir, args.subliminal)
        sys.exit(0 if ok_m else 1)
    if args.install_deps:
        if _dep_mkvmerge(args.mkvmerge_dir)[0]: _bullet("mkvmerge already available.")
        else: ok, msg = try_install_mkvtoolnix(); _bullet(msg)
        sys.exit(0)
    if args.to_processed:
        mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
        organize_loose_to_processed(root, tmdb_api_key=args.tmdb_api_key, omdb_api_key=args.omdb_api_key, auto_fetch_ro_subtitles=not args.no_auto_fetch_subs, subliminal_exe=args.subliminal, opensubtitlescom_user=args.opensubtitlescom_user, mkvmerge_exe=mkv_exe)
        return
    if args.interactive or args.mode == "movies":
        try: interactive_menu(args)
        except KeyboardInterrupt: print("\n  Bye!"); return
        return
    if args.mode == "series":
        mkv_exe = resolve_mkvmerge_exe(args.mkvmerge_dir)
        series_pipeline(root, mkvmerge_exe=mkv_exe, fetch_subs=args.fetch_subs, subs_lang=args.subs_lang, use_subliminal=args.use_subliminal, subliminal_exe=args.subliminal, dry_run=args.dry_run, skip_flatten=args.skip_flatten, skip_cleanup=args.skip_cleanup)
        return

    # Interactive menu (default)
    try: interactive_menu(args)
    except KeyboardInterrupt: print("\n  Bye!")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n  Bye!")
