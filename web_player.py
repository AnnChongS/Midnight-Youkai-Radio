#!/usr/bin/env python3
"""Midnight Youkai Radio — web player + station API.

Serves the player UI, proxies the Icecast mount (same-origin so the browser can
run an AnalyserNode on it) and exposes now-playing / history / DJ voice / health
endpoints for the frontend.
"""

import json
import logging
import os
import sys
import time
from uuid import uuid4
from pathlib import Path

import requests
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import radio_config as cfg

STATIC_DIR = Path(__file__).resolve().parent / "static"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("web")

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

_status_cache = {"at": 0.0, "data": {}}


def _lang() -> str:
    raw = (request.args.get("lang") or "en").lower()
    if raw in ("cn", "zh", "zh-cn", "zh_cn"):
        return "zh"
    return raw if raw in cfg.DJ_LANGS else "en"


def clean_lang(raw: str) -> str:
    raw = (raw or "en").lower()
    if raw in ("cn", "zh", "zh-cn", "zh_cn"):
        return "zh"
    return raw if raw in cfg.DJ_LANGS else "en"


def icecast_status(lang: str = "en") -> dict:
    """Listener count / stream info from icecast (cached for 4 s)."""
    key = f"status_{lang}"
    cached = _status_cache.get(key)
    if cached and time.time() - cached["at"] < 4:
        return cached["data"]
    info = {"listeners": 0, "online": False, "title": "", "peak": 0}
    mount = cfg.mount_for(lang)["mount"]
    try:
        raw = requests.get(cfg.ICECAST_STATUS_URL, timeout=4).json()
        src = raw.get("icestats", {}).get("source")
        if isinstance(src, list):
            match = [x for x in src if str(x.get("listenurl", "")).endswith(mount)]
            src = (match or src or [None])[0]
        if src:
            info = {
                "online": True,
                "listeners": int(src.get("listeners") or 0),
                "peak": int(src.get("listener_peak") or 0),
                "title": src.get("title") or "",
                "server_name": src.get("server_name") or cfg.STATION_NAME,
                "server_description": src.get("server_description") or cfg.STATION_TAGLINE,
                "stream_start": src.get("stream_start_iso8601") or "",
                "listenurl": src.get("listenurl") or "",
            }
    except Exception:
        pass
    _status_cache[key] = {"at": time.time(), "data": info}
    return info


def engine_status() -> dict:
    try:
        return json.loads((cfg.STATE_DIR / "engine.json").read_text())
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# pages / assets
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/cn")
@app.get("/zh")
def index_cn():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/favicon.ico")
def favicon():
    try:
        return send_from_directory(STATIC_DIR, "favicon.svg", mimetype="image/svg+xml")
    except Exception:
        abort(404)


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------
def _relay(lang: str):
    """Proxy one icecast mount so the browser sees a same-origin audio stream."""
    m = cfg.mount_for(lang)
    try:
        upstream = requests.get(cfg.http_url(lang), stream=True, timeout=(6, 60))
    except Exception as exc:  # noqa: BLE001
        log.warning("stream upstream unreachable: %s", exc)
        return Response("stream offline", status=503, mimetype="text/plain")

    if upstream.status_code != 200:
        upstream.close()
        return Response("stream offline", status=503, mimetype="text/plain")

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk
        except Exception:
            pass
        finally:
            upstream.close()

    resp = Response(relay(), mimetype="audio/mpeg")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    ascii_name = m["label"].encode("ascii", "ignore").decode().strip()
    resp.headers["Icy-Name"] = ascii_name or ("Midnight Youkai Radio CN" if lang == "zh" else "Midnight Youkai Radio")
    resp.headers["Icy-Genre"] = cfg.STATION_GENRE
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.get("/stream")
def stream():
    return _relay("en")


@app.get("/stream-<lang>")
def stream_lang(lang: str):
    return _relay(clean_lang(lang))


@app.get("/api/dj/current.wav")
def dj_current():
    return dj_clip("latest.wav")


@app.get("/api/dj/latest-<lang>.wav")
def dj_latest(lang: str):
    l = clean_lang(lang)
    return dj_clip("latest.wav" if l == "en" else f"latest-{l}.wav")


@app.get("/api/dj/clip/<path:name>")
def dj_clip(name: str):
    safe = os.path.basename(name)
    if not safe.endswith(".wav") or not (cfg.ON_AIR_DIR / safe).exists():
        abort(404)
    resp = send_from_directory(cfg.ON_AIR_DIR, safe, mimetype="audio/wav")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ---------------------------------------------------------------------------
# api
# ---------------------------------------------------------------------------
@app.get("/api/station")
def api_station():
    lang = _lang()
    payload = cfg.station_payload(lang)
    payload["dj"]["voice_demo"] = "/api/dj/current.wav"
    payload["version"] = "2.0"
    return jsonify(payload)


@app.get("/api/now-playing")
def api_now_playing():
    lang = _lang()
    now = cfg.read_now_playing(lang)
    meta = icecast_status(lang)
    started = float(now.get("started_at") or 0)
    dur = float(now.get("duration_ms") or 0) / 1000.0
    elapsed = max(0.0, time.time() - started) if started else 0.0
    if dur and elapsed > dur:
        elapsed = dur
    return jsonify({
        "now": now,
        "progress": {"elapsed": round(elapsed, 2), "duration": round(dur, 2),
                     "started_at": started},
        "listeners": meta.get("listeners", 0),
        "peak": meta.get("peak", 0),
        "online": meta.get("online", False),
        "engine": engine_status(),
        "history": cfg.read_history(12),
        "lang": lang,
        "server_time": time.time(),
        "library": {"tracks": len(cfg.list_tracks()), "dir": str(cfg.TRACK_DIR)},
    })


@app.get("/api/queue")
def api_queue():
    eng = engine_status()
    return jsonify({"queue_depth": eng.get("queue_depth", 0),
                    "history": cfg.read_history(30)})


@app.post("/api/calibrate")
def api_calibrate():
    """Ask the engine to inject one inaudible marker burst into the live feed."""
    payload = request.get_json(silent=True) or {}
    lang = clean_lang(str(payload.get("lang") or request.args.get("lang") or "en"))
    nonce = str(payload.get("nonce") or "")[:64] or uuid4().hex
    try:
        cfg.CALIB_REQUESTS[lang].write_text(json.dumps({"nonce": nonce, "lang": lang,
                                                       "at": time.time()}))
    except Exception as exc:  # noqa: BLE001
        log.warning("calibrate request failed: %s", exc)
        return jsonify({"status": "error"}), 500
    return jsonify({"status": "queued", "nonce": nonce, "lang": lang,
                    "server_time": time.time()})


@app.get("/api/calibrate/<nonce>")
def api_calibrate_result(nonce: str):
    lang = _lang()
    try:
        res = json.loads(cfg.CALIB_RESULTS[lang].read_text())
    except Exception:
        return jsonify({"status": "pending", "server_time": time.time()}), 202
    if res.get("nonce") != nonce:
        return jsonify({"status": "pending", "server_time": time.time()}), 202
    injected = float(res.get("injected_at") or 0)
    if time.time() - injected > 45:
        return jsonify({"status": "expired", "server_time": time.time()}), 410
    return jsonify({"status": "ok", "lang": lang, "injected_at": injected,
                    "position_s": res.get("position_s"), "server_time": time.time()})


@app.get("/api/health")
def api_health():
    lang = _lang()
    meta = icecast_status(lang)
    eng = engine_status()
    ok = bool(meta.get("online")) and bool(eng.get("ffmpeg_alive", True))
    mounts = {l: icecast_status(l) for l in cfg.DJ_LANGS}
    return jsonify({"ok": ok, "lang": lang, "icecast": meta, "mounts": mounts,
                    "engine": eng, "tracks": len(cfg.list_tracks())}), (200 if ok else 503)


@app.after_request
def no_cache_api(resp):
    if resp.mimetype == "application/json":
        resp.headers["Cache-Control"] = "no-store"
    return resp


def main() -> None:
    host = os.environ.get("MYR_WEB_ADDR", "0.0.0.0")
    log.info("=" * 60)
    log.info("  %s — web player", cfg.STATION_NAME)
    log.info("  http://%s:%d   (mounts %s)", host, cfg.WEB_PORT,
             ", ".join(m["mount"] for m in cfg.MOUNTS))
    log.info("  tracks: %d", len(cfg.list_tracks()))
    log.info("=" * 60)
    try:
        from waitress import serve
        serve(app, host=host, port=cfg.WEB_PORT, threads=12, channel_timeout=120,
              connection_limit=200, ident="MidnightYoukaiRadio")
    except ImportError:
        log.warning("waitress not available — falling back to the flask dev server")
        app.run(host=host, port=cfg.WEB_PORT, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
