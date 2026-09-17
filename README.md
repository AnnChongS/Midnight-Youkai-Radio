# 東方幻想夜行 · Midnight Youkai Radio

24/7 Touhou Eurobeat internet radio with a virtual youkai DJ, a procedural
night-drive interlude bed, and a Touhou × JDM player front end.

```
Touhou_Eurobeat/*.mp3 ─┐
                       ├─▶ producer: normalise → EBU R128 loudness match → DJ voice over ducked intro
procedural bed ────────┘                │
                                        ▼
                          segment queue (crossfaded, 44.1 kHz stereo wav)
                                        │
                        feeder: real-time paced raw PCM ─▶ ffmpeg (libmp3lame 192k) ─▶ Icecast :8001 /midnight
                                        │
                          now_playing.json · history.jsonl · engine.json
                                        │
                             web player :9999  (proxies the stream, renders the UI)
```

## What was wrong before

| Symptom | Cause | Fix |
| --- | --- | --- |
| Stream cut out every few seconds | The library mixes 44.1 kHz and 48 kHz files and the encoder was piped `-c copy`, so the sample rate changed mid-stream and decoders broke. | Every source is resampled to **44.1 kHz / stereo / s16le** before it reaches the encoder; the encoder runs in one long-lived process. |
| Silence between tracks | Whole tracks were queued as one MP3 chunk; `queue.Full` dropped them and there was no pre-buffer. | Producer builds segments ~2 tracks ahead (blocking queue, nothing is dropped), each segment starts with a 3 s **crossfade** from the previous tail, and a procedural **eurobeat bed** covers any gap. |
| DJ voice was empty | `mimo-v2.5-pro` sometimes returns an empty `content` (text only in `reasoning_content`), so TTS synthesised nothing. | Content fallback + plausibility filter + template fallback; TTS clips are cached on disk so the stream never waits for the API. |
| Volume jumps between tracks, DJ hard to hear | No loudness normalisation, no ducking. | Per-track EBU R128 gain to −11.5 LUFS (cached), voice to −8.5 LUFS, 13 dB ducking envelope written by ffmpeg for the length of the line. |
| Ugly player | — | New poster-style UI: back-lit youkai silhouettes per track, tachometer progress, danmaku analyser, drifting coupe, sakura/danmaku scene. |

## Quick start

```bash
./stop_radio.sh      # kill anything already running (also done by start)
./start_radio.sh     # icecast → web player → streaming engine
```

* player: <http://localhost:9999>
* stream: <http://localhost:8001/midnight>
* logs:   `logs/`

Requirements: `ffmpeg`, `ffprobe`, `icecast2`, `python3` (flask, requests,
waitress — `start_radio.sh` installs the python ones into `./vendor` if needed).

## Files

| File | Role |
| --- | --- |
| `radio_config.py` | station identity, audio constants, track-name parser, youkai roster + keyword mapping |
| `dj_engine.py` | MiMo LLM lines + MiMo TTS performance, disk cache, R128 loudness helpers |
| `bed.py` | renders the procedural 172 BPM eurobeat interlude loop |
| `main_streamer.py` | producer / feeder / metadata threads, the streaming engine |
| `web_player.py` | Flask + waitress: UI, stream proxy, JSON APIs |
| `static/index.html`, `style.css`, `app.js`, `art.js` | the player front end (scene, tachometer, analyser, youkai art) |
| `icecast_midnight.xml` | icecast config (256 KB burst, 1 MB queue, CORS headers) |
| `start_radio.sh` / `stop_radio.sh` | lifecycle |
| `download_tracks.py` | yt-dlp grabber for the A-One Touhou Eurobeat volumes |

## Progress bar accuracy (why it used to run ahead)

Every listener hears audio that was encoded a moment earlier, so a clock-driven
progress bar always finishes before the song does. Two things caused it:

1. **Icecast burst size.** `burst-size` was 256 KB, i.e. every new listener got
   ~11 seconds of *past* audio and stayed ~11 s behind live forever. It is now
   64 KB (~2.7 s).
2. **Unmeasured latency.** The player now *measures* the remaining delay instead
   of guessing it.

The engine mixes an inaudible **16 kHz three-pulse marker** (3 x 200 ms at
-34 dBFS, ~30 dB above the music's 16 kHz floor) into the head of every track,
and can inject one on demand. The browser watches that band with a dedicated
AnalyserNode (`fftSize` 4096, no smoothing); when it hears the burst it knows
exactly when the audio it is *playing* passed a known point, so it can compute
the true encoder -> icecast -> buffer latency. Calibration runs once when
playback starts, is refreshed at every track start, and matches markers by pulse
pattern plus a consistency check (+/-2.5 s) so music cymbals cannot fake it. The
needle and the elapsed time are then driven by the *heard* position, so they end
when the music ends.

* Disable the marker (bit-perfect listening) with `MYR_MARKER=0` - the player
  falls back to measuring the browser buffer instead.
* Check from the browser console: `window.__myr.state.measuredLag` is the
  measured pipeline delay in seconds.

## DJ line quality gates

mimo-v2.5-pro sometimes answers with its own reasoning instead of the line
(mostly in Chinese), so every candidate has to survive four checks before TTS:
it must not match the meta/rule-echo blacklist, must not look like a plan
fragment (bullets, "Count: ... (1) (2) (3)", "flavor:" / "结构：" style notes),
must stay under 140 (zh) / 260 (en) characters, and must actually name the track
(whole-word match). If both attempts fail, or the API stalls past its hard
deadline, the station falls back to a varied template instead of reading its own
instructions on air. Real lines are recovered from the reasoning dump when the
model buries the answer there.

## Voice style control (how the DJ is asked to perform)

Three layers, all following the MiMo speech-synthesis guide (target text in the
assistant message, style instructions in the user message, style tags inside the
spoken text):

1. **Natural-language instruction** (user message) - performance only, never a
   voice identity. Describing a "voice" while also passing a preset voice makes
   the model re-design the timbre (that is how Chloe/冰糖 occasionally drifted
   into a mature "big sister" read):
   - EN: `Speak as a bright, upbeat late-night radio DJ: medium-fast pace, high energy, playful and smiling, close to the microphone.`
   - ZH: `用轻快上扬的电台DJ语气念这段话：语速偏快、情绪高涨有活力，尾音带笑意，贴近话筒说话。`
2. **Overall style tag** at the very start of the spoken text, rotated per track
   (deterministic by title hash) so the station never sounds monotonous:
   - EN: `(excited, playful)` `(lively, confident)` `(playful, magnetic)` `(energetic, upbeat)` `(bright, cheerful)`
   - ZH: `(兴奋 俏皮)` `(活泼 热情)` `(干练 磁性)` `(兴奋 活泼)` `(俏皮 明快)` `(热情 律动)`
3. **Fine-grained tags** can be dropped anywhere in the line (`(笑)` `(拖音)` `[pause]` …) - not used by
   default to keep the delivery steady.

Tags are injected only into the TTS request; the text shown in the player stays clean.
Because asking for "25 words max" made the model count words inside its reasoning
and burn the whole token budget, the length limit is now soft ("keep it short")
and completions cut by the token limit are discarded.

### Japanese titles

The English DJ must not emit kana/kanji, so the prompt hands it the Hepburn form
of the title and, as a guarantee, any CJK left in the spoken text is converted by
pykakasi (`vendor/pykakasi`) before synthesis. The Chinese DJ keeps kanji (readable
for Chinese listeners) but kana is romanised the same way - e.g. 深奥イレギュラー
becomes `shin'ou iregyuraa` for Chloe and `深奥iregyuraa` for 冰糖.

## Two stations, one engine (English / 中文)

The same engine feeds **two mounts at once**, in lock step, so both languages hear
the same song at the same moment - only the DJ voice differs:

| | English | 中文 |
| --- | --- | --- |
| page | `/` | `/cn` |
| stream | `/stream` -> `/midnight` | `/stream-zh` -> `/midnight-cn` |
| DJ | Mystia Lorelei, voice `Chloe` | 米斯蒂娅·萝蕾拉, voice `冰糖` |
| on-air clip | `latest.wav` | `latest-zh.wav` |

Every track is decoded/trimmed/measured **once**, then mixed twice (one DJ line
per language, generated in parallel) and crossfaded per mount. The feeder writes
both ffmpeg pipes from the same 250 ms block, so the two stations cannot drift.
The UI is fully localised (labels, ticker, youkai names/epithets, numbers) and
each page measures its own pipeline latency for the progress bar.

```bash
MYR_DJ_VOICE=Chloe        # English voice: Chloe, Mia, Dean, Milo
MYR_DJ_VOICE_ZH=冰糖     # 中文嗓音: 冰糖, 茉莉, 白桦, 苏打
MYR_DJ_LANGS=en,zh      # or en / zh to run a single station
```

## The virtual DJ

Mystia Lorelei (夜雀) introduces every track over its intro. Voice and
language are configurable:

```bash
MYR_DJ_VOICE=Chloe  ./start_radio.sh        # Chloe, Mia, Dean, Milo, 冰糖, 茉莉, 白桦, 苏打
MYR_DJ_LANG=zh    ./start_radio.sh        # Chinese DJ instead of English
```

Warm the cache (optional, avoids a slow first hour):

```bash
python3 dj_engine.py --warm 9                       # reusable station IDs / interludes
python3 dj_engine.py --line intro --track "U.N. Owen Was Her"
python3 dj_engine.py --say "Midnight Youkai Radio. Keep the redline honest."
```

Every line is cached in `cache/tts/` keyed by `sha1(voice|lang|text)`, and the
currently playing clip is published at `/api/dj/current.wav` (the **REPLAY**
button in the player).

## Tuning

All knobs are environment variables (see `radio_config.py`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MYR_TARGET_LUFS` | `-11.5` | music loudness |
| `MYR_VOICE_LUFS` | `-8.5` | DJ voice loudness |
| `MYR_BED_LUFS` | `-19.0` | interlude bed loudness |
| `MYR_DUCK_DB` | `-13.0` | ducking depth under the voice |
| `MYR_CROSSFADE_MS` | `3000` | crossfade between tracks |
| `MYR_MARKER` | `1` | inaudible 16 kHz sync marker for exact progress |
| `MYR_QUEUE_AHEAD` | `2` | segments prepared ahead |
| `MYR_ICECAST_PORT` / `MYR_WEB_PORT` | `8001` / `9999` | ports |
| `MYR_TRACK_DIR` | `Touhou_Eurobeat` | music library (re-scanned live, half-downloaded files are skipped) |

## APIs

| Endpoint | Returns |
| --- | --- |
| `GET /stream` | same-origin mp3 relay of the mount (lets the browser run an AnalyserNode) |
| `GET /api/now-playing` | now playing, progress, DJ line, listeners, engine state, upcoming, history |
| `GET /api/station` | station identity, youkai roster with art specs |
| `GET /api/dj/current.wav` | the DJ voice clip that is on air |
| `GET /api/health` | icecast + engine health, library size |

Icecast's own metadata is updated per track (`/admin/metadata`), so VLC and
other players show `Artist - Title` too, and `http://localhost:8001/status-json.xsl`
stays in sync with the UI.

## Notes

* Track/character pairing is thematic (keywords such as *U.N. Owen*, *Bloody*,
  *Lunatic*, *Faith*, *Ice* → Flandre, Remilia, Kaguya, Sanae, Cirno…), otherwise
  a stable hash picks a youkai so every track always gets the same artwork.
* The interlude bed is synthesised from scratch (kick / snare / hats / saw bass /
  pluck arp / pad) — it is original, non-infringing, and generated once into
  `cache/bed.wav`.
* Music files are the user's own download; nothing is redistributed by this repo.
