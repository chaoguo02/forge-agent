#!/bin/bash
# _ci_server_health.sh — verify Grace-Code CI server lifecycle (Phase 9 Batch C)
# Usage: bash tools/_ci_server_health.sh [--ephemeral]
# With --ephemeral: auto-kills server after test (no port contamination)
set -euo pipefail

PORT="${CI_SERVER_PORT:-18765}"
EPHEMERAL=0
if [ "${1:-}" = "--ephemeral" ]; then EPHEMERAL=1; fi

echo -n "Starting server on port $PORT ... "
timeout 12 bash -c "
python -m server.main --repo . --port $PORT --no-browser 2>/dev/null &
SERVER_PID=\$!
sleep 6
if curl -sf http://127.0.0.1:$PORT/ > /dev/null 2>&1; then
    echo OK
    if [ $EPHEMERAL -eq 1 ]; then
        kill \$SERVER_PID 2>/dev/null || true
        echo 'Server stopped (ephemeral mode)'
    fi
    exit 0
else
    echo FAIL
    kill \$SERVER_PID 2>/dev/null || true
    exit 1
fi
" 2>/dev/null || { echo "TIMEOUT"; exit 1; }

exit 0
