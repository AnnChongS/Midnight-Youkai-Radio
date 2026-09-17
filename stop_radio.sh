#!/usr/bin/env bash
# Stop all Midnight Youkai Radio processes
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$BASE_DIR/pids"

echo "Stopping Midnight Youkai Radio..."

for svc in main_streamer web_player icecast; do
    pid_file="$PID_DIR/${svc}.pid"
    if [ -f "$pid_file" ]; then
        pid="$(cat "$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            for _ in $(seq 1 20); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.25
            done
            kill -9 "$pid" 2>/dev/null || true
            echo "  stopped $svc (pid=$pid)"
        fi
        rm -f "$pid_file"
    fi
done

pkill -f "main_streamer.py" 2>/dev/null || true
pkill -f "web_player.py" 2>/dev/null || true
pkill -f "icecast2 -c .*icecast_runtime" 2>/dev/null || true
pkill -f "ffmpeg .*icecast://source" 2>/dev/null || true

rm -f "$BASE_DIR"/cache/segments/*.wav "$BASE_DIR"/state/engine.lock
echo "Done."
