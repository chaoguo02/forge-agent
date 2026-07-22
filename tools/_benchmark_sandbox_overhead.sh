#!/bin/bash
# _benchmark_sandbox_overhead.sh — measure Docker container startup + execution latency (Phase 9 Batch A)
# Usage: bash tools/_benchmark_sandbox_overhead.sh [--quick]
# Exit 0 if overhead <=500ms, exit 2 if >500ms, exit 1 if sandbox unavailable
set -euo pipefail

ITERATIONS="${BENCHMARK_ITERATIONS:-5}"
MT=""
QUICK="${1:-}"
if [ "$QUICK" = "--quick" ]; then ITERATIONS=2; fi

echo "=== Sandbox Overhead Benchmark (${ITERATIONS} iterations) ==="

TOTAL_START=$(date +%s%3N 2>/dev/null || echo 0)

for i in $(seq 1 "$ITERATIONS"); do
    echo -n "  Run $i/$ITERATIONS — container startup ... "
    START=$(date +%s%3N 2>/dev/null || echo 0)

    RESULT=$(timeout 30 python -c "
import os, time, subprocess, sys

# Measure docker run + exec overhead
os.environ['FORGE_SANDBOX_CPUS']='1'
os.environ['FORGE_SANDBOX_MEMORY']='512m'
os.environ['FORGE_SANDBOX_PIDS']='50'

sys.path.insert(0, '.')
from core.process import create_runtime

rt = create_runtime(sandbox=True, repo_path='.')
t0 = time.perf_counter()
result = rt.exec('echo ok', timeout=10)
t1 = time.perf_counter()
rt.cleanup()

overhead_ms = (t1 - t0) * 1000
print(f'{overhead_ms:.0f}')
" 2>/dev/null || echo "UNAVAILABLE")

    if [ "$RESULT" = "UNAVAILABLE" ]; then
        echo "UNAVAILABLE (Docker may not be running)"
        exit 1
    fi

    echo "$RESULT ms"
    if [ -n "$RESULT" ] && [ "$RESULT" -gt 500 ] 2>/dev/null; then
        MT="$RESULT"
    fi
done

TOTAL_END=$(date +%s%3N 2>/dev/null || echo 0)

echo ""
if [ -n "$MT" ]; then
    echo "OVERHEAD WARNING: max=${MT}ms exceeds 500ms target"
    exit 2
else
    echo "OVERHEAD OK: all runs <=500ms"
    exit 0
fi
