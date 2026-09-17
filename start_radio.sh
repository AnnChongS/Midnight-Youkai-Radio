#!/usr/bin/env bash
# ============================================================
#  Midnight Youkai Radio — One-Click Startup
#  icecast2 (mount)  ->  ffmpeg encoder  ->  web player
# ============================================================
set -u

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
PID_DIR="$BASE_DIR/pids"
ICECAST_LOG_DIR="$LOG_DIR/icecast"
ICECAST_RUNTIME="$LOG_DIR/icecast_runtime.xml"
ICECAST_PORT="${MYR_ICECAST_PORT:-8001}"
WEB_PORT="${MYR_WEB_PORT:-9999}"
VENV_PY="$BASE_DIR/vendor"

mkdir -p "$LOG_DIR" "$PID_DIR" "$ICECAST_LOG_DIR" "$BASE_DIR/cache/segments" "$BASE_DIR/state"

echo "============================================"
echo "  MIDNIGHT YOUKAI RADIO — startup"
echo "============================================"
echo ""

# ----------------------------------------------------------
# 0. clear out any previous instance (ports 8001 / 9999)
# ----------------------------------------------------------
for pat in "main_streamer.py" "web_player.py" "icecast2 -c $BASE_DIR" "icecast2 -c $LOG_DIR" "ffmpeg .*icecast://source"; do
    if pgrep -f "$pat" >/dev/null 2>&1; then
        echo "[0/4] stopping previous instance: $pat"
        pkill -f "$pat" 2>/dev/null || true
        sleep 0.4
    fi
done

# ----------------------------------------------------------
# 0b. dependencies
# ----------------------------------------------------------
echo "[0/4] Checking dependencies..."
python3 - <<'PY' || { echo "       installing missing python packages into ./vendor"; pip3 install --quiet --target vendor flask requests waitress 2>/dev/null || pip install --quiet --target vendor flask requests waitress; }
import sys
sys.path.insert(0, "vendor")
import flask, requests, waitress  # noqa: F401
PY
for bin in ffmpeg ffprobe icecast2; do
    command -v "$bin" >/dev/null || { echo "  [ERROR] missing binary: $bin"; exit 1; }
done
echo "       ok"

# ----------------------------------------------------------
# 1. icecast2
# ----------------------------------------------------------
echo "[1/4] Starting Icecast2 on port $ICECAST_PORT..."
if pgrep -f "icecast2.*icecast_runtime" >/dev/null 2>&1; then
    echo "       already running"
else
    for _ in $(seq 1 30); do
        (exec 3<>/dev/tcp/127.0.0.1/$ICECAST_PORT) >/dev/null 2>&1 || { exec 3<&- 2>/dev/null; break; }
        exec 3<&- 2>/dev/null
        sleep 0.3
    done
    sed -e "s#LOGDIR_PLACEHOLDER#$ICECAST_LOG_DIR#" -e "s#<port>8001</port>#<port>$ICECAST_PORT</port>#" "$BASE_DIR/icecast_midnight.xml" > "$ICECAST_RUNTIME"
    icecast2 -c "$ICECAST_RUNTIME" >> "$LOG_DIR/icecast.out" 2>&1 &
    echo $! > "$PID_DIR/icecast.pid"
    for _ in $(seq 1 40); do
        curl -sf -m 2 "http://127.0.0.1:$ICECAST_PORT/status-json.xsl" >/dev/null 2>&1 && break
        sleep 0.25
    done
    if curl -sf -m 2 "http://127.0.0.1:$ICECAST_PORT/status-json.xsl" >/dev/null 2>&1; then
        echo "       listening on :$ICECAST_PORT (pid $(cat "$PID_DIR/icecast.pid"))"
    else
        echo "       [ERROR] icecast is not answering on :$ICECAST_PORT"
        tail -n 5 "$LOG_DIR/icecast/error.log" 2>/dev/null | sed "s/^/         /"
        cat "$LOG_DIR/icecast.out" 2>/dev/null | tail -n 5 | sed "s/^/         /"
        echo "       (is another service holding port $ICECAST_PORT?)"
        exit 1
    fi
fi

# ----------------------------------------------------------
# 2. web player
# ----------------------------------------------------------
echo "[2/4] Starting Web Player on port $WEB_PORT..."
if pgrep -f "web_player.py" >/dev/null 2>&1; then
    echo "       already running"
else
    PYTHONPATH="$VENV_PY:$BASE_DIR" nohup python3 "$BASE_DIR/web_player.py" \
        >> "$LOG_DIR/web_player.log" 2>&1 &
    echo $! > "$PID_DIR/web_player.pid"
    sleep 1
    echo "       http://localhost:$WEB_PORT (pid $(cat "$PID_DIR/web_player.pid"))"
fi

# ----------------------------------------------------------
# 3. streaming engine
# ----------------------------------------------------------
echo "[3/4] Starting streaming engine (DJ voice + eurobeat bed)..."
if pgrep -f "main_streamer.py" >/dev/null 2>&1; then
    echo "       already running"
else
    PYTHONPATH="$VENV_PY:$BASE_DIR" nohup python3 "$BASE_DIR/main_streamer.py" \
        >> "$LOG_DIR/main_streamer.log" 2>&1 &
    echo $! > "$PID_DIR/main_streamer.pid"
    echo "       pid $(cat "$PID_DIR/main_streamer.pid")"
fi

# ----------------------------------------------------------
# 4. status
# ----------------------------------------------------------
sleep 2
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
TRACKS=$(ls "$BASE_DIR/Touhou_Eurobeat" 2>/dev/null | wc -l)
echo ""
echo "[4/4] Station status"
echo "============================================"
echo "  tracks in library : $TRACKS"
echo "  stream (icecast)  : http://localhost:$ICECAST_PORT/midnight"
echo "  stream 中文台     : http://localhost:$ICECAST_PORT/midnight-cn"
echo "  web player  (EN)  : http://localhost:$WEB_PORT"
echo "  web player  (中文) : http://localhost:$WEB_PORT/cn"
[ -n "${LAN_IP:-}" ] && echo "  web player (LAN)  : http://$LAN_IP:$WEB_PORT"
echo "  logs              : $LOG_DIR/"
echo "============================================"
echo ""
echo "  Stop everything:  $BASE_DIR/stop_radio.sh"
echo "  Warm the DJ voice cache (optional):  python3 dj_engine.py --warm 9"
echo ""
