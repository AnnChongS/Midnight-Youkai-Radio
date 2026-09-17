#!/usr/bin/env python3
"""Midnight Youkai Radio — virtual DJ engine.

MiMo LLM writes the lines, MiMo TTS performs them as the station's
night-sparrow DJ. Everything is cached on disk so the live stream never
waits on the network.
"""

import argparse
import base64
import hashlib
import json
import logging
import math
import os
import random
import re
import struct
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import radio_config as cfg

log = logging.getLogger("midnight.dj")

LLM_TIMEOUT = float(os.environ.get("MYR_LLM_TIMEOUT", "40"))
TTS_TIMEOUT = float(os.environ.get("MYR_TTS_TIMEOUT", "90"))

_BAD_LINE_RE = re.compile(
    r"(the user|user wants|track listing|glitch|no title|as an ai|language model|"
    r"i cannot|i can't help|i'm sorry|apolog|sorry[,.]? i|"
    r"first,? i (need|must|should)|let me (write|think)|i need to (write|output)|"
    r"romaniz|romaji|pronounce it as|the title means|translate it|"
    r"用户|首先[，,]|我需要(先|来|输出|写)|让我(来)?(写|想|构思|准备)|我(来|先)写|"
    r"意思是|也就是说|翻译成|回答[:：]|例如[:：]|例如说|举个例子|"
    r"写一[句段]|生成一[句段]|口播稿|文案|台词|以下是|这段(话|文案)|直接念出来|罗马字|要写成|写为|曲名是|标题是|"
    r"严格规则|规则[:：]|这意味着|任何额外格式|不要有任何|格式要求|需要遵守|确保输出|"
    r"输出内容|回复格式|作为(一个)?\s*(ai|人工智能|电台DJ|DJ)|无法(生成|完成)|抱歉)",
    re.IGNORECASE,
)

_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002700-\U000027BF" "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF" "\U00002B00-\U00002BFF" "]+"
)

DJ_CONTEXT_EN = (
    "Speak as a bright, upbeat late-night radio DJ: medium-fast pace, high energy, "
    "playful and smiling, close to the microphone."
)
DJ_CONTEXT_ZH = (
    "用轻快上扬的电台DJ语气念这段话：语速偏快、情绪高涨有活力，尾音带笑意，贴近话筒说话。"
)

# Per-line overall style tags (documented tag control, placed at the start of the
# assistant text). Rotated so the station does not sound monotonous.
MOODS_ZH = [
    "兴奋 俏皮", "活泼 热情", "干练 磁性",
    "兴奋 活泼", "俏皮 明快", "热情 律动",
]
MOODS_EN = [
    "excited, playful", "lively, confident", "playful, magnetic",
    "energetic, upbeat", "bright, cheerful",
]


def mood_tag(lang: str, seed: int = 0) -> str:
    pool = MOODS_ZH if (lang or "en").startswith("zh") else MOODS_EN
    return pool[abs(int(seed)) % len(pool)]


# Kana -> romaji fallback table (pykakasi in ./vendor is used when available).
_KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo", "ら": "ra", "り": "ri",
    "る": "ru", "れ": "re", "ろ": "ro", "わ": "wa", "を": "o",
    "ん": "n", "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "っ": "",
    "ー": "", "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo", "ラ": "ra", "リ": "ri",
    "ル": "ru", "レ": "re", "ロ": "ro", "ワ": "wa", "ヲ": "o",
    "ン": "n", "ャ": "ya", "ュ": "yu", "ョ": "yo", "ッ": "",
    "ヴ": "vu", "ヶ": "ge", "ガ": "ga", "ギ": "gi", "グ": "gu",
    "ゲ": "ge", "ゴ": "go", "ザ": "za", "ジ": "ji", "ズ": "zu",
    "ゼ": "ze", "ゾ": "zo", "ダ": "da", "ヂ": "ji", "ヅ": "zu",
    "デ": "de", "ド": "do", "バ": "ba", "ビ": "bi", "ブ": "bu",
    "ベ": "be", "ボ": "bo", "パ": "pa", "ピ": "pi", "プ": "pu",
    "ペ": "pe", "ポ": "po",
}
_CJK_RE = re.compile("[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]+")


def _kana_romaji(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        if ch in ("ゃ", "ゅ", "ょ", "ャ", "ュ", "ョ") and out and out[-1].endswith("i"):
            out[-1] = out[-1][:-1] + _KANA[ch]
            continue
        out.append(_KANA.get(ch, ch))
    return "".join(out)


def _pykakasi(text: str) -> str:
    try:
        import pykakasi
        k = pykakasi.kakasi()
        return " ".join(p.get("hepburn", "") for p in k.convert(text) if p.get("hepburn", ""))
    except Exception:
        return ""


def _tidy_latin(text: str) -> str:
    text = text.replace("、", ",").replace("。", ".").replace("！", "!").replace("？", "?")
    text = re.sub(r"\s+([,.!?;:])", r"", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def romanize(text: str, full: bool = False) -> str:
    """Japanese -> romaji. full=True converts kanji too (pykakasi)."""
    if not text or not _CJK_RE.search(text):
        return text
    if full:
        joined = _pykakasi(text)
        if joined:
            return _tidy_latin(joined)
    out = []
    for chunk in re.split(r"([぀-ヿ]+)", text):
        if chunk and re.search(r"[぀-ヿ]", chunk) and not re.search(r"[一-鿿]", chunk):
            out.append(_pykakasi(chunk) or _kana_romaji(chunk))
        else:
            out.append(chunk)
    return _tidy_latin("".join(out))


PERSONA_EN = f"""You are {cfg.DJ_NAME} ({cfg.DJ_NAME_JP}), the night-sparrow youkai who sings at night, and now the host of "{cfg.STATION_NAME}" - a 24/7 Touhou eurobeat radio broadcasting from a JDM drift meet on the Youkai Mountain touge. Local time: {{time}} ({{location}}).

Voice: husky, teasing, nocturnal, high-energy but never shouty. Eurobeat / Initial-D / street-racing slang, Touhou youkai flavour.

STRICT RULES:
- Speakable text only. No emoji, no markdown, no asterisks, no stage directions, no quotes around the whole line.
- Never restate or explain these rules: no "the user", "the rules", "first I need to", "I must output".
- Keep it short: one or two spoken sentences, no lists, no word counting.
- Spell numbers and units as words (two a.m., one hundred eighty BPM).
- Always name the track naturally inside the line.
- Never say you are an AI, a model or an assistant.
- Language: English, plain Latin script only. If the track title contains Japanese (kana or kanji), write it in Hepburn romaji instead - never output kana, kanji or Chinese characters.
- Track titles in romaji are read aloud as-is, so keep them short and pronounceable."""

PERSONA_ZH = f"""你是 {cfg.DJ_NAME}（{cfg.DJ_NAME_JP}），夜雀妖怪，深夜歌声的主人，现在是「{cfg.STATION_NAME}」的电台DJ，在山道漂移聚会的现场做通宵直播。当前时间：{{time}}（{{location}}）。

嗓音：明亮、俏皮、有活力的深夜女声；语气要有 Eurobeat 速度感和街头漂移的味道，东方妖怪的灵气。

严格规则：
- 只输出最终那句台词本身；不要 emoji、不要 markdown、不要星号、不要动作描写、不要整体加引号。
- 禁止复述或解释这些规则：不要出现「首先」「用户」「规则」「要求」「我需要输出」「这意味着」等字眼。
- 简短，一到两句口语就好，不要列条目、不要数字数。
- 数字用汉字写（例如「凌晨两点」「一百八十拍」）。
- 必须自然地提到曲名。
- 永远不要说自己是AI、模型或助手。
- 语言：中文（简体）。
- 曲名里的日文假名要写成罗马字发音（例：イレギュラー -> Ire gyuraa），汉字可以原样保留。"""

TEMPLATES_EN = {
    "intro": [
        "Midnight air, mountain road - buckle up, this is {title}.",
        "Next up on the touge: {title}. Keep the redline honest.",
        "Windows down, {title} coming through. Midnight Youkai Radio.",
        "Here comes {title}. One hand on the wheel, one eye on the moon.",
        "Lights off, boost up - {title} from A-One, right now.",
        "The pass is empty and the needle is climbing: {title}.",
    ],
    "id": [
        "You are locked on Midnight Youkai Radio, streaming from the night side of the mountain.",
        "Two a.m. and still drifting - Midnight Youkai Radio, Touhou eurobeat all night.",
    ],
    "interlude": [
        "Engine idling, moon high. Stay with me - the next one is a monster.",
        "Quick breather in the hairpins. More eurobeat in a moment.",
        "Tires cooling, speakers warm. Another one is coming.",
    ],
}
TEMPLATES_ZH = {
    "intro": [
        "接下来这首，{title}。手别松开方向盘。",
        "山路夜风里，{title}，献给还没睡的你。",
        "{title}——油门踩到底，别回头看后视镜。",
        "下一首 {title}，让引擎声盖过所有心事。",
        "深夜的弯道没有人，只有 {title} 和你的转速表。",
    ],
    "id": [
        "你正在收听「{station}」，东方 Eurobeat，通宵不停。",
        "凌晨的山道，只有引擎和鼓点——{station}。",
    ],
    "interlude": [
        "先让引擎凉一凉，下一首马上就来。",
        "月亮还高，别急着关电台。",
        "轮胎凉一点，音量再大一点。",
    ],
}
_last_template = {"key": ""}

_IO_POOL = ThreadPoolExecutor(max_workers=6)


def _headers() -> dict:
    return {"Authorization": f"Bearer {cfg.MIMO_API_KEY}", "Content-Type": "application/json"}


def _post_json(url: str, payload: dict, read_timeout: float, hard_timeout: float) -> dict:
    """POST with a hard wall-clock deadline: the MiMo API occasionally stalls and
    a stuck producer thread would starve the stream."""
    fut = _IO_POOL.submit(requests.post, url, headers=_headers(), json=payload,
                          timeout=(6, read_timeout))
    try:
        resp = fut.result(timeout=hard_timeout)
    except FutureTimeout:
        raise TimeoutError("api call exceeded %.0fs" % hard_timeout)
    resp.raise_for_status()
    return resp.json()


DQUOTE = chr(34)
QUOTES = DQUOTE + "“”「」『』'"
COUNTER_RE = re.compile("[(][0-9]{1,2}[)]")
_SENT_SPLIT = re.compile("[" + "。！？!?；;." + "]+")
_LABEL_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:那么|所以|最终|总之|回答|台词|输出|答案|句子|口播|回复|例如|比如|示例|举个例子|照例|final line|answer|output|reply|spoken line)\s*[:：]?\s*",
    re.IGNORECASE)
_QUOTE_RE = re.compile("[" + QUOTES + "]([^" + QUOTES + "]{10,180})[" + QUOTES + "]")


def _mentions_title(text: str, title: str) -> bool:
    """A DJ intro must name the track (whole-word match, romaji accepted)."""
    if not title or not text:
        return True
    squash = lambda v: re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", "", v.lower())
    t, c = squash(title), squash(text)
    if not t:
        return True
    if len(t) >= 4 and t in c:
        return True
    rom = squash(romanize(title, full=True))
    if len(rom) >= 4 and rom[: max(4, len(rom) // 3)] in squash(text):
        return True
    toks = [x for x in re.split(r"\s+", title.lower()) if len(x) >= 3]
    toks += [x for x in romanize(title, full=True).lower().split() if len(x) >= 4]
    if not toks:
        return len(t) >= 3 and t[:4] in c
    hits = 0
    for tok in toks:
        if re.search(r"\b" + re.escape(tok) + r"\b", text, re.IGNORECASE):
            hits += 1
    return hits >= max(1, int(len(toks) * 0.6))


def _looks_like_plan(text: str) -> bool:
    if not text:
        return True
    if len(COUNTER_RE.findall(text)) >= 3:
        return True
    if "count" in text[:14].lower():
        return True
    if text.lstrip().startswith(("-", "*", "•", "·", "1.")):
        return True
    head = text[:24].lower()
    return any(k in head for k in ("flavor:", "structure", "tone:", "style:", "结构", "风格：", "例子"))


def _strip_label(c: str) -> str:
    c = _LABEL_RE.sub("", c).strip()
    c = re.sub("^[" + QUOTES + "]+|[" + QUOTES + "]+$", "", c).strip()
    m = re.search(r"(?:那么|最终|总之|回答|台词|输出|答案|口播|回复)\s*(?:是|为)?\s*[:：]\s*", c)
    if m and m.end() < len(c) - 10:
        c = c[m.end():].strip()
    return c


def _harvest(text: str) -> str:
    """Pull a usable spoken line out of a model monologue / reasoning dump."""
    if not text:
        return ""
    chunks = [c.strip() for c in text.strip().splitlines() if c.strip()]
    flat = []
    for c in chunks:
        parts = [x.strip() for x in _SENT_SPLIT.split(c) if x.strip()]
        flat.extend(parts or [c])
    cands = []
    for c in reversed(flat[-8:]):
        cands.append(_strip_label(c))
        for q in _QUOTE_RE.findall(c):
            cands.append(_strip_label(q))
    for q in _QUOTE_RE.findall(text):
        cands.append(_strip_label(q))
    for c in cands:
        if 12 <= len(c) <= 140 and not _BAD_LINE_RE.search(c):
            return c
    return ""


def _clean(text: str) -> str:
    text = _EMOJI_RE.sub("", text or "")
    text = text.replace("**", "").replace("*", "").replace(chr(96), "")
    text = re.sub(r"^\s*(dj|host|mystia|夜雀)\s*[:：-]\s*", "", text.strip(), flags=re.I)
    text = re.sub("^[\"“”「」『’‘']+|[\"“”「」『’‘']+$", "", text.strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_or(track: dict) -> str:
    return (track or {}).get("title", "") or "track"


def llm_line(kind: str, track: dict | None = None, extra: str = "",
            lang: str | None = None) -> tuple[str, str]:
    """Return (text, source). Falls back to a template when the API misbehaves."""
    lang = (lang or cfg.DJ_LANG or "en").lower()
    is_zh = lang.startswith("zh")
    now = datetime.now().strftime("%I:%M %p").lstrip("0")
    templates = TEMPLATES_ZH if is_zh else TEMPLATES_EN
    persona = (PERSONA_ZH if is_zh else PERSONA_EN).format(time=now, location=cfg.STATION_LOCATION)

    title = ((track or {}).get("title") or "").strip() or "an untitled youkai bootleg"
    artist = (track or {}).get("artist", "")
    album = (track or {}).get("album", "")
    if kind == "intro":
        rom = romanize(title)
        rom_full = romanize(title, full=True)
        ask = (f"今晚这首：{title}（读音：{rom}），{artist}。"
               f"说一句开曲口播，提一下这首歌。" if is_zh
               else f'Tonight: "{title}" ({rom_full}) by {artist}. '
                    f"Say one short opening DJ line that names it.")
    elif kind == "interlude":
        ask = ("说一句过渡的话，接在刚才的曲子后面，预告还有更多东方 Eurobeat。"
               if is_zh else
               "Say a short bridge line after the last track, teasing more Touhou eurobeat coming up.")
    else:
        ask = ("报一句电台台呼，提到电台名字和此刻的时间。"
               if is_zh else
               "Do a short station ID, mentioning the station name and the current hour.")
    if extra:
        ask += " " + extra

    nudge = (" Just answer with the line itself - no notes, no counting, no quotes."
             if not is_zh else " 直接给那句话，不要解释、不要数字数、不要引号。")
    limit = 140 if is_zh else 260
    for attempt in range(2):
        try:
            data = _post_json(f"{cfg.MIMO_BASE_URL}/chat/completions",
                              {"model": cfg.LLM_MODEL,
                               "messages": [
                                   {"role": "system", "content": persona},
                                   {"role": "user", "content": ask if attempt == 0 else ask + nudge}],
                               "max_tokens": 500,
                               "temperature": 1.0 if attempt == 0 else 0.8},
                              LLM_TIMEOUT, LLM_TIMEOUT + 6)
            choice = data["choices"][0]
            finish = choice.get("finish_reason") or ""
            msg = choice["message"]
            raw_content = _clean(msg.get("content") or "")
            raw_reason = _clean(msg.get("reasoning_content") or "")
            flat_content = raw_content.replace(chr(10), " ").strip()
            first_sent = ""
            if flat_content:
                parts = [x.strip() for x in _SENT_SPLIT.split(flat_content) if x.strip()]
                first_sent = (parts[0] if parts else flat_content)
            truncated = (finish == "length")
            ends_clean = (not flat_content) or flat_content[-1:] in (".!?。！？…" + chr(34) + chr(8221) + chr(12301))
            if truncated and flat_content and not ends_clean:
                log.info("[LLM] dropped truncated completion: %s", flat_content[-40:])
                flat_content, first_sent = "", ""
            if truncated and not flat_content:
                cands = [_harvest(raw_content) if raw_content else ""]
            else:
                cands = [flat_content if len(flat_content) <= limit else first_sent,
                         first_sent,
                         _harvest(raw_reason), _harvest(raw_content)]
            for cand in cands:
                cand = _strip_label(cand)
                if not cand:
                    continue
                if len(cand) > limit:
                    log.info("[LLM] rejected over-long line (%d chars)", len(cand))
                    continue
                if _looks_like_plan(cand):
                    log.info("[LLM] rejected plan fragment: %s", cand[:60])
                    continue
                if kind == "intro" and not _mentions_title(cand, title):
                    log.info("[LLM] rejected line without the track name: %s", cand[:60])
                    continue
                if len(cand) >= 12 and not _BAD_LINE_RE.search(cand):
                    return cand, "llm"
                log.info("[LLM] rejected off-format line: %s", cand[:70])
            log.warning("[LLM] no usable line (attempt %d)", attempt + 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("[LLM] failed: %s", exc)
            if "exceeded" in str(exc) or "timed out" in str(exc).lower():
                break
        time.sleep(0.4)

    pool = [x for x in templates.get(kind, templates["intro"]) if x != _last_template["key"]] or \
        templates.get(kind, templates["intro"])
    tpl = random.choice(pool)
    _last_template["key"] = tpl
    display_title = title if is_zh else romanize(title, full=True)
    return tpl.format(title=display_title, station=cfg.STATION_NAME), "template"


def tts_cache_path(text: str, voice: str, lang: str = "en") -> Path:
    key = hashlib.sha1((voice + "|" + lang + "|" + text).encode("utf-8")).hexdigest()
    return cfg.TTS_CACHE_DIR / f"{key}.wav"


def synthesize(text: str, voice: str | None = None, force: bool = False,
               lang: str | None = None, seed: int = 0,
               with_tag: bool = True) -> Path | None:
    """Synthesize with MiMo TTS. Returns a cached wav path (or None)."""
    lang = (lang or cfg.DJ_LANG or "en").lower()
    voice = voice or cfg.DJ_VOICES.get("zh" if lang.startswith("zh") else "en", cfg.DJ_VOICE)
    if lang.startswith("zh"):
        text = romanize(text, full=False)
        if with_tag:
            text = "(" + mood_tag("zh", seed) + ")" + text
    else:
        if _CJK_RE.search(text):
            text = romanize(text, full=True)
        if with_tag:
            text = "(" + mood_tag("en", seed) + ")" + text
    text = _clean(text)
    if not text:
        return None
    out = tts_cache_path(text, voice, lang)
    if out.exists() and not force and out.stat().st_size > 4000:
        return out

    context = DJ_CONTEXT_ZH if lang.startswith("zh") else DJ_CONTEXT_EN
    payload = {
        "model": cfg.TTS_MODEL,
        "messages": [{"role": "user", "content": context},
                     {"role": "assistant", "content": text}],
        "audio": {"format": "wav", "voice": voice},
    }
    try:
        data = _post_json(f"{cfg.MIMO_BASE_URL}/chat/completions", payload,
                          TTS_TIMEOUT, TTS_TIMEOUT + 6)
        audio = data["choices"][0]["message"].get("audio") or {}
        b64 = audio.get("data")
        if not b64:
            raise ValueError("no audio data in response")
        raw = base64.b64decode(b64)
        tmp = out.with_suffix(".part")
        tmp.write_bytes(raw)
        os.replace(tmp, out)
        out.with_suffix(".json").write_text(
            json.dumps({"text": text, "voice": voice, "lang": lang,
                        "created": time.time()}, ensure_ascii=False), encoding="utf-8")
        log.info("[TTS:%s] %d bytes for: %s", lang, len(raw), text[:70])
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("[TTS:%s] failed: %s", lang, exc)
        return None


def publish_on_air(wav: Path | None, meta: dict, lang: str = "en") -> str:
    """Copy the current DJ clip somewhere the web player can serve it."""
    if not wav or not wav.exists():
        return ""
    suffix = "" if lang == "en" else f"-{lang}"
    try:
        dest = cfg.ON_AIR_DIR / f"latest{suffix}.wav"
        dest.write_bytes(wav.read_bytes())
        (cfg.ON_AIR_DIR / f"latest{suffix}.json").write_text(
            json.dumps({**meta, "lang": lang,
                        "clip": f"/api/dj/latest{suffix}.wav", "at": time.time()},
                       ensure_ascii=False), encoding="utf-8")
        return f"/api/dj/latest{suffix}.wav"
    except Exception:
        return ""


def dj_line_for_track(track: dict, lang: str = "en") -> dict:
    """Generate + perform an intro line for a track. Never raises."""
    text, source = llm_line("intro", track, lang=lang)
    seed = int(hashlib.md5((title_or(track) + lang).encode("utf-8")).hexdigest()[:6], 16)
    wav = synthesize(text, lang=lang, seed=seed)
    return {"text": text, "source": source, "wav": str(wav) if wav else "",
            "clip": publish_on_air(wav, {"kind": "intro", "text": text,
                                         "track": track.get("title", "")}, lang)}


# ---------------------------------------------------------------------------
# Loudness (EBU R128 via ffmpeg, cached)
# ---------------------------------------------------------------------------
def _load_cache() -> dict:
    try:
        return json.loads(cfg.LOUDNESS_CACHE.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        cfg.LOUDNESS_CACHE.write_text(json.dumps(cache))
    except Exception:
        pass


def _rms_lufs_fallback(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            sw, ch = wf.getsampwidth(), wf.getnchannels()
            frames = wf.readframes(min(wf.getnframes(), wf.getframerate() * 60))
        if sw != 2:
            return -14.0
        n = len(frames) // 2
        if not n:
            return -14.0
        total = 0.0
        step = max(1, n // 400000)
        count = 0
        for i in range(0, n, step):
            (val,) = struct.unpack_from("<h", frames, i * 2)
            total += (val / 32768.0) ** 2
            count += 1
        rms = math.sqrt(total / max(1, count))
        if rms <= 0:
            return -30.0
        return 20 * math.log10(rms) - 3.0
    except Exception:
        return -14.0


def measure_lufs(path) -> float:
    """Integrated loudness of a file in LUFS (cached by path/mtime/size)."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return -14.0
    key = str(path)
    stamp = f"{int(st.st_mtime)}:{st.st_size}"
    cache = _load_cache()
    hit = cache.get(key)
    if hit and hit.get("stamp") == stamp:
        return float(hit["lufs"])

    lufs = None
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-t", "200", "-i", str(path),
             "-af", "ebur128", "-f", "null", "-"],
            capture_output=True, text=True, timeout=240,
        )
        matches = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", proc.stderr)
        if matches:
            lufs = float(matches[-1])
        else:
            matches = re.findall(r"integrated loudness:\s*(-?\d+(?:\.\d+)?)",
                                 proc.stderr, re.IGNORECASE)
            if matches:
                lufs = float(matches[-1])
    except Exception:
        lufs = None

    if lufs is None or lufs < -60 or lufs > 0:
        lufs = _rms_lufs_fallback(path)
    cache[key] = {"stamp": stamp, "lufs": lufs}
    _save_cache(cache)
    return lufs


def gain_for_loudness(path, target_lufs: float, max_gain: float = 18.0) -> float:
    gain = target_lufs - measure_lufs(path)
    return max(-18.0, min(max_gain, gain))


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------
def _cli() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Midnight Youkai Radio DJ engine")
    ap.add_argument("--say", help="synthesize this exact text")
    ap.add_argument("--line", choices=["intro", "id", "interlude"], help="generate+perform a DJ line")
    ap.add_argument("--track", default="", help="track title for --line intro")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--out", default="", help="copy the wav here")
    ap.add_argument("--warm", type=int, default=0, help="pre-generate N reusable lines")
    args = ap.parse_args()

    if args.say:
        p = synthesize(args.say, args.voice, force=True)
        print(p)
        if p and args.out:
            Path(args.out).write_bytes(p.read_bytes())
        return

    if args.line:
        track = {"title": args.track or "the next one", "artist": "A-One", "album": ""}
        text, source = llm_line(args.line, track)
        print(f"[{source}] {text}")
        p = synthesize(text, args.voice, force=True)
        print(p)
        if p and args.out:
            Path(args.out).write_bytes(p.read_bytes())
        return

    if args.warm:
        made = 0
        for i in range(args.warm):
            kind = ["id", "interlude", "intro"][i % 3]
            text, _ = llm_line(kind, {"title": "Midnight Touge", "artist": "A-One", "album": ""},
                               extra="用不同说法，避免和之前重复。")
            if synthesize(text):
                made += 1
            print(f"  warm {i + 1}/{args.warm}: {text}")
        print(f"[warm] {made} new clips")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()
