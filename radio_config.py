#!/usr/bin/env python3
"""Midnight Youkai Radio — shared station configuration.

Single source of truth for paths, audio constants, station identity and the
youkai character roster (used by both the streaming engine and the web player).
"""

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

TRACK_DIR = Path(os.environ.get("MYR_TRACK_DIR", BASE_DIR / "Touhou_Eurobeat"))
CACHE_DIR = Path(os.environ.get("MYR_CACHE_DIR", BASE_DIR / "cache"))
STATE_DIR = Path(os.environ.get("MYR_STATE_DIR", BASE_DIR / "state"))
LOG_DIR = BASE_DIR / "logs"
PID_DIR = BASE_DIR / "pids"

TTS_CACHE_DIR = CACHE_DIR / "tts"
SEGMENT_DIR = CACHE_DIR / "segments"
BED_FILE = CACHE_DIR / "bed.wav"
ON_AIR_DIR = CACHE_DIR / "onair"

LOUDNESS_CACHE = CACHE_DIR / "loudness.json"
MARKER_FILE = CACHE_DIR / "marker.wav"

# Inaudible 16 kHz sync marker: lets the web player measure the real
# encoder -> icecast -> browser latency instead of estimating it.
MARKER_FREQ = 16000
MARKER_PULSE_MS = 200
MARKER_GAP_MS = 150
MARKER_PULSES = 3
MARKER_ENABLED = os.environ.get("MYR_MARKER", "1") not in ("0", "false", "no")
MARKER_LEVEL_DB = -34.0
MARKER_AT_MS = 60
CALIB_REQUEST = STATE_DIR / "calibrate.req"
CALIB_RESULT = STATE_DIR / "calibrate.res"
HISTORY_FILE = STATE_DIR / "history.jsonl"
NOW_PLAYING_FILE = STATE_DIR / "now_playing.json"
NOW_PLAYING_TXT = BASE_DIR / "now_playing.txt"

# ---------------------------------------------------------------------------
# Station identity
# ---------------------------------------------------------------------------
STATION_NAME = "Midnight Youkai Radio"
STATION_NAME_JP = "東方幻想夜行"
STATION_TAGLINE = "TOUHOU EUROBEAT · 24/7 · TOUGE NIGHT DRIVE"
STATION_LOCATION = os.environ.get("MYR_LOCATION", "Singapore")
STATION_GENRE = "Touhou Eurobeat"

# Virtual DJ — Mystia Lorelei, the night-sparrow youkai who sings at night.
DJ_NAME = os.environ.get("MYR_DJ_NAME", "Mystia Lorelei")
DJ_NAME_JP = "ミスティア・ローレライ"
DJ_VOICE = os.environ.get("MYR_DJ_VOICE", "Chloe")        # Mia | Chloe | Dean | Milo
DJ_VOICE_ZH = os.environ.get("MYR_DJ_VOICE_ZH", "冰糖")   # 冰糖 | 茉莉 | 白桦 | 苏打
DJ_VOICES = {"en": DJ_VOICE, "zh": DJ_VOICE_ZH}
DJ_LANGS = [x for x in os.environ.get("MYR_DJ_LANGS", "en,zh").split(",")
            if x.strip() in ("en", "zh")] or ["en"]
DJ_NAME_ZH = os.environ.get("MYR_DJ_NAME_ZH", "米斯蒂娅·萝蕾拉")
STATION_NAME_ZH = "东方幻想夜行 · 中文台"
DJ_LANG = os.environ.get("MYR_DJ_LANG", "en").lower()      # en | zh

# ---------------------------------------------------------------------------
# MiMo API
# ---------------------------------------------------------------------------
MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://YOUR_MIMO_ENDPOINT/v1")
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "YOUR_MIMO_API_KEY_HERE")
LLM_MODEL = os.environ.get("MYR_LLM_MODEL", "mimo-v2.5-pro")
TTS_MODEL = os.environ.get("MYR_TTS_MODEL", "mimo-v2.5-tts")

# ---------------------------------------------------------------------------
# Icecast / audio pipeline
# ---------------------------------------------------------------------------
ICECAST_HOST = os.environ.get("MYR_ICECAST_HOST", "127.0.0.1")
ICECAST_PORT = int(os.environ.get("MYR_ICECAST_PORT", "8001"))
ICECAST_MOUNT = os.environ.get("MYR_ICECAST_MOUNT", "/midnight")
ICECAST_SOURCE_PASSWORD = os.environ.get("MYR_SOURCE_PASSWORD", "CHANGEME")
ICECAST_ADMIN_USER = os.environ.get("MYR_ADMIN_USER", "admin")
ICECAST_ADMIN_PASSWORD = os.environ.get("MYR_ADMIN_PASSWORD", "CHANGEME")

ICECAST_SOURCE_URL = (
    f"icecast://source:{ICECAST_SOURCE_PASSWORD}@{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}"
)
ICECAST_HTTP_URL = f"http://{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}"
ICECAST_STATUS_URL = f"http://{ICECAST_HOST}:{ICECAST_PORT}/status-json.xsl"

WEB_PORT = int(os.environ.get("MYR_WEB_PORT", "9999"))

# A single, fixed on-air format. Every sound is resampled to this before it
# reaches the encoder — mixed sample rates are what made the old stream cut out.
SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2              # bytes (s16le)
MP3_BITRATE = "192k"
BLOCK_MS = 250                # feeder write granularity

TARGET_LUFS = float(os.environ.get("MYR_TARGET_LUFS", "-11.5"))   # music loudness
VOICE_LUFS = float(os.environ.get("MYR_VOICE_LUFS", "-8.5"))      # DJ voice above music
BED_LUFS = float(os.environ.get("MYR_BED_LUFS", "-19.0"))         # interlude bed
DUCK_DB = float(os.environ.get("MYR_DUCK_DB", "-13.0"))
VOICE_AT_MS = 2600
DUCK_FADE_MS = 1600

CROSSFADE_MS = int(os.environ.get("MYR_CROSSFADE_MS", "3000"))
QUEUE_AHEAD = int(os.environ.get("MYR_QUEUE_AHEAD", "2"))
PREBUFFER_SECONDS = float(os.environ.get("MYR_PREBUFFER_SECONDS", "24"))
PACING_LEAD_S = 0.7           # keep the encoder fed slightly ahead of realtime
BED_LOOP_SECONDS = 16

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus", ".aac", ".wma"}

MOUNTS = [
    {"lang": "en", "mount": ICECAST_MOUNT, "web_path": "/", "voice": DJ_VOICE,
     "label": STATION_NAME, "label_jp": STATION_NAME_JP},
    {"lang": "zh",
     "mount": os.environ.get("MYR_ICECAST_MOUNT_ZH", ICECAST_MOUNT + "-cn"),
     "web_path": "/cn", "voice": DJ_VOICE_ZH,
     "label": STATION_NAME_ZH, "label_jp": STATION_NAME_JP},
]


def mount_for(lang: str) -> dict:
    for m in MOUNTS:
        if m["lang"] == lang:
            return m
    return MOUNTS[0]


def source_url(lang: str) -> str:
    return (f"icecast://source:{ICECAST_SOURCE_PASSWORD}@{ICECAST_HOST}:"
            f"{ICECAST_PORT}{mount_for(lang)['mount']}")


def http_url(lang: str) -> str:
    return f"http://{ICECAST_HOST}:{ICECAST_PORT}{mount_for(lang)['mount']}"


def _suffix(lang: str) -> str:
    return "" if lang == "en" else f"-{lang}"


NOW_PLAYING_FILES = {m["lang"]: STATE_DIR / f"now_playing{_suffix(m['lang'])}.json" for m in MOUNTS}
CALIB_REQUESTS = {m["lang"]: STATE_DIR / f"calibrate{_suffix(m['lang'])}.req" for m in MOUNTS}
CALIB_RESULTS = {m["lang"]: STATE_DIR / f"calibrate{_suffix(m['lang'])}.res" for m in MOUNTS}

for _d in (TRACK_DIR, CACHE_DIR, STATE_DIR, LOG_DIR, PID_DIR,
           TTS_CACHE_DIR, SEGMENT_DIR, ON_AIR_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Youkai roster — colours + parametric silhouette spec for the player artwork
# ---------------------------------------------------------------------------
CHARACTERS = {
    "reimu": {
        "name_zh": "博丽灵梦", "epithet_zh": "博丽的巫女",
        "name": "Reimu Hakurei", "jp": "博麗 霊夢", "epithet": "Hakurei Shrine Maiden",
        "color": "#e63946", "accent": "#fff1e6",
        "spec": {"hair": {"style": "long", "color": "#4a2c22", "tie": "#e63946"},
                 "head": {"type": "bow", "color": "#e63946"},
                 "acc": {"type": "gohei", "color": "#fdf6e3"},
                 "outfit": {"type": "shrine", "main": "#f5ece0", "sub": "#e63946"}},
    },
    "marisa": {
        "name_zh": "雾雨魔理沙", "epithet_zh": "普通的魔法使",
        "name": "Marisa Kirisame", "jp": "霧雨 魔理沙", "epithet": "Ordinary Magician",
        "color": "#ffd23f", "accent": "#fff7d6",
        "spec": {"hair": {"style": "long", "color": "#e9c46a", "tie": "#ffffff"},
                 "head": {"type": "witch_hat", "color": "#1b1b24"},
                 "acc": {"type": "broom", "color": "#c9a227"},
                 "outfit": {"type": "witch", "main": "#1b1b24", "sub": "#ffffff"}},
    },
    "remilia": {
        "name_zh": "蕾米莉亚·斯卡雷特", "epithet_zh": "红魔馆之主",
        "name": "Remilia Scarlet", "jp": "レミリア・スカーレット", "epithet": "Scarlet Devil",
        "color": "#ff5c8a", "accent": "#ffd6e6",
        "spec": {"hair": {"style": "short", "color": "#8fb8e6", "tie": "#ff5c8a"},
                 "head": {"type": "mob_cap", "color": "#f5e6ee"},
                 "acc": {"type": "bat_wings", "color": "#ff5c8a"},
                 "outfit": {"type": "dress", "main": "#f5e6ee", "sub": "#ff5c8a"}},
    },
    "flandre": {
        "name_zh": "芙兰朵露·斯卡雷特", "epithet_zh": "恶魔之妹",
        "name": "Flandre Scarlet", "jp": "フランドール・スカーレット", "epithet": "Sister of the Devil",
        "color": "#ff2b3d", "accent": "#ffd0d6",
        "spec": {"hair": {"style": "side_ponytail", "color": "#f2d16b", "tie": "#ff2b3d"},
                 "head": {"type": "ribbon", "color": "#ff2b3d"},
                 "acc": {"type": "crystal_wings", "color": "#ff2b3d"},
                 "outfit": {"type": "dress", "main": "#e8455a", "sub": "#fff1f2"}},
    },
    "sakuya": {
        "name_zh": "十六夜咲夜", "epithet_zh": "完美的女仆长",
        "name": "Sakuya Izayoi", "jp": "十六夜 咲夜", "epithet": "Perfect and Elegant Servant",
        "color": "#a8d8ff", "accent": "#ffffff",
        "spec": {"hair": {"style": "braid", "color": "#c9d6e8", "tie": "#4a5568"},
                 "head": {"type": "headband", "color": "#ffffff"},
                 "acc": {"type": "knife", "color": "#dfe9f5"},
                 "outfit": {"type": "maid", "main": "#26303f", "sub": "#ffffff"}},
    },
    "patchouli": {
        "name_zh": "帕秋莉·诺蕾姬", "epithet_zh": "一周的魔法使",
        "name": "Patchouli Knowledge", "jp": "パチュリー・ノーレッジ", "epithet": "One-Week Magician",
        "color": "#b06bff", "accent": "#e6d4ff",
        "spec": {"hair": {"style": "long", "color": "#9b7fd4", "tie": "#ffd166"},
                 "head": {"type": "nightcap", "color": "#f0e2ff"},
                 "acc": {"type": "book", "color": "#7b4fd4"},
                 "outfit": {"type": "dress", "main": "#8f6bd0", "sub": "#f0e2ff"}},
    },
    "cirno": {
        "name_zh": "琪露诺", "epithet_zh": "冰之妖精",
        "name": "Cirno", "jp": "チルノ", "epithet": "Ice Fairy",
        "color": "#4fd8ff", "accent": "#dffbff",
        "spec": {"hair": {"style": "short", "color": "#7fd4ff", "tie": "#2f9fd0"},
                 "head": {"type": "ribbon", "color": "#2f9fd0"},
                 "acc": {"type": "ice_wings", "color": "#bfefff"},
                 "outfit": {"type": "dress", "main": "#3fb6e6", "sub": "#dffbff"}},
    },
    "kaguya": {
        "name_zh": "蓬莱山辉夜", "epithet_zh": "月之公主",
        "name": "Kaguya Houraisan", "jp": "蓬莱山 輝夜", "epithet": "Lunatic Princess",
        "color": "#f0b7ff", "accent": "#fff0ff",
        "spec": {"hair": {"style": "long", "color": "#2a2438", "tie": "#f0b7ff"},
                 "head": {"type": "ribbon", "color": "#c98fe0"},
                 "acc": {"type": "moon", "color": "#f6e7ff"},
                 "outfit": {"type": "hakama", "main": "#c9a2de", "sub": "#fff0ff"}},
    },
    "mokou": {
        "name_zh": "藤原妹红", "epithet_zh": "不死之凤凰",
        "name": "Fujiwara no Mokou", "jp": "藤原 妹紅", "epithet": "Immortal Phoenix",
        "color": "#ff7a3d", "accent": "#ffe0c2",
        "spec": {"hair": {"style": "long", "color": "#f3ece3", "tie": "#ff7a3d"},
                 "head": {"type": "ribbon", "color": "#ff7a3d"},
                 "acc": {"type": "fire", "color": "#ff7a3d"},
                 "outfit": {"type": "casual", "main": "#3a3f4b", "sub": "#ff7a3d"}},
    },
    "youmu": {
        "name_zh": "魂魄妖梦", "epithet_zh": "半人半灵",
        "name": "Youmu Konpaku", "jp": "魂魄 妖夢", "epithet": "Half-Human Half-Phantom",
        "color": "#b9ffe0", "accent": "#f0fff8",
        "spec": {"hair": {"style": "short", "color": "#dfe9e3", "tie": "#7fd6a8"},
                 "head": {"type": "ribbon", "color": "#7fd6a8"},
                 "acc": {"type": "sword", "color": "#dfe9f5"},
                 "outfit": {"type": "uniform", "main": "#2f4a3f", "sub": "#b9ffe0"}},
    },
    "yukari": {
        "name_zh": "八云紫", "epithet_zh": "境界的妖怪",
        "name": "Yukari Yakumo", "jp": "八雲 紫", "epithet": "Phantasm of the Boundary",
        "color": "#c9a2ff", "accent": "#efe0ff",
        "spec": {"hair": {"style": "long", "color": "#f0dfa8", "tie": "#c9a2ff"},
                 "head": {"type": "mob_cap", "color": "#efe0ff"},
                 "acc": {"type": "parasol", "color": "#a97fe0"},
                 "outfit": {"type": "dress", "main": "#8f6bd0", "sub": "#efe0ff"}},
    },
    "sanae": {
        "name_zh": "东风谷早苗", "epithet_zh": "现人神巫女",
        "name": "Sanae Kochiya", "jp": "東風谷 早苗", "epithet": "Miracle Working Shrine Maiden",
        "color": "#6bffa8", "accent": "#e8fff2",
        "spec": {"hair": {"style": "long", "color": "#5fbf8f", "tie": "#ffffff"},
                 "head": {"type": "ribbon", "color": "#6bffa8"},
                 "acc": {"type": "snake", "color": "#6bffa8"},
                 "outfit": {"type": "shrine", "main": "#f2fff7", "sub": "#2fa96f"}},
    },
    "koishi": {
        "name_zh": "古明地恋", "epithet_zh": "无意识的妖怪",
        "name": "Koishi Komeiji", "jp": "古明地 こいし", "epithet": "Closed Third Eye",
        "color": "#9cff5f", "accent": "#e8ffd8",
        "spec": {"hair": {"style": "short", "color": "#cfe6a0", "tie": "#9cff5f"},
                 "head": {"type": "hat", "color": "#3f5f2f"},
                 "acc": {"type": "third_eye", "color": "#9cff5f"},
                 "outfit": {"type": "dress", "main": "#4f7f3f", "sub": "#e8ffd8"}},
    },
    "aya": {
        "name_zh": "射命丸文", "epithet_zh": "传统的记者",
        "name": "Aya Shameimaru", "jp": "射命丸 文", "epithet": "Traditional Reporter of Fantasy",
        "color": "#ff5c5c", "accent": "#ffe0e0",
        "spec": {"hair": {"style": "short", "color": "#2e2a33", "tie": "#ff5c5c"},
                 "head": {"type": "tokin", "color": "#f5efe2"},
                 "acc": {"type": "crow_wings", "color": "#ff5c5c"},
                 "outfit": {"type": "uniform", "main": "#f5efe2", "sub": "#8f2f3f"}},
    },
    "mystia": {
        "name_zh": "米斯蒂娅·萝蕾拉", "epithet_zh": "夜雀歌姬",
        "name": "Mystia Lorelei", "jp": "ミスティア・ローレライ", "epithet": "Night Sparrow Songstress",
        "color": "#ff9ad5", "accent": "#ffe6f4",
        "spec": {"hair": {"style": "long", "color": "#f0a8c8", "tie": "#ff9ad5"},
                 "head": {"type": "hat", "color": "#5f3f6f"},
                 "acc": {"type": "lantern", "color": "#ffd166"},
                 "outfit": {"type": "dress", "main": "#c95f9f", "sub": "#ffe6f4"}},
    },
    "reisen": {
        "name_zh": "铃仙·优昙华院·因幡", "epithet_zh": "月兔",
        "name": "Reisen Udongein Inaba", "jp": "鈴仙・優曇華院・イナバ", "epithet": "Lunatic Moon Rabbit",
        "color": "#c9b6ff", "accent": "#f0eaff",
        "spec": {"hair": {"style": "long", "color": "#d8c8f0", "tie": "#8f6bd0"},
                 "head": {"type": "ears", "color": "#e6dcff"},
                 "acc": {"type": "moon", "color": "#e6dcff"},
                 "outfit": {"type": "uniform", "main": "#5f4f9f", "sub": "#f0eaff"}},
    },
}

ROSTER_KEYS = sorted(CHARACTERS)

# keyword -> character key (thematic mapping, first match wins)
CHARACTER_KEYWORDS = [
    ("u.n. owen", "flandre"), ("u.n owen", "flandre"), ("unowen", "flandre"),
    ("flandre", "flandre"), ("scarlet", "remilia"), ("bloody", "remilia"),
    ("knife", "sakuya"), ("maid", "sakuya"), ("sakuya", "sakuya"), ("izayoi", "sakuya"),
    ("witch", "marisa"), ("magic", "marisa"), ("broom", "marisa"), ("star", "marisa"),
    ("asterisk", "marisa"), ("marisa", "marisa"),
    ("shrine", "reimu"), ("reimu", "reimu"), ("hakurei", "reimu"),
    ("lunatic", "kaguya"), ("princess", "kaguya"), ("eternal", "kaguya"), ("kaguya", "kaguya"),
    ("moon", "reisen"), ("rabbit", "reisen"), ("lunar", "reisen"), ("reisen", "reisen"),
    ("ice", "cirno"), ("freeze", "cirno"), ("cool", "cirno"), ("cirno", "cirno"), ("9", "cirno"),
    ("fire", "mokou"), ("phoenix", "mokou"), ("burn", "mokou"), ("mokou", "mokou"), ("immortal", "mokou"),
    ("book", "patchouli"), ("knowledge", "patchouli"), ("patchouli", "patchouli"), ("silence", "patchouli"),
    ("brave", "youmu"), ("sword", "youmu"), ("phantom", "youmu"), ("youmu", "youmu"), ("half", "youmu"),
    ("gap", "yukari"), ("boundary", "yukari"), ("yukari", "yukari"), ("spider", "yukari"),
    ("faith", "sanae"), ("miracle", "sanae"), ("snake", "sanae"), ("sanae", "sanae"), ("wind", "sanae"),
    ("dream", "koishi"), ("subconscious", "koishi"), ("koishi", "koishi"), ("eye", "koishi"),
    ("crow", "aya"), ("reporter", "aya"), ("aya", "aya"), ("news", "aya"),
    ("night", "mystia"), ("sparrow", "mystia"), ("mystia", "mystia"), ("song bird", "mystia"),
    ("dance", "mystia"), ("sing", "mystia"),
    ("spirit", "youmu"), ("blossom", "yukari"), ("sakura", "yukari"),
    ("heart", "remilia"), ("devil", "remilia"), ("paradise", "kaguya"),
    ("night drop", "sakuya"), ("drive", "marisa"), ("highway", "marisa"),
]

_ARTIST_HINTS = (
    "a-one", "aone", "a one", "a_one", "akane", "ariake", "cocoa", "gumi",
    "t. steve", "dj command", "eurobeat", "feat.",
)


def character_for(track_title: str, seed: str = "") -> dict:
    """Pick a youkai for a track: keyword match first, stable hash otherwise."""
    hay = f"{track_title} {seed}".lower()
    for needle, key in CHARACTER_KEYWORDS:
        if needle in hay:
            return {"key": key, **CHARACTERS[key]}
    h = int(hashlib.md5(hay.encode("utf-8")).hexdigest()[:8], 16)
    key = ROSTER_KEYS[h % len(ROSTER_KEYS)]
    return {"key": key, **CHARACTERS[key]}


# ---------------------------------------------------------------------------
# Track naming
# ---------------------------------------------------------------------------
_VIDEO_ID_RE = re.compile(r"\s*\[[A-Za-z0-9_\-]{6,15}\]\s*$")
_NOISE_RE = re.compile(
    r"\b(official\s*m\s*v|official\s*mv|official\s*video|mv|demo|teaser|non[\s\-]?stop|"
    r"eng(lish)?\s*subs?|english\s*subtitle|jpn\s*subtitle|lyric\s*video|full\s*ver(sion)?|"
    r"hd|4k|remaster(ed)?|touhou\s*eurobeat|toho\s*eurobeat|eurobeat|"
    r"vol\.?\s*\d+|volume\s*\d+)\b",
    re.IGNORECASE,
)


def parse_track_name(path) -> dict:
    """Derive {title, artist, album} from a downloaded file name."""
    stem = Path(path).stem
    stem = _VIDEO_ID_RE.sub("", stem)
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip(" -–~")

    album = ""
    m = re.search(r"T?OHO\s*EUROBEAT\s*VOL\.?\s*(\d+)", stem, re.IGNORECASE)
    if m:
        album = f"TOHO EUROBEAT VOL.{int(m.group(1))}"
    elif re.search(r"eurobeat\s*vol\.?\s*(\d+)", stem, re.IGNORECASE):
        album = "EUROBEAT FESTIVAL"

    artist = "A-One"
    work = stem
    low = work.lower()
    for hint in ("a-one", "a one", "aone", "akane", "ariake", "cocoa", "gumi"):
        if low.startswith(hint):
            artist = {"akane": "Akane", "ariake": "Ariake", "cocoa": "Cocoa",
                      "gumi": "GUMI"}.get(hint, "A-One")
            work = work[len(hint):].lstrip(" -_~.")
            break

    title = _NOISE_RE.sub(" ", work)
    title = re.sub(r"\s*[-–~]\s*$", "", re.sub(r"\s+", " ", title)).strip(" -–~._")
    if not title:
        title = re.sub(r"\s+", " ", _NOISE_RE.sub(" ", stem)).strip(" -–~._")
    if not title or not re.search(r"[A-Za-z0-9\u3040-\u30ff\u4e00-\u9fff]", title):
        title = f"Untitled Youkai Drive {hashlib.md5(stem.encode('utf-8')).hexdigest()[:4].upper()}"
    return {"title": title, "artist": artist, "album": album, "raw": stem}


# ---------------------------------------------------------------------------
# State files
# ---------------------------------------------------------------------------
def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def write_now_playing(payload: dict, lang: str = "en") -> None:
    payload = {**payload, "updated_at": time.time(), "lang": lang}
    _atomic_write(NOW_PLAYING_FILES.get(lang, NOW_PLAYING_FILE),
                  json.dumps(payload, ensure_ascii=False, indent=2))
    _atomic_write(NOW_PLAYING_TXT, payload.get("title", "") + "\n")


def read_now_playing(lang: str = "en") -> dict:
    try:
        return json.loads(NOW_PLAYING_FILES.get(lang, NOW_PLAYING_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def append_history(entry: dict) -> None:
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_history(limit: int = 20) -> list:
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def list_tracks() -> list:
    try:
        names = [p for p in TRACK_DIR.iterdir()
                 if p.suffix.lower() in AUDIO_EXTS and p.is_file()]
    except FileNotFoundError:
        return []
    return sorted(str(p) for p in names)


def station_payload(lang: str = "en") -> dict:
    lang = lang if lang in DJ_LANGS else "en"
    m = mount_for(lang)
    return {
        "station": m["label"],
        "station_jp": m["label_jp"],
        "tagline": STATION_TAGLINE,
        "location": STATION_LOCATION,
        "genre": STATION_GENRE,
        "lang": lang,
        "dj": {"name": DJ_NAME if lang == "en" else DJ_NAME_ZH,
               "name_jp": DJ_NAME_JP,
               "voice": m["voice"], "lang": lang},
        "stream": f"/stream{_suffix(lang)}",
        "mount": m["mount"],
        "web_path": m["web_path"],
        "characters": CHARACTERS,
        "track_count": len(list_tracks()),
        "languages": [{"lang": x["lang"], "web_path": x["web_path"], "label": x["label"]} for x in MOUNTS],
    }


def shuffle_bag(items: list):
    bag = list(items)
    random.shuffle(bag)
    while True:
        if not bag:
            bag = list(items)
            random.shuffle(bag)
        yield bag.pop()
