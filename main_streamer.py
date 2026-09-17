#!/usr/bin/env python3
"""Midnight Youkai Radio — continuous streaming engine.

Design goals
------------
* Never goes quiet: a procedural eurobeat bed keeps the mount alive while the
  next track is being prepared, so listeners never hear drop-outs.
* One fixed on-air format: every source is resampled to 44.1 kHz / stereo
  before it reaches the encoder (mixed sample rates used to break decoders).
* Loudness matched: every track is EBU R128 measured and gain-corrected; the DJ
  voice sits above the music with side-chain ducking done inside ffmpeg.
* Crossfaded: each segment starts with the previous track's tail blended in,
  so the stream is a continuous DJ mix instead of a file-per-file playlist.
"""

import argparse
import audioop
import fcntl
import json
import logging
import os
import queue
import random
import re
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor

import bed as bed_mod
import dj_engine
import marker
import radio_config as cfg

log = logging.getLogger("midnight")

FADE_MS = 1400
MANIFEST = cfg.STATE_DIR / "engine.json"
LOCK_PATH = cfg.STATE_DIR / "engine.lock"
_lock_handle = None


def acquire_singleton():
    """Only one streaming engine may own the mount and state files."""
    global _lock_handle
    handle = open(LOCK_PATH, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[engine] another {cfg.STATION_NAME} engine already holds {LOCK_PATH} - exiting",
              file=sys.stderr)
        sys.exit(2)
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    try:
        state = json.loads(MANIFEST.read_text())
        age = time.time() - float(state.get("updated_at") or 0)
        if age < 20:
            print(f"[engine] WARNING: {MANIFEST} was updated {age:.0f}s ago by another "
                  f"process - a stray instance may still be running (run stop_radio.sh)",
                  file=sys.stderr)
    except Exception:
        pass
    return handle



def now() -> float:
    return time.monotonic()


def probe_duration_ms(path) -> int:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        return int(float(out) * 1000)
    except Exception:
        return 0


def run_ffmpeg(args: list, timeout: int = 900) -> bool:
    try:
        proc = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            log.warning("[ffmpeg] %s", (proc.stderr or "").strip()[-600:])
        return proc.returncode == 0
    except Exception as exc:  # noqa: BLE001
        log.warning("[ffmpeg] failed: %s", exc)
        return False


def slugify(text: str, limit: int = 42) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s[:limit] or "track"


def is_stable(path, wait: float = 1.2) -> bool:
    """True when a file has stopped growing (download finished)."""
    try:
        first = os.path.getsize(path)
    except OSError:
        return False
    if first < 200_000:
        return False
    time.sleep(wait)
    try:
        return os.path.getsize(path) == first
    except OSError:
        return False


class Segment:
    """One broadcast item, rendered once per language (one mount each)."""

    __slots__ = ("paths", "metas", "clips", "duration_ms", "kind")

    def __init__(self, paths: dict, metas: dict, duration_ms: int, kind: str = "track",
                 clips: dict | None = None):
        self.paths = {l: Path(p) for l, p in paths.items()}
        self.metas = dict(metas)
        self.clips = dict(clips or {})
        self.duration_ms = duration_ms
        self.kind = kind

    @property
    def path(self):
        return self.paths.get("en") or next(iter(self.paths.values()))

    @property
    def meta(self):
        return self.metas.get("en") or next(iter(self.metas.values()))

    @property
    def dj_clip(self):
        return self.clips.get("en", "")

    @property
    def files(self):
        seen, out = set(), []
        for p in self.paths.values():
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def langs(self):
        return list(self.paths)


class Engine:
    def __init__(self, voice: bool = True, crossfade: int = cfg.CROSSFADE_MS):
        self.voice = voice
        self.crossfade_ms = crossfade
        self.segments: queue.Queue = queue.Queue(maxsize=cfg.QUEUE_AHEAD)
        self.stop = threading.Event()
        self.next_at = now()
        self.current = None
        self.current_offset = 0
        self._bed_item = None
        self._last_status = 0.0
        self.seq = 0
        self.counters = {"built": 0, "played": 0, "underruns": 0, "restarts": 0,
                         "tracks_skipped": 0, "dj_lines": 0}
        self.started = time.time()
        self.meta_queue: queue.Queue = queue.Queue()
        self.history: list = []
        self.lock = threading.Lock()
        self._icecast_ready = False
        self._fail_streak = 0
        self._marker_pcm = b""
        self.procs: dict = {l: None for l in cfg.DJ_LANGS}
        self.offsets: dict = {l: 0 for l in cfg.DJ_LANGS}
        self.inject: dict = {l: {"pos": 0, "left": 0} for l in cfg.DJ_LANGS}
        self.pending_tails: dict = {l: cfg.SEGMENT_DIR /
                                  ("_pending_tail.wav" if l == "en" else "_pending_tail-" + l + ".wav")
                                  for l in cfg.DJ_LANGS}
        self._inject_left = 0
        self._inject_pos = 0

    # ---------------------------------------------------------------- helpers
    def bed_segment(self) -> Segment:
        if self._bed_item is None:
            dur = probe_duration_ms(cfg.BED_FILE)
            paths = {l: cfg.BED_FILE for l in cfg.DJ_LANGS}
            metas = {}
            for l in cfg.DJ_LANGS:
                metas[l] = {"kind": "bed", "title": "Youkai Mountain Night Drive",
                            "artist": cfg.mount_for(l)["label"], "album": "interlude",
                            "duration_ms": dur, "character_key": "mystia",
                            "character": {"key": "mystia", **cfg.CHARACTERS["mystia"]},
                            "dj_text": "", "lang": l}
            self._bed_item = Segment(paths, metas, dur, "bed")
        return self._bed_item
    def write_pcm(self, lang: str, data: bytes) -> bool:
        proc = self.procs.get(lang)
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, AttributeError, ValueError) as exc:
            log.warning("[Feeder:%s] pipe write failed: %s", lang, exc)
            return False
    def wait_for_icecast(self, timeout: float = 25.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline and not self.stop.is_set():
            try:
                if requests.get(cfg.ICECAST_STATUS_URL, timeout=3).status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1.0)
        return False

    def start_ffmpeg(self, lang: str) -> bool:
        if not self._icecast_ready:
            if not self.wait_for_icecast():
                log.error("[Feeder] icecast not answering on %s:%d", cfg.ICECAST_HOST, cfg.ICECAST_PORT)
                self._fail_streak += 1
                time.sleep(min(6.0, 1.5 * self._fail_streak))
                return False
            self._icecast_ready = True
            self._fail_streak = 0
        m = cfg.mount_for(lang)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
            "-f", "s16le", "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
            "-i", "pipe:0",
            "-c:a", "libmp3lame", "-b:a", cfg.MP3_BITRATE,
            "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
            "-f", "mp3", "-content_type", "audio/mpeg",
            "-ice_name", m["label"], "-ice_genre", cfg.STATION_GENRE,
            "-ice_description", cfg.STATION_TAGLINE,
            "-ice_url", f"http://{cfg.ICECAST_HOST}:{cfg.WEB_PORT}{m['web_path']}",
            cfg.source_url(lang),
        ]
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as exc:  # noqa: BLE001
            log.error("[Feeder:%s] cannot start ffmpeg: %s", lang, exc)
            return False
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()
        self.procs[lang] = proc
        time.sleep(0.4)
        if proc.poll() is not None:
            log.error("[Feeder:%s] ffmpeg exited immediately (code=%s)", lang, proc.returncode)
            self.procs[lang] = None
            self._icecast_ready = False
            return False
        self.next_at = now()
        log.info("[Feeder:%s] ffmpeg -> %s", lang, cfg.source_url(lang))
        return True
    @staticmethod
    def _drain_stderr(proc) -> None:
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    log.debug("[ffmpeg] %s", line)
        except Exception:
            pass

    def metadata_worker(self) -> None:
        while not self.stop.is_set():
            try:
                lang, track = self.meta_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                requests.get(
                    f"http://{cfg.ICECAST_HOST}:{cfg.ICECAST_PORT}/admin/metadata",
                    params={"mount": cfg.mount_for(lang)["mount"], "mode": "updinfo",
                            "song": f"{track.get('artist','')} - {track.get('title','')}".strip(" -")},
                    auth=(cfg.ICECAST_ADMIN_USER, cfg.ICECAST_ADMIN_PASSWORD),
                    timeout=8,
                )
            except Exception:
                pass
    def announce(self, item: Segment, started_at: float) -> None:
        texts, clips = {}, {}
        for lang in item.langs():
            meta = item.metas.get(lang, {})
            m = cfg.mount_for(lang)
            payload = {
                "title": meta.get("title", ""),
                "artist": meta.get("artist", ""),
                "album": meta.get("album", ""),
                "kind": item.kind,
                "duration_ms": item.duration_ms,
                "started_at": started_at,
                "dj_text": meta.get("dj_text", ""),
                "dj_source": meta.get("dj_source", "template"),
                "dj_clip": "",
                "character": meta.get("character", cfg.CHARACTERS["mystia"]),
                "character_key": meta.get("character_key", "mystia"),
                "station": m["label"],
                "lang": lang,
                "stream": f"/stream{'' if lang == 'en' else '-' + lang}",
                "mount": m["mount"],
            }
            clip_file = item.clips.get(lang)
            if clip_file and Path(clip_file).exists():
                try:
                    suffix = "" if lang == "en" else f"-{lang}"
                    (cfg.ON_AIR_DIR / f"latest{suffix}.wav").write_bytes(Path(clip_file).read_bytes())
                    payload["dj_clip"] = f"/api/dj/clip/{Path(clip_file).name}"
                    (cfg.ON_AIR_DIR / f"latest{suffix}.json").write_text(
                        json.dumps({"kind": item.kind, "text": meta.get("dj_text", ""),
                                    "track": meta.get("title", ""), "lang": lang,
                                    "clip": payload["dj_clip"], "at": started_at},
                                   ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            cfg.write_now_playing(payload, lang)
            texts[lang] = payload["dj_text"]
            clips[lang] = payload["dj_clip"]
            if item.kind != "bed":
                self.meta_queue.put((lang, payload))
        if item.kind == "track":
            meta = item.meta
            entry = {"title": meta.get("title", ""), "artist": meta.get("artist", ""),
                     "album": meta.get("album", ""), "started_at": started_at,
                     "character_key": meta.get("character_key", "mystia"),
                     "character": meta.get("character", {}).get("name", ""),
                     "color": meta.get("character", {}).get("color", "#ff5c8a"),
                     "dj_text": texts, "dj_clip": clips}
            with self.lock:
                self.history.append(entry)
                del self.history[:-60]
            cfg.append_history(entry)
    def feeder(self) -> None:
        log.info("[Feeder] started for %s", ", ".join(cfg.DJ_LANGS))
        while not self.stop.is_set():
            missing = [l for l in cfg.DJ_LANGS
                       if self.procs.get(l) is None or self.procs[l].poll() is not None]
            if missing:
                for lang in missing:
                    self.start_ffmpeg(lang)
                time.sleep(2)
                continue
            item = None
            try:
                item = self.segments.get(timeout=1.0)
                with self.lock:
                    self.current_offset = 0
                for l in cfg.DJ_LANGS:
                    self.offsets[l] = 0
            except queue.Empty:
                if self.current is None:
                    item = self.bed_segment()
                    with self.lock:
                        self.current_offset = 0
                    self.counters["underruns"] += 1
                    n = self.counters["underruns"]
                    if n in (1, 5) or n % 25 == 0:
                        log.info("[Feeder] underrun #%d - filling with station bed", n)
            if item is None:
                self._status()
                continue

            self.current = item
            started_at = time.time() + cfg.PACING_LEAD_S
            self.announce(item, started_at)
            log.info("[Feeder] >> %s (%s, %.1fs) [%s]", item.meta.get("title", item.path.name),
                     item.kind, item.duration_ms / 1000, "/".join(item.langs()))
            try:
                finished = self.play(item)
            except Exception as exc:  # noqa: BLE001
                log.error("[Feeder] play error: %s", exc, exc_info=True)
                finished = False
            if finished:
                self.counters["played"] += 1
                self.current = None
                self.cleanup(item)
            self._status()

    def play(self, item: Segment) -> bool:
        """Stream one segment to every mount in lock step (same song, same moment)."""
        readers = {}
        for lang in item.langs():
            try:
                readers[lang] = wave.open(str(item.paths[lang]), "rb")
            except Exception as exc:  # noqa: BLE001
                log.warning("[Feeder] cannot open %s: %s", item.paths[lang], exc)
        if not readers:
            return True
        block_frames = int(cfg.SAMPLE_RATE * cfg.BLOCK_MS / 1000)
        totals = {l: wf.getnframes() for l, wf in readers.items()}
        frames = {}
        for l, wf in readers.items():
            if wf.getframerate() != cfg.SAMPLE_RATE or wf.getnchannels() != cfg.CHANNELS:
                log.warning("[Feeder] %s is not %dHz/%dch - skipping", item.paths[l].name,
                            cfg.SAMPLE_RATE, cfg.CHANNELS)
                wf.close()
                del readers[l]
                continue
            off = min(self.offsets.get(l, 0), max(0, totals[l] - 1))
            if off:
                try:
                    wf.setpos(off)
                except Exception:
                    pass
            frames[l] = off
        if not readers:
            return True
        primary = "en" if "en" in readers else next(iter(readers))
        total = totals[primary]
        fade_from = max(frames[primary], total - int(cfg.SAMPLE_RATE * FADE_MS / 1000))
        playable = max(1.0, float(total - fade_from))
        ok = True
        while not self.stop.is_set():
            data_p = readers[primary].readframes(block_frames)
            if not data_p:
                break
            n = len(data_p) // (cfg.SAMPLE_WIDTH * cfg.CHANNELS)
            ramp = None
            if frames[primary] >= fade_from and self.segments.empty() and item.kind != "bed":
                ramp = 1.0 - ((frames[primary] + n - fade_from) / playable)
            for lang, wf in readers.items():
                data = data_p if lang == primary else wf.readframes(block_frames)
                if not data:
                    continue
                if ramp is not None:
                    try:
                        data = audioop.mul(data, cfg.SAMPLE_WIDTH, max(0.0, min(1.0, ramp)))
                    except Exception:
                        pass
                data = self._maybe_inject(lang, data)
                if not self.write_pcm(lang, data):
                    self.offsets[lang] = frames[lang]
                    self.counters["restarts"] += 1
                    self._icecast_ready = False
                    try:
                        self.procs[lang].kill()
                    except Exception:
                        pass
                    self.procs[lang] = None
                    ok = False
                else:
                    self.offsets[lang] = frames[lang] + n
            for lang in readers:
                frames[lang] += n
            with self.lock:
                self.current_offset = frames[primary]
            if not ok:
                for wf in readers.values():
                    try:
                        wf.close()
                    except Exception:
                        pass
                time.sleep(0.6)
                return False
            self.next_at += n / cfg.SAMPLE_RATE
            for _l in readers:
                self._check_calibration(_l)
            self._status()
            drift = self.next_at - cfg.PACING_LEAD_S - now()
            if drift > 0:
                time.sleep(min(drift, 2.0))
            else:
                self.next_at = now() + cfg.PACING_LEAD_S
        for wf in readers.values():
            try:
                wf.close()
            except Exception:
                pass
        return frames[primary] >= total - 16
    def cleanup(self, item: Segment) -> None:
        for f in item.files:
            if f.name.startswith("_pending_tail") or f == cfg.BED_FILE:
                continue
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
    def _status(self) -> None:
        if now() - self._last_status < 5:
            return
        self._last_status = now()
        cur = self.current
        try:
            upcoming = [{"title": s.meta.get("title", ""), "artist": s.meta.get("artist", ""),
                         "kind": s.kind,
                         "color": (s.meta.get("character") or {}).get("color", "#ff9ad5")}
                        for s in list(self.segments.queue)[:6]]
        except Exception:
            upcoming = []
        alive = {l: bool(self.procs.get(l) and self.procs[l].poll() is None) for l in cfg.DJ_LANGS}
        try:
            MANIFEST.write_text(json.dumps({
                "uptime_s": int(time.time() - self.started),
                "counters": self.counters,
                "queue_depth": self.segments.qsize(),
                "upcoming": upcoming,
                "current": (cur.meta.get("title") if cur else None),
                "current_kind": (cur.kind if cur else None),
                "current_by_lang": ({l: cur.metas.get(l, {}).get("title") for l in cur.langs()}
                                    if cur else {}),
                "ffmpeg_alive": all(alive.values()),
                "mounts": alive,
                "updated_at": time.time(),
            }))
        except Exception:
            pass

    def next_track(self, bag: list, last: str) -> str:
        """Shuffle-bag picker that rebuilds when the library changes on disk."""
        tracks = [t for t in cfg.list_tracks() if not t.endswith(".part")]
        known = getattr(self, "_bag_source", None)
        if known != set(tracks) or not bag:
            random.shuffle(tracks)
            bag[:] = tracks
            self._bag_source = set(tracks)
        while bag:
            path = bag.pop(0)
            if path == last or not os.path.exists(path):
                continue
            return path
        return ""

    @staticmethod
    def prune_caches(max_onair: int = 16, max_tts: int = 600) -> None:
        try:
            clips = sorted(cfg.ON_AIR_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
            for stale in clips[max_onair:]:
                stale.unlink(missing_ok=True)
            if len(list(cfg.TTS_CACHE_DIR.glob("*.wav"))) > max_tts:
                def stamp(f):
                    try:
                        return f.stat().st_atime
                    except OSError:
                        return 0
                for stale in sorted(cfg.TTS_CACHE_DIR.glob("*.wav"), key=stamp)[:200]:
                    stale.unlink(missing_ok=True)
                    stale.with_suffix(".json").unlink(missing_ok=True)
        except Exception:
            pass
    def producer(self) -> None:
        log.info("[Producer] started (voice=%s, crossfade=%dms)", self.voice, self.crossfade_ms)
        bag: list = []
        last = ""
        while not self.stop.is_set():
            try:
                path = self.next_track(bag, last)
                if not path:
                    item = self.build_interlude()
                    if item is None:
                        time.sleep(5)
                        continue
                    self.segments.put(item, timeout=3600)
                    continue
                if not is_stable(path):
                    log.info("[Producer] %s still downloading — skipping for now", Path(path).name)
                    self.counters["tracks_skipped"] += 1
                    time.sleep(2)
                    continue
                item = self.build_track(path)
                last = path
                if item is None:
                    time.sleep(1)
                    continue
                with self.lock:
                    self.counters["built"] += 1
                self.prune_caches()
                self.segments.put(item, timeout=3600)
            except Exception as exc:  # noqa: BLE001
                log.error("[Producer] error: %s", exc, exc_info=True)
                time.sleep(3)

    @staticmethod
    def duck_expr(pos_ms: int, dur_ms: int, fade_ms: int, duck_db: float) -> str:
        """Sample-accurate ducking envelope for the `volume` filter (eval=frame)."""
        target = 10 ** (duck_db / 20.0)
        fade = max(0.05, fade_ms / 1000.0)
        a = max(0.0, pos_ms / 1000.0 - fade)
        b = pos_ms / 1000.0
        c = pos_ms / 1000.0 + dur_ms / 1000.0
        d = c + fade
        return (f"if(lt(t,{a:.3f}),1,"
                f"if(lt(t,{b:.3f}),1-{1 - target:.4f}*(t-{a:.3f})/{fade:.3f},"
                f"if(lt(t,{c:.3f}),{target:.4f},"
                f"if(lt(t,{d:.3f}),{target:.4f}+{1 - target:.4f}*(t-{c:.3f})/{fade:.3f},1))))")

    def _mix(self, music: Path, voice, voice_pos_ms: int, music_db: float,
             voice_db: float, out: Path, with_marker: bool = True) -> bool:
        wide = (f"aformat=sample_fmts=fltp:sample_rates={cfg.SAMPLE_RATE}:"
                f"channel_layouts=stereo")
        parts, inputs = [], []
        if voice:
            try:
                voice_dur = probe_duration_ms(voice)
            except Exception:
                voice_dur = 4000
            expr = self.duck_expr(voice_pos_ms, max(500, voice_dur), cfg.DUCK_FADE_MS, cfg.DUCK_DB)
            parts.append(f"[0:a]{wide},volume={music_db:.2f}dB,"
                         f"volume=volume='{expr}':eval=frame[m]")
            parts.append(f"[1:a]{wide},volume={voice_db:.2f}dB,"
                         f"adelay={voice_pos_ms}|{voice_pos_ms}[v]")
            parts.append("[m][v]amix=inputs=2:duration=longest:normalize=0,"
                         "alimiter=limit=0.95[mix]")
            inputs = ["-i", str(music), "-i", str(voice)]
        else:
            parts.append(f"[0:a]{wide},volume={music_db:.2f}dB,"
                         f"alimiter=limit=0.95[mix]")
            inputs = ["-i", str(music)]
        last = "mix"
        if with_marker and cfg.MARKER_ENABLED and cfg.MARKER_FILE.exists():
            inputs += ["-i", str(cfg.MARKER_FILE)]
            idx = len(inputs) // 2 - 1
            parts.append(f"[{idx}:a]{wide},adelay={cfg.MARKER_AT_MS}|{cfg.MARKER_AT_MS}[mk]")
            parts.append(f"[{last}][mk]amix=inputs=2:duration=longest:normalize=0[out]")
            last = "out"
        graph = ";".join(parts)
        return run_ffmpeg(inputs + ["-filter_complex", graph, "-map", f"[{last}]",
                                    "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
                                    "-c:a", "pcm_s16le", str(out)])

    def _check_calibration(self, lang: str) -> None:
        req = cfg.CALIB_REQUESTS.get(lang)
        try:
            if not (cfg.MARKER_ENABLED and req is not None and req.exists()):
                return
            data = json.loads(req.read_text())
            req.unlink(missing_ok=True)
            st = self.inject[lang]
            st["pos"], st["left"] = 0, len(self._marker_pcm)
            cfg.CALIB_RESULTS[lang].write_text(json.dumps({
                "nonce": data.get("nonce"), "lang": lang, "injected_at": time.time(),
                "position_s": round(self.offsets.get(lang, 0) / cfg.SAMPLE_RATE, 2)}))
            log.info("[Calib:%s] marker injected for nonce=%s", lang, data.get("nonce"))
        except Exception as exc:
            log.warning("[Calib:%s] %s", lang, exc)
    def _maybe_inject(self, lang: str, data: bytes) -> bytes:
        st = self.inject.get(lang)
        if not st or st["left"] <= 0:
            return data
        chunk = self._marker_pcm[st["pos"]:st["pos"] + len(data)]
        if not chunk:
            st["left"] = 0
            return data
        st["pos"] += len(chunk)
        st["left"] -= len(chunk)
        try:
            return audioop.add(data, chunk.ljust(len(data), bytes(1)), cfg.SAMPLE_WIDTH)
        except Exception:
            return data
    @staticmethod
    def _mean_db(path) -> float | None:
        """Mean level of a short file in dBFS (ffmpeg volumedetect)."""
        try:
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                 "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=60)
            m = re.findall(r"mean_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", proc.stderr)
            if not m:
                return None
            return None if "inf" in m[-1] else float(m[-1])
        except Exception:
            return None

    def _crossfade(self, full: Path, out: Path, lang: str = "en") -> bool:
        xf = self.crossfade_ms / 1000.0
        fi = 0.45
        wide = f"aformat=sample_fmts=fltp:sample_rates={cfg.SAMPLE_RATE}:channel_layouts=stereo"
        tail_in = self.pending_tails[lang]
        blend = False
        if tail_in.exists() and self.crossfade_ms > 0:
            mean = self._mean_db(tail_in)
            blend = mean is not None and mean > -38.0
            if not blend:
                log.debug("[Producer] %s tail silent (%.1f dB) - hard cut", lang, mean or -99)
        if blend:
            graph = (
                f"[1:a]{wide},atrim=0:{xf:.3f},asetpts=PTS-STARTPTS[fh];"
                f"[1:a]{wide},atrim={xf:.3f},asetpts=PTS-STARTPTS[fb];"
                f"[0:a]{wide},volume=volume='if(lt(t\,{xf:.3f})\,pow(1-t/{xf:.3f}\,1.15)\,0)':eval=frame[t];"
                f"[fh]volume=volume='if(lt(t\,{fi:.3f})\,pow(t/{fi:.3f}\,0.35)\,1)':eval=frame[fi];"
                f"[t][fi]amix=inputs=2:duration=longest:normalize=0,{wide}[blend];"
                f"[blend][fb]concat=n=2:v=0:a=1[x]"
            )
            ok = run_ffmpeg(["-i", str(tail_in), "-i", str(full),
                             "-filter_complex", graph, "-map", "[x]",
                             "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
                             "-c:a", "pcm_s16le", str(out)])
            if not ok:
                return False
        else:
            if not run_ffmpeg(["-i", str(full), "-ar", str(cfg.SAMPLE_RATE), "-ac",
                               str(cfg.CHANNELS), "-c:a", "pcm_s16le", str(out)]):
                return False
        try:
            tmp = tail_in.with_name(tail_in.stem + "." + lang + ".new.wav")
            if run_ffmpeg(["-sseof", f"-{xf:.3f}", "-i", str(full),
                           "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
                           "-c:a", "pcm_s16le", str(tmp)]):
                if tmp.exists() and tmp.stat().st_size > 40000:
                    os.replace(tmp, tail_in)
        except Exception:
            pass
        return True
    def build_track(self, path: str) -> Segment | None:
        t0 = time.time()
        parsed = cfg.parse_track_name(path)
        character = cfg.character_for(parsed["title"], seed=Path(path).name)
        self.seq += 1
        tag = f"{self.seq:04d}-{slugify(parsed['title'])}"
        norm = cfg.SEGMENT_DIR / f"{tag}.src.wav"

        trim = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.15,"
                "areverse,"
                "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.35,"
                "areverse")
        if not run_ffmpeg(["-i", path, "-af", trim,
                           "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
                           "-c:a", "pcm_s16le", str(norm)]):
            norm.unlink(missing_ok=True)
            return None
        dur_ms = probe_duration_ms(norm)
        if dur_ms < 20000:
            log.info("[Producer] %s too short (%.1fs) - skipping", Path(path).name, dur_ms / 1000)
            norm.unlink(missing_ok=True)
            return None

        lines = {}
        if self.voice:
            with ThreadPoolExecutor(max_workers=max(1, len(cfg.DJ_LANGS))) as pool:
                futs = {lang: pool.submit(dj_engine.dj_line_for_track, parsed, lang)
                        for lang in cfg.DJ_LANGS}
                for lang, fut in futs.items():
                    try:
                        lines[lang] = fut.result(timeout=200)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("[Producer] %s DJ line failed: %s", lang, exc)
                        lines[lang] = {"text": "", "wav": "", "source": "error", "clip": ""}
            self.counters["dj_lines"] += sum(1 for l in lines if lines[l].get("wav"))

        music_db = dj_engine.gain_for_loudness(norm, cfg.TARGET_LUFS)
        paths, metas, clips = {}, {}, {}
        for lang in cfg.DJ_LANGS:
            dj = lines.get(lang, {"text": "", "wav": "", "source": "off"})
            voice_path = Path(dj["wav"]) if dj.get("wav") and Path(dj["wav"]).exists() else None
            voice_db, voice_pos = 0.0, cfg.VOICE_AT_MS
            if voice_path:
                voice_db = dj_engine.gain_for_loudness(voice_path, cfg.VOICE_LUFS, max_gain=16.0)
                v_dur = probe_duration_ms(voice_path) or 4000
                if voice_pos + v_dur > dur_ms - 2000:
                    voice_pos = max(800, dur_ms - v_dur - 3000)
            full = cfg.SEGMENT_DIR / f"{tag}.{lang}.mix.wav"
            out = cfg.SEGMENT_DIR / f"{tag}.{lang}.wav"
            if not self._mix(norm, voice_path, voice_pos, music_db, voice_db, full, True):
                log.warning("[Producer] %s mix failed for %s", tag, lang)
                continue
            if not self._crossfade(full, out, lang):
                full.unlink(missing_ok=True)
                continue
            full.unlink(missing_ok=True)
            out_dur = probe_duration_ms(out) or dur_ms
            paths[lang] = out
            metas[lang] = {**parsed, "kind": "track", "track_path": path, "lang": lang,
                           "character": character, "character_key": character["key"],
                           "dj_text": dj.get("text", ""),
                           "dj_source": dj.get("source", "template"),
                           "duration_ms": out_dur}
            if voice_path:
                clip = cfg.ON_AIR_DIR / f"{tag}-{lang}.wav"
                try:
                    clip.write_bytes(voice_path.read_bytes())
                    clips[lang] = str(clip)
                except Exception:
                    pass
        norm.unlink(missing_ok=True)
        if not paths:
            return None
        dur = max(m["duration_ms"] for m in metas.values())
        log.info("[Producer] built %s | %s - %s | char=%s | %.1fs | langs=%s | ready in %.1fs",
                 tag, parsed["artist"], parsed["title"], character["name"], dur / 1000,
                 "/".join(paths), time.time() - t0)
        return Segment(paths, metas, dur, "track", clips)
    def build_interlude(self, seconds: int = 52) -> Segment | None:
        self.seq += 1
        tag = f"{self.seq:04d}-interlude"
        bed_src = cfg.SEGMENT_DIR / f"{tag}.bed.wav"
        out = cfg.SEGMENT_DIR / f"{tag}.bed.out.wav"
        bed_ms = max(1, probe_duration_ms(cfg.BED_FILE))
        loops = max(1, int(seconds * 1000 / bed_ms))
        if not run_ffmpeg(["-stream_loop", str(loops - 1), "-i", str(cfg.BED_FILE),
                           "-t", str(seconds), "-af", "afade=t=in:d=1.5",
                           "-ar", str(cfg.SAMPLE_RATE), "-ac", str(cfg.CHANNELS),
                           "-c:a", "pcm_s16le", str(bed_src)]):
            return None
        lines = {}
        if self.voice:
            with ThreadPoolExecutor(max_workers=max(1, len(cfg.DJ_LANGS))) as pool:
                futs = {lang: pool.submit(dj_engine.llm_line, "interlude",
                                          {"title": "the night drive", "artist": "A-One",
                                           "album": ""}, "", lang)
                        for lang in cfg.DJ_LANGS}
                for lang, fut in futs.items():
                    try:
                        text, _src = fut.result(timeout=120)
                    except Exception:
                        text = ""
                    lines[lang] = text
        paths, metas, clips = {}, {}, {}
        for lang in cfg.DJ_LANGS:
            text = lines.get(lang, "")
            voice = dj_engine.synthesize(text, lang=lang) if (self.voice and text) else None
            voice_db = (dj_engine.gain_for_loudness(voice, cfg.VOICE_LUFS, max_gain=16.0)
                        if voice else 0.0)
            mix = cfg.SEGMENT_DIR / f"{tag}.{lang}.mix.wav"
            seg_out = cfg.SEGMENT_DIR / f"{tag}.{lang}.wav"
            if not self._mix(bed_src, voice, 1800, 0.0, voice_db, mix, False):
                continue
            if not self._crossfade(mix, seg_out, lang):
                mix.unlink(missing_ok=True)
                continue
            mix.unlink(missing_ok=True)
            m = cfg.mount_for(lang)
            dur = probe_duration_ms(seg_out)
            paths[lang] = seg_out
            metas[lang] = {"kind": "interlude", "lang": lang,
                           "title": "Youkai Mountain Night Drive" if lang == "en"
                                    else "妖怪之山 深夜巡航",
                           "artist": m["label"], "album": "interlude", "duration_ms": dur,
                           "character_key": "mystia",
                           "character": {"key": "mystia", **cfg.CHARACTERS["mystia"]},
                           "dj_text": text, "dj_source": "llm"}
            if voice:
                clip = cfg.ON_AIR_DIR / f"{tag}-{lang}.wav"
                try:
                    clip.write_bytes(Path(voice).read_bytes())
                    clips[lang] = str(clip)
                except Exception:
                    pass
        bed_src.unlink(missing_ok=True)
        if not paths:
            return None
        dur = max(m["duration_ms"] for m in metas.values())
        log.info("[Producer] built interlude %.1fs (%s)", dur / 1000, "/".join(paths))
        return Segment(paths, metas, dur, "interlude", clips)
    def run(self) -> None:
        for stale in cfg.SEGMENT_DIR.glob("*.wav"):
            if "_pending_tail" not in stale.name:
                stale.unlink(missing_ok=True)
        bed_mod.build()
        marker.build(force=True)
        self._marker_pcm = marker.pcm()
        log.info("=" * 64)
        log.info("  %s - engine online", cfg.STATION_NAME)
        for m in cfg.MOUNTS:
            log.info("  [%s] %-28s -> %s", m["lang"], m["label"], cfg.source_url(m["lang"]))
        log.info("  voices  : %s", ", ".join(f"{m['lang']}={m['voice']}" for m in cfg.MOUNTS))
        log.info("  format  : %d Hz / %dch / %s", cfg.SAMPLE_RATE, cfg.CHANNELS, cfg.MP3_BITRATE)
        log.info("=" * 64)
        for target, name in ((self.producer, "producer"),
                             (self.metadata_worker, "metadata"),
                             (self.feeder, "feeder")):
            threading.Thread(target=target, name=name, daemon=True).start()
        while not self.stop.is_set():
            time.sleep(0.5)

    def shutdown(self) -> None:
        self.stop.set()
        for lang, proc in list(self.procs.items()):
            try:
                if proc and proc.poll() is None:
                    proc.stdin.close()
                    proc.terminate()
            except Exception:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Midnight Youkai Radio streaming engine")
    ap.add_argument("--no-voice", action="store_true", help="music only, no DJ voice")
    ap.add_argument("--crossfade", type=int, default=cfg.CROSSFADE_MS)
    ap.add_argument("--build-one", action="store_true", help="build one segment and exit")
    ap.add_argument("--track", default="", help="track path for --build-one")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    eng = Engine(voice=not args.no_voice, crossfade=args.crossfade)

    if args.build_one:
        bed_mod.build()
        path = args.track or (cfg.list_tracks() or [""])[0]
        t0 = time.time()
        seg = eng.build_track(path)
        if not seg:
            print("build failed")
            sys.exit(1)
        print(json.dumps({
            "segment": str(seg.path), "title": seg.meta["title"],
            "artist": seg.meta["artist"], "character": seg.meta["character"]["name"],
            "dj": seg.meta["dj_text"], "duration_ms": seg.duration_ms,
            "lufs": round(dj_engine.measure_lufs(seg.path), 1),
            "build_s": round(time.time() - t0, 1), "voice_wav": seg.dj_clip,
        }, ensure_ascii=False, indent=2))
        return

    acquire_singleton()

    def _sig(*_a):
        log.info("[Main] shutting down...")
        eng.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    eng.run()


if __name__ == "__main__":
    main()
