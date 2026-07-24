# Phase 13 Plan: Harness Design First

## Context

Phase 12 focused on Claude Code alignment at the runtime boundary: termination, permissions, subagents, MCP lifecycle, skills, memory, and hooks.

That work is necessary, but it does not yet make the system a strong **harness**.

A good harness is not just a loop that calls tools. It is a controlled execution environment that can:

- run deterministically enough to debug
- recover from partial failure
- prove what happened after the fact
- constrain dangerous actions before they become runtime incidents
- measure quality and regressions over time
- support repeatable evaluation, replay, and benchmarking

The current codebase already contains the core ingredients:

- `agent/core.py` for the ReAct loop
- `agent/runtime_controller.py` and `agent/session/task_state_machine.py` for runtime guards
- `core/process.py` and `core/streaming_executor.py` for tool execution and concurrency
- `agent/session/session_store.py` for durable session state
- `observability/` for traces, scores, and datasets
- `tools/_quality_gate.sh` for CI gates
- `memory/` and `hooks/` for long-lived runtime behavior

But these pieces are still more like separate subsystems than a unified harness contract.

## What else we should consider before calling the harness “good”

### 1. Deterministic replay and debugging

We need a repeatable way to reconstruct a run:

- same input prompt
- same tool permissions
- same model settings
- same tool outputs
- same runtime decisions
- same recovery path

Without replay, debugging remains guesswork.

### 2. Failure taxonomy

Right now many failures are classified, but the harness still needs a stronger shared vocabulary for:

- model failure
- tool failure
- environment failure
- policy denial
- context pressure
- completion guard rejection
- cancellation
- timeout
- retry exhaustion

A harness should not treat all non-success states as the same thing.

### 3. Step-level observability

We need visibility into the full step lifecycle:

- what the runtime decided
- what tools were visible
- what the model tried to do
- what actually executed
- what observations came back
- what the next decision was

The goal is not more logs; it is more **useful causal traceability**.

### 4. Run identity and provenance

Every run should have a strong identity:

- task id
- session id
- generation / revision
- model identity
- permission snapshot
- tool snapshot
- memory snapshot
- MCP snapshot
- hook snapshot

This is the basis for audit, replay, and comparison.

### 5. Recovery strategy as a first-class design problem

The current code already has recovery paths, but the harness should decide and document:

- when to compact
- when to retry
- when to terminate
- when to hand back control
- when to force finalization
- when to preserve state vs discard it

### 6. Execution isolation model

We should be explicit about what is isolated at which level:

- process isolation
- worktree isolation
- session isolation
- subagent isolation
- MCP server isolation
- memory scope isolation

A harness is only credible if these boundaries are obvious and testable.

### 7. Evaluation and acceptance criteria

The harness needs a notion of success beyond “the code ran”:

- did the right tool get called?
- did the right boundary block the wrong action?
- did the run recover when it should?
- did the final answer reflect the actual state?
- did the session stay reproducible after compaction or resume?

### 8. Regression protection

We need better coverage for “this used to work” failures:

- tool concurrency regressions
- plan-mode drift
- context trimming regressions
- subagent contract regressions
- hook side effects
- MCP lifecycle leaks
- permission visibility drift

### 9. Harness-level metrics

Useful metrics are different from product metrics:

- step count distribution
- tool call success rate
- recovery frequency
- compaction frequency
- termination reason distribution
- retry depth
- subagent yield quality
- permission block frequency

These metrics should support debugging and design iteration, not just dashboards.

## Proposed next phase: Harness First

### Phase objective

Turn the runtime into a **measurable, replayable, bounded execution harness** instead of only a feature-complete agent loop.

### Phase success definition

We should be able to answer, for any run:

1. what happened
2. why it happened
3. what was visible to the model
4. what was blocked and by whom
5. whether the run can be replayed
6. whether the run is within expected safety and quality bounds

## Target state

The harness should provide:

- deterministic run identity
- typed event trail
- replayable tool and runtime decisions
- explicit recovery policy
- isolated execution scopes
- measurable quality gates
- audit-friendly failure classification
- testable step boundaries

## Phase 13 workstreams

### Workstream A — Run trace and replay contract

Goal: make a run reconstructable after the fact.

Focus areas:

- event trail normalization
- tool schema snapshots
- runtime decision snapshots
- model/provider provenance
- step-by-step replay metadata

Likely files:

- `agent/task.py`
- `agent/event_log.py`
- `agent/core.py`
- `agent/session/run_context.py`
- `agent/session/session_store.py`
- `observability/models.py`
- `observability/tracing.py`

### Workstream B — Failure taxonomy and recovery policy

Goal: separate “what failed” from “what the harness should do next.”

Focus areas:

- typed failure classes
- canonical retry reasons
- termination and recovery mapping
- guard outcome normalization
- summary vs abort policy

Likely files:

- `agent/task.py`
- `agent/runtime_controller.py`
- `agent/completion_guard.py`
- `agent/session/task_state_machine.py`
- `agent/recovery.py`
- `agent/session/execution_budget.py`

### Workstream C — Tool execution as a controlled subsystem

Goal: make tool execution predictable under concurrency and partial failure.

Focus areas:

- streaming executor admission control
- concurrency partitioning
- sibling abort behavior
- output truncation policy
- tool result shaping
- tool visibility snapshots

Likely files:

- `core/streaming_executor.py`
- `agent/core.py`
- `core/base.py`
- `agent/context_trimming.py`
- `agent/observation_rendering.py`

### Workstream D — Isolation boundaries

Goal: define what is isolated, what is shared, and what can cross the boundary.

Focus areas:

- worktree isolation
- session isolation
- MCP server lifecycle
- subagent context boundaries
- permission snapshots
- memory scope boundaries

Likely files:

- `agent/session/runtime.py`
- `agent/session/subagent.py`
- `agent/session/worktree_service.py`
- `agent/session/worktree_manager.py`
- `agent/session/mcp_integration.py`
- `memory/context.py`

### Workstream E — Harness evaluation and gates

Goal: make harness quality visible and enforceable.

Focus areas:

- replay-based regression tests
- lifecycle tests
- permission boundary tests
- failure injection tests
- quality gates tied to harness invariants

Likely files:

- `tests/`
- `tools/_quality_gate.sh`
- `docs/QUALITY_GATE.md`
- `docs/RISK_REGISTER.md`

## Proposed phase breakdown

### Batch 1 — Define the harness contract

Deliverables:

- a canonical harness contract document
- a typed list of run identity fields
- a typed list of failure categories
- a typed list of replay inputs and outputs

Outcome:

- every later harness feature can point back to the same contract

### Batch 2 — Make runs replayable

Deliverables:

- stable run identifiers
- step snapshots
- tool schema snapshots
- decision snapshots
- persisted provenance

Outcome:

- one run can be reconstructed without relying on memory or guesswork

### Batch 3 — Stabilize failure and recovery semantics

Deliverables:

- canonical failure taxonomy
- normalized recovery policy table
- stronger guard outcome mapping

Outcome:

- similar failures lead to similar harness behavior

### Batch 4 — Harden tool execution boundaries

Deliverables:

- clearer concurrency and abort rules
- better tool result shaping
- deterministic output truncation behavior

Outcome:

- the harness behaves predictably even under tool pressure

### Batch 5 — Add harness-level evaluation coverage

Deliverables:

- replay tests
- lifecycle tests
- permission tests
- failure injection tests
- gate updates where necessary

Outcome:

- the harness can prove it is still correct after change

## What we should not do in this phase

- do not add more prompt text unless it enforces a runtime contract
- do not add new features just because they are interesting
- do not broaden the agent’s power surface
- do not optimize for model cleverness before harness correctness
- do not hide uncertain behavior behind fallback text

## Verification criteria

This phase is successful only if we can show:

- a run can be reconstructed from persisted facts
- failure reasons are typed and non-ambiguous
- runtime decisions are auditable step by step
- tool execution remains bounded and deterministic enough to debug
- harness regressions have dedicated tests

## Relationship to Phase 12

Phase 12 was about **Claude Code alignment**.

Phase 13 should be about **harness quality**.

That means:

- Phase 12 asks: “Are we behaving like the target design?”
- Phase 13 asks: “Can this system be trusted, replayed, measured, and debugged?”

Both matter, but they are not the same problem.
