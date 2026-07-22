# Grace-Code Project Panorama — Phase 1-10

> **One-page overview for onboarding, technical leadership, and new contributors.**
> **Last updated**: 2026-07-22 (Phase 10 closure)

---

## What We Built

**Grace-Code** is a Claude Code-aligned autonomous coding agent framework. It implements the ReAct (Reasoning + Acting) decision loop, a permission pipeline with 6-layer defense-in-depth, subagent orchestration via Git worktrees, MCP protocol integration, and a production-grade Web UI with real-time event streaming.

### Stack

| Layer | Technology |
|-------|-----------|
| Agent Engine | Python 3.11, ReAct loop, custom ToolRegistry |
| Web Server | FastAPI + Uvicorn, WebSockets |
| Frontend | React 19 + TypeScript + Zustand, Vite 6 |
| Database | SQLite (WAL mode), thread-safe |
| LLM Provider | DeepSeek (default), OpenAI, Anthropic |
| Sandbox | Docker overlay FS, no-new-privileges, resource limits |
| Observability | Langfuse (RetryMetrics tracer) |
| CI Gate | 18 automated assertions, Playwright visual regression |

### Architecture Modules (8 Frozen Contracts)

| Module | Purpose | Phase |
|--------|---------|-------|
| `agent/loop/types.py` | LoopAction, StepResult, CompletionBlockTracker | 5 |
| `agent/constants.py` | 18 magic values → named constants | 5 |
| `server/services/chat_pipeline.py` | 6-stage chat orchestrator | 5 |
| `observability/retry_tracer.py` | RetryMetrics → Langfuse | 6 |
| `web/src/hooks/useWebSocket.ts` | WS lifecycle hook | 6 |
| `web/src/utils/markdown.ts` | Safe XSS-free markdown renderer | 4 |
| `web/src/utils/{format,status,target}.ts` | Pure UI utility functions | 5 |
| `core/process.py` | Docker sandbox + CMD-INJ filter + env whitelist | 9-10 |

---

## What We Fixed

| Priority | Cleared | Rate |
|----------|---------|------|
| P0 (critical) | **13/13** | 100% |
| P1 (high) | **35/35** | 100% |
| P2 (medium) | **43/53** | 81% |
| **Total** | **91/101** | **90%** |

### Key Achievements

| Category | Achievement |
|----------|------------|
| **Thread Safety** | SQLite WAL, `_stats_lock`, `_counter_lock` — 1000 concurrent ops, 0 lost updates |
| **ReAct Reliability** | Error feedback loop, reactive compact dedup, fallback timeout |
| **Security** | Permission pipeline 6-layer defense, Bash read-write symmetric checks, CMD-INJ pre-filter |
| **Performance** | Session List -94% latency, p99 ≤500ms, CSS-LINT zero exceptions |
| **Observability** | RetryMetrics tracer, Langfuse health gate, ACC-1~6 CI enforcement |

---

## How We Got Here

| Phase | Focus | Method |
|-------|-------|--------|
| **1-3** | Audit | Full-stack audit, benchmark analysis, 117 debt items |
| **4** | Clear P0 | Risk Matrix, 6 batches, VESP verification matrix |
| **5** | Clear P1 | ACC-1~5 audit, `_run_body` dedup, ChatPipeline |
| **6** | Features + Validation | Observability, input validation, frontend UX |
| **7** | Quality Gate | CI gate activation, SSOT checker, CSS migration |
| **8** | Risk Liquidation | R-5/R-6 resolved, R-3 mitigated via Docker |
| **9** | Production Hardening | Resource limits, code health, CI server |
| **10** | Defense-in-Depth | CMD-INJ pre-filter, env whitelist, R-3 hardened |

### Core Methodology

**Risk-Driven, Batch-Gated, Solo-Dev Self-Constrained**

1. **Risk Matrix** — every change graded by impact, coverage, rollback viability
2. **ACC Multi-Dimension Audit** — atomicity, visibility, ordering, XSS, a11y, performance
3. **Per-Batch Reflection** — actual-vs-estimated time, documentation accuracy, next-batch adjustments
4. **18-Gate CI** — `bash tools/_quality_gate.sh` blocks merge on any violation
5. **Quarterly Risk Review** — R-1/R-2/R-3/R-4 next review 2026-10-22

---

## How to Use This Project

### Getting Started

```bash
git clone <repo-url>
pip install -e ".[dev]"
cp .env.template .env  # add your API key
python -m server.main --repo . --no-browser
# Open http://localhost:8765
```

### Running Tests

```bash
python -m pytest tests/ -v -m "not e2e"  # 56 unit tests
bash tools/_quality_gate.sh              # 18-gate CI check
python tools/_check_xss.py               # XSS surface audit
```

### Before Every PR

Review the checklist in `docs/PULL_REQUEST_TEMPLATE.md` (18 items). Every item has an automated verification command — do NOT check items manually.

```bash
bash tools/_quality_gate.sh  # must output "Quality gate PASSED"
```

### Emergency Override

```bash
QUALITY_GATE_OVERRIDE=1 bash tools/_quality_gate.sh
# Creates automatic follow-up issue. Max 1 override per quarter.
```

---

## Current Risk Status

| Risk | Status | Next Review |
|------|--------|------------|
| R-1 MicroCompactor mutation | ACCEPTED (LOW) | 2026-10-22 |
| R-2 Hook silent swallow | ACCEPTED (LOW) | 2026-10-22 |
| R-3 ROOT_REMOVAL bypass | **MITIGATED** | 2026-10-22 |
| R-4 Windows TOCTOU | ACCEPTED (LOW) | 2026-10-22 |

> No HIGH or MEDIUM risks outstanding.

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/CORE_ARCHITECTURE_REPORT.md` | System-wide SSOT |
| `docs/BENCHMARK_ANALYSIS.md` | CC/Cursor/Aider/OpenHands comparison |
| `docs/TODO.md` | Active debt tracking (updated continuously) |
| `docs/LEGACY_OWNERSHIP.md` | 8 frozen contracts + maintenance contracts |
| `docs/QUALITY_GATE.md` | CI gate definitions and override protocol |
| `docs/RISK_REGISTER.md` | Quarterly-reviewed risk items |
| `docs/PULL_REQUEST_TEMPLATE.md` | 18-item self-enforced checklist |
| `docs/PHASE10_ROADMAP.md` | Value creation roadmap (reactive batches) |

---

*This panorama accompanies the Phase 10 closure report. Use it as the entry point for onboarding, technical decision-making, and quarterly reviews.*
