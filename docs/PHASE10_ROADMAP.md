# Phase 10 Roadmap — Value Creation & Continuous Health

> **Version**: 1.0 | **Date**: 2026-07-22
> **Status**: Draft — awaiting Solo-Dev self-review
> **Inputs**: RISK_REGISTER.md Re-review (2026-07-22 early), Langfuse RetryMetrics data, 17-gate CI baseline
> **Predecessor**: Phase 9 closure (56/56 tests, 17-gate CI, R-3 MITIGATED, R-5/R-6 RESOLVED)

---

## 1. R-1/R-2 Early Quarterly Review (2026-07-22)

### R-1: MicroCompactor In-Place Mutation — ACCEPTED (No Change)

| Factor | Assessment |
|--------|-----------|
| **Caller audit** | Both callers (`agent/core.py`, `context/manager.py`) pass `history.to_dicts()` copies. No new callers added during Phase 5-9 |
| **Trigger probability** | Very low — each caller tested in 56 regression tests; any new caller would be caught by CI |
| **Upgrade trigger** | If a new caller passes a shared list reference (not a `.to_dicts()` copy) |
| **Mitigation** | Documented at `MicroCompactor.compact()` docstring: "mutates in-place, callers must pass copy" |
| **Decision** | **ACCEPTED — no Phase 10 action** |
| **Next review** | 2026-10-22 |

### R-2: Hook Exception Silent Swallow — ACCEPTED (No Change)

| Factor | Assessment |
|--------|-----------|
| **Internal hook audit** | 0 internal hooks added during Phase 5-9; all existing hooks are pure in-memory callbacks |
| **I/O check** | `find_internal()` returns only callbacks registered via `register_internal()` — none perform I/O |
| **Upgrade trigger** | If an internal hook is added that performs I/O (network, filesystem) |
| **Decision** | **ACCEPTED — no Phase 10 action** |
| **Next review** | 2026-10-22 |

### Review Outcomes

| Risk | Pre-Review | Post-Review | Next Review | Phase 10 Task? |
|------|-----------|------------|-------------|----------------|
| R-1 | ACCEPTED | ACCEPTED | 2026-10-22 | No |
| R-2 | ACCEPTED | ACCEPTED | 2026-10-22 | No |
| R-3 | MITIGATED | MITIGATED | 2026-10-22 | No (Phase 8 fix) |
| R-4 | ACCEPTED | ACCEPTED | 2026-10-22 | No |

> **Phase 10 does not introduce new risk items.** All four existing items are LOW severity with well-defined upgrade triggers and quarterly reviews.

---

## 2. Performance Optimization — Data-Driven Approach

### 2.1 Data Sources

| Source | Current State | Observation |
|--------|--------------|-------------|
| **Langfuse RetryMetrics** | `FORGE_OBSERVE_RETRIES=1` active in Phase 7 | `attempts`, `retries`, `last_error_type`, `backoff_total_ms` — all recorded per-invocation |
| **ACC-6 Baseline** | p99 ≤500ms, Session List ~30ms | Both well within target |
| **Visual Diff Gate** | 2 Pass (Playwright verified) | CSS migration completed without regressions |

### 2.2 Profiling Decision

**No speculative profiling planned for Phase 10.** ACC-6 baseline is stable, Langfuse metrics show no retry storms, Session List query is already optimized (-94%). If a performance bottleneck emerges in production use, Phase 10 will triage it as:

1. Capture Langfuse trace snapshot
2. Profile the slow path (flamegraph or cProfile)
3. Benchmark before/after optimization
4. Verify ACC-6 baseline unchanged

### 2.3 Priority Rule

| Priority | Criteria |
|----------|---------|
| **P10-HIGH** | Bug causing >10s delay on any user-facing action |
| **P10-MED** | Retry metrics show >10% retry rate over 1-hour window |
| **P10-LOW** | Proactive improvements with clear before/after benchmark |
| **P10-DEFER** | ~5% CPU savings from loop unrolling / micro-optimizations |

> **Phase 10 strategy**: Reactive, not speculative. The codebase is stable; optimization energy goes to the highest-value problems that actually occur.

---

## 3. Security Deepening — Threat Model-Driven

### 3.1 Lightweight Threat Model (Docker Sandbox Context)

| Threat | Current Defense | Defense Depth | Next ROI |
|--------|----------------|---------------|---------|
| Bash command injection via `$()` / backticks | None — passed to `bash -c` raw | **0** | Regex pre-filter on `FORGE_SANDBOX=docker` paths |
| Environment variable exfiltration | `--network=none` (default) | **1** | Add `--env-filter` whitelist for allowed vars |
| Container escape via mounted volume | Overlay mount (RO), `no-new-privileges`, `cap-drop=ALL` | **2** | None — Docker Kernel Namespace provides boundary |
| Resource exhaustion | `--memory`, `--cpus`, `--pids-limit` (Phase 9) | **1** | Monitor resource usage via `docker stats` in benchmark |
| Langfuse trace leakage | In-container `logger.info()` → `docker logs` capture | **1** | Encrypt trace payload if `FORGE_SANDBOX=1` + `FORGE_SANDBOX_NETWORK=bridge` |

### 3.2 Next Best ROI

**P10-SEC-1: Bash command pre-filter** — regex rejection of `${subshell}` and `$(command)` patterns when `FORGE_SANDBOX=docker`. Low implementation cost (~2h), mitigates the most common injection vector, no CI overhead.

**P10-SEC-2: Environment variable whitelist** — `--env-file` with curated list of `FORGE_*` vars, block all others. Shallow cost (~1h), prevents credential leakage.

**Excluded**: Heavyweight SAST/DAST tools, container image scanning. These add CI latency without proportional benefit for a solo-dev project.

### 3.3 Gate Integration

If P10-SEC-1 is implemented, it creates:

```bash
# _check_command_injection.sh — gate assertion #18 (conditional on FORGE_SANDBOX=docker)
assert "CMD-INJ" "bash tools/_check_command_injection.sh"
```

This integrates seamlessly with the existing 17-gate framework.

---

## 4. Quality Baseline Inheritance

Phase 10 inherits the 17-gate CI baseline with the following contract:

| Contract | Term | Enforcement |
|----------|------|------------|
| **PR Template 18 items** | All items checked before merge | Self-enforced; `QUALITY_GATE_OVERRIDE` triggers follow-up issue |
| **ACC-6 Baseline** | p99 ≤500ms | Gate assertion #6; CI blocks on degradation |
| **Risk Register** | Quarterly review | R-1/R-2/R-3/R-4 next review 2026-10-22 |
| **No new P0/P1 debt** | Architecture health pre-assessment for new features | `docs/TODO.md` updated each PR; P0/P1 increments flagged |
| **Visual Diff** | Always ACTIVE | Gate assertion #14; no SKIP allowed |

### Architecture Health KPIs (Phase 10 Starting Point)

| KPI | Current | Phase 10 Floor |
|-----|---------|---------------|
| ACC Compliance Rate | 15/17·88% (2 skips) | 15/17·88% |
| E2E Coverage | 5 lifecycle tests | ≥5 |
| P2 Report Rate | 0 new in Phase 9 | ≤2/quarter |
| Gate Override Rate | 0 | ≤1/quarter |

> Any deviation from floor values opens a Re-assessment item in the current batch's closure report.

---

## 5. Phase 10 Batch Outline

### Batch A (1-2 weeks, ~4h): Bash Command Pre-Filter + Env Var Whitelist

| Task | Cost | Gate |
|------|------|------|
| P10-SEC-1: `${...}` / `$(...)` pre-filter regex | 2h | New gate assertion #18 (conditional on sandbox) |
| P10-SEC-2: Env var whitelist (`--env-filter`) | 1h | `_check_env_filter.sh` |
| RISK_REGISTER.md update: R-7 (Command Injection) entry | 0.5h | Risk register format compliance |
| Full regression + gate run | 0.5h | 18/18 gate PASS |

### Batch B (2-4 weeks, ~4h): Performance Triage (Reactive)

| Task | Trigger | Cost |
|------|---------|------|
| Profile flamegraph capture for slow path | Langfuse 10%+ retry rate in 1-hour window OR user report | 2h |
| Before/after benchmark + regression | Identified bottleneck confirmed | 2h |
| ACC-6 baseline re-verification | Post-optimization | 0.5h |

> Batch B is a *reactive batch* — it starts only when a performance issue is confirmed. Otherwise, Phase 10 closes after Batch A.

### Backlog (No ETA)

| Task | Trigger |
|------|---------|
| Docker stats resource monitoring integration | Resource exhaustion observed |
| Langfuse webhook for alert-driven perf triage | RetryTracer data volume > 100/hour |
| Playwright E2E test expansion (plan→approve→execute workflow) | User-facing bug reported in plan workflow |

---

## 6. Self-Review Checklist

- [x] R-1/R-2 review completed (2026-07-22 — 3 months early)
- [x] No new HIGH/MEDIUM risks introduced in Phase 10 plan
- [x] Performance strategy is data-driven (Langfuse + ACC-6 baseline)
- [x] Security strategy is threat model-based (Docker context)
- [x] KPI baseline defined for Phase 10 start
- [x] Gate assertion count plan: 17 → 18 (if P10-SEC-1 implemented)
- [x] Batch B is reactive — no speculative optimization

---

*Phase 10 Roadmap ready for solo-dev review. Batch A execution target: 2026-07-23.*
