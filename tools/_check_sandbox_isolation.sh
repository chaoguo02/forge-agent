#!/bin/bash
# _check_sandbox_isolation.sh — verify Docker sandbox availability (Phase 8, R-3 mitigation)
# Conditional gate: invoked when FORGE_SANDBOX=docker
# Non-blocking when Docker is not configured.
set -euo pipefail

if [ "${FORGE_SANDBOX:-}" != "docker" ]; then
    echo "SANDBOX: NOT_APPLICABLE (FORGE_SANDBOX not set to 'docker')"
    exit 0
fi

echo -n "Docker daemon ... "
if docker info > /dev/null 2>&1; then
    echo "OK"
else
    echo "WARNING — Docker not reachable (daemon may be stopped)"
    echo "SANDBOX: FAIL (Docker unreachable)"
    exit 1
fi

echo -n "Docker memory limit ... "
if [ "${FORGE_SANDBOX_MEMORY:-}" != "" ]; then
    echo "OK (${FORGE_SANDBOX_MEMORY})"
else
    echo "OK (default: 2GB)"
fi

echo "SANDBOX: PASS"
exit 0
