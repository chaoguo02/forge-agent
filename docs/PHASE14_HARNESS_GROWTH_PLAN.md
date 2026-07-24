# Phase 14 Plan: Harness Growth and Verifiability

## Goal

This phase deepens the harness so the system is not only Claude Code aligned, but also replayable, auditable, and verifiable under failure.

## Working agreement

The harness must preserve its hard boundaries under stress:

- permission denial must remain a denial
- tool failure must not turn into uncontrolled retry loops
- budget exhaustion must still terminate cleanly
- replay data must remain stable enough to reconstruct a run
- validation must fail closed when invariants break

## Phase 14 focus

1. deterministic replay data
2. typed step records
3. failure injection tests
4. verification of boundary preservation after failure
5. audit-ready provenance capture

## Core design decisions already aligned

- Primary target: `replayable + auditable + verifiable`
- First priority: `replayable`
- Record the minimum replay facts:
  - run input
  - runtime decision
  - tool input/output
  - termination reason
- Save replay state as structured event streams with stable fields and versioned schema
- Use `step` as the primary unit of verification
- Keep one verifiable step record per turn
- Prefer failure injection over speculation
- First failure coverage:
  - permission rejection
  - tool failure
  - budget exhaustion
- After failure, preserve the harness boundary instead of degrading into arbitrary retry

## What must be captured for replay

### 1. Immutable run identity

A run must be addressable by stable identifiers:

- `run_id`
- `session_id`
- `task_id`
- `generation`

These identifiers should be stored with every step/event that matters for audit or replay.

### 2. Provenance snapshot

The replay contract should include:

- model version
- provider
- prompt version
- tool snapshot version
- permission snapshot version
- runtime budget snapshot

### 3. Tool visibility snapshot

Before each model turn, capture the tool-visible state:

- tool name
- schema
- role/effects
- visible flag
- source
- visibility reason

### 4. Runtime decision snapshot

For every step, capture the runtime authority decision:

- step
- decision
- reason
- strip_tools
- inject_message
- terminate_reason

### 5. Tool execution snapshot

For each tool call, capture:

- tool_name
- tool_call_id
- params
- success
- output_summary
- error
- duration_ms

### 6. Termination snapshot

When the run ends, capture the authoritative terminal classification:

- termination reason
- run status
- whether the run ended by budget, max steps, loop, permission, tool failure, model error, cancellation, or completion guard

## Suggested implementation batches

### Batch 1 — replay record shape

Files likely involved:

- `agent/task.py`
- `agent/session/run_context.py`
- `agent/event_log.py`
- `observability/models.py`
- `observability/tracing.py`

Outcome:

- the project has a typed replay record shape for run identity, step records, and termination facts

### Batch 2 — step record emission

Files likely involved:

- `agent/core.py`
- `agent/runtime_controller.py`
- `agent/session/task_state_machine.py`
- `core/streaming_executor.py`

Outcome:

- every step emits a complete verifiable record

### Batch 3 — failure injection coverage

Files likely involved:

- `tests/`
- `tools/_quality_gate.sh`
- `docs/QUALITY_GATE.md`

Outcome:

- permission rejection, tool failure, and budget exhaustion are exercised intentionally

### Batch 4 — replay validation and regression gates

Files likely involved:

- `tests/`
- `tools/_quality_gate.sh`
- `docs/RISK_REGISTER.md`

Outcome:

- replay data is checked for consistency and boundary preservation is enforced

## Verification criteria

This phase is only successful if the harness can prove all of the following:

- a run can be reconstructed from persisted facts
- each step can be explained from the record alone
- failures do not erase the boundary that caused them
- the same input under the same version yields the same key decisions
- failure injection produces the expected termination or recovery behavior

## Non-goals

- do not broaden model capabilities
- do not rework the whole agent architecture
- do not add more prompt text unless it strengthens the runtime contract
- do not accept silent fallback behavior where the harness should be explicit

## Summary

Phase 14 makes the harness grow from "hard-bounded runtime" into "replayable, verifiable execution system".

That is the right next step after Claude Code alignment: not just behaving correctly, but proving it under recorded, testable conditions.
