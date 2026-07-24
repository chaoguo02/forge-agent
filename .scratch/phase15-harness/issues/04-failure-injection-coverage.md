# 04 — Failure injection coverage

**What to build:** failure-injection tests that intentionally trigger permission rejection, tool failure, and budget exhaustion, then verify the harness preserves its boundary and records the outcome correctly.

**Blocked by:** 02 — Step record emission, 03 — Failure taxonomy and recovery policy

**Status:** ready-for-agent

- [ ] Trigger permission rejection, tool failure, and budget exhaustion on demand
- [ ] Verify the harness preserves its boundary after each injected failure
