#!/usr/bin/env bash
# Start CropOrbit w tle przy każdym starcie Codespace: najpierw najnowszy kod, potem serwer odłączony od sesji.
cd "$(dirname "$0")/.." || exit 0
git pull --ff-only || true
pkill -f "python server.py" || true
nohup setsid python server.py > /tmp/croporbit.log 2>&1 < /dev/null &
sleep 2
# port po restarcie Codespace wraca do prywatnego — przestawiamy go na publiczny (link dla komisji)
if [ -n "$CODESPACE_NAME" ] && command -v gh > /dev/null; then
  gh codespace ports visibility 8077:public -c "$CODESPACE_NAME" > /tmp/croporbit-port.log 2>&1 || true
fi
pgrep -f "python server.py" > /dev/null && echo "CropOrbit started" || echo "CropOrbit failed to start, see /tmp/croporbit.log"
