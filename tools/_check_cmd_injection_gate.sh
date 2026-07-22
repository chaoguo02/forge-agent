#!/bin/bash
# _check_cmd_injection_gate.sh — gate assertion #18 (Phase 10, P10-SEC-1)
# Conditional: only activates when FORGE_SANDBOX=docker
set -euo pipefail

if [ "${FORGE_SANDBOX:-}" != "docker" ]; then
    echo "CMD-INJ: NOT_APPLICABLE (FORGE_SANDBOX not set to 'docker')"
    exit 0
fi

python tools/_test_cmd_injection_patterns.py
