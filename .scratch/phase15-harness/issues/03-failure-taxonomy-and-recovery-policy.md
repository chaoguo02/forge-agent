# 03 — Failure taxonomy and recovery policy

**What to build:** typed failure categories and a normalized recovery policy so budget exhaustion, max steps, loop detection, permission denial, tool failure, model error, cancellation, and completion guard rejection all map to stable harness behavior.

**Blocked by:** 01 — Replay record contract

**Status:** ready-for-agent

- [ ] Classify terminal outcomes with a stable harness vocabulary
- [ ] Preserve boundary behavior after failure instead of falling into arbitrary retry
