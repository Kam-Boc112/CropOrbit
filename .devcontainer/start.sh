#!/usr/bin/env bash
# Start CropOrbit w tle przy każdym starcie Codespace: najpierw najnowszy kod, potem serwer odłączony od sesji.
cd "$(dirname "$0")/.." || exit 0
git pull --ff-only || true
pkill -f "python server.py" || true
nohup setsid python server.py > /tmp/croporbit.log 2>&1 < /dev/null &
sleep 2
pgrep -f "python server.py" > /dev/null && echo "CropOrbit started" || echo "CropOrbit failed to start, see /tmp/croporbit.log"
