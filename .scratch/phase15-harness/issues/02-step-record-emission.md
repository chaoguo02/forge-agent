# 02 — Step record emission

**What to build:** a verifiable step record for each turn that ties together step input, runtime decision, visible tools, model action, tool results, and continue/terminate outcome.

**Blocked by:** 01 — Replay record contract

**Status:** ready-for-agent

- [ ] Emit one coherent step record per turn
- [ ] Keep step records aligned with the replay contract so they can be persisted and replayed
