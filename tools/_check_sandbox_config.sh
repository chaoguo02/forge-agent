#!/bin/bash
# _check_sandbox_config.sh — verify sandbox resource limits configurable (Phase 9, gate #17)
python -c "
from core.process import SANDBOX_CPUS, SANDBOX_MEMORY, SANDBOX_PIDS
assert isinstance(SANDBOX_MEMORY, str)
assert int(SANDBOX_PIDS) > 0
assert SANDBOX_CPUS.replace('.','').isdigit()
" 2>/dev/null
