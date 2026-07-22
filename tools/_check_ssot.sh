#!/bin/bash
# _check_ssot.sh — verify /api/config/models SSOT consistency (Phase 7 L-2)
# Rejects the PR if MODEL_CATALOG ↔ agent/constants.py drift is detected.
set -euo pipefail

PASS=0; FAIL=0

assert_py () {
    local label="$1"; local script="$2"
    if python "$script"; then
        PASS=$((PASS + 1)); echo "  [SSOT-${label}] PASS"
    else
        FAIL=$((FAIL + 1)); echo "  [SSOT-${label}] FAIL"
    fi
}

assert_sh () {
    local label="$1"; local cmd="$2"
    if eval "$cmd"; then
        PASS=$((PASS + 1)); echo "  [SSOT-${label}] PASS"
    else
        FAIL=$((FAIL + 1)); echo "  [SSOT-${label}] FAIL"
    fi
}

echo "=== SSOT Check: /api/config/models <-> agent/constants.py ==="

assert_sh "catalog-exists"  "grep -q '_MODEL_CATALOG' server/routers/config.py"
assert_py "catalog-content" "tools/_check_ssot_catalog.py"
assert_py "model-keys"      "tools/_check_ssot_keys.py"
assert_sh "constants-ref"   "grep -q 'DEFAULT_MAX_OUTPUT_TOKENS\|DEFAULT_REQUEST_BUDGET_TOKENS' agent/constants.py"

echo ""
echo "SSOT: ${PASS}/${FAIL}"
if [ "$FAIL" -gt 0 ]; then
    echo "SSOT BLOCKED — catalog/constants consistency violated."
    exit 1
else
    echo "SSOT PASSED"
    exit 0
fi
