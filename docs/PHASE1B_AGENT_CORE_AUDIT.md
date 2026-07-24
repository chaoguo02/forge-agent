# Agent Core Loop Deep Audit — Phase 1B

**Date:** 2026-07-24  
**Scope:** `agent/core.py`, `agent/session/runtime.py`, `agent/session/runtime_spawn.py`, `context/compaction.py`, `context/manager.py`  
**Method:** 4-agent parallel adversarial review, verified against actual source

---

## Summary

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 2 | Subagent delegation crash, streaming tool call silent loss |
| HIGH | 2 | Post-compaction type mismatch crash, subagent `NameError` |
| MEDIUM | 7 | Observability leak, stale collapse state, memory duplication, env-block gap, cached project instructions, missing-test-target dead code, hardcoded step |
| LOW | 8 | Stale history, duplicate capabilities, unprotected logging, circuit breaker granularity, feedback reset, event routing, cancellation latency, tool_call_id=None |
| **Total** | **19** | |

---

## CRITICAL

### BUG 1: [CRITICAL] `NameError` — `parent_session_id` undefined; ALL subagent spawning broken

**File:** `agent/session/runtime_spawn.py:251`  
**Verified:** Yes — line 251 references `parent_session_id`, function signature at line 196 does NOT include it

**Scenario:** Any subagent spawn (foreground or background). `_execute_child_session()` is a module-level function extracted from `spawn_agent`. At line 251 it passes `parent_session_id` to `self.get_backend_for_session(...)` but `parent_session_id` is NOT a parameter.

**Impact:** Every child agent call crashes with `NameError`. The `finally` block catches it and marks the child FAILED, but the crash means subagent delegation simply does not work. The parent keeps running (silently degrades to no-delegation mode).

**Root cause:** During extract-function refactoring, `parent_session_id` was not added to the function signature. It was a closure variable in the original `spawn_agent`. Fix: replace `parent_session_id` with `parent.id` (the `parent` session record IS a parameter).

---

### BUG 2: [CRITICAL] Streaming tool calls silently dropped when stream ends without FINISH event

**File:** `agent/core.py:3191-3196`  
**Verified:** Yes — fallthrough path after `StreamEventKind.FINISH` handler

**Scenario:** Network disruption, API timeout, or backend bug causes `self._backend.stream_iter()` to terminate its generator without emitting `StreamEventKind.FINISH`. Prior `TOOL_USE` events have already been enqueued in `StreamingToolExecutor`.

**Impact:** All accumulated tool calls in `tool_calls_raw` are silently discarded. The agent returns `ActionType.FINISH` with message "Stream ended." Meanwhile, the executor may have already started **speculative execution** of those tools — they modify files, spawn subagents, etc., but their results are never observed by the agent loop. The agent reports success while mutated workspace state is unaccounted for.

**Root cause:** The fallthrough path at line 3191-3196 doesn't check whether `tool_calls_raw` is non-empty. It unconditionally returns FINISH instead of returning a TOOL_CALL action (like the FINISH handler at line 3179 does). No mechanism exists to cancel/reap speculative tool executions.

---

## HIGH

### BUG 3: [HIGH] Type mismatch — `list[dict]` mixed with `LLMMessage` crashes post-compaction

**File:** `agent/core.py:2903-2909` + `context/compaction.py:1000`  
**Verified:** Yes — `build_recovery_messages` returns `list[dict]`, line 2909 appends `LLMMessage`

**Scenario:** Compaction triggers during a long session. `_build_recovery_messages()` calls `recovery.build_recovery_messages([])` which returns `list[dict]` (raw dicts with `role`/`content` keys). Then line 2909 appends an `LLMMessage` object. The result (mixed `list[dict | LLMMessage]`) is concatenated with `list[LLMMessage]` at line 2895.

**Impact:** When the LLM backend iterates over the final messages list and accesses `msg.tool_calls` or `msg.role` on a `dict` element (instead of an `LLMMessage`), it raises `AttributeError`. This crashes the agent on the step immediately after compaction. Post-compaction recovery is non-functional.

**Root cause:** `CompactionRecovery.build_recovery_messages()` was designed to produce raw dicts (to avoid coupling with the LLM types), but the caller never converts them. The type annotation `-> list[LLMMessage]` on `_build_recovery_messages()` is wrong.

---

### BUG 4: [HIGH] `long_term_context` injected twice after compaction — token waste + confusion

**File:** `agent/core.py:2832, 2843, 2907-2909`  
**Verified:** Yes — both code paths inject the same memory content independently

**Scenario:** 1) `_build_messages()` calls `_build_long_term_context()` which produces memory injection text. 2) This is passed to `build_request_messages()` where it's injected as a user message with an "Understood" assistant response. 3) Compaction triggers within the same call. 4) `_inject_recovery_after_compact` is called. 5) `_build_recovery_messages()` calls `_invalidate_ltc()` then `_build_long_term_context()` AGAIN, appending `[MEMORY RESTORED]\n{same_content}`.

**Impact:** Memory context appears TWICE in the message list. This wastes 2x the memory injection budget (up to 3000 tokens) and the "Understood" assistant message from injection #1 survives compaction, creating an incoherent conversation structure when followed by the raw recovery injection.

**Root cause:** The recovery path unconditionally re-injects memory without checking whether the normal `build_request_messages` path already included it in the PRE-compaction portion of the message set.

---

## MEDIUM

### BUG 5: [MEDIUM] `CollapseStore` entries become stale after reactive compact replaces history

**File:** `agent/core.py:3274-3275` + `agent/context_trimming.py:120`  
**Verified:** Yes — `_attempt_reactive_compact` replaces history, CollapseStore references old indices

**Scenario:** Over multiple steps, `_apply_context_collapse` builds a `CollapseStore` with entries referencing message indices (e.g., `start=3, end=8`). A "prompt too long" error triggers reactive compact which replaces the entire history. The `collapse_store` still holds entries with OLD indices. On the next step, `_apply_collapse_projection` applies stale indices to the new shorter history.

**Impact:** After reactive compaction, the next turn may crash with `IndexError` in `project_view`, or silently produce a malformed message list where summaries are injected at wrong positions (context corruption).

**Root cause:** `_attempt_reactive_compact` does not reset/invalidate `_context_trimming_state.collapse_store` after replacing the history.

---

### BUG 6: [MEDIUM] Missing test target always terminates run — follow-up countdown dead code

**File:** `agent/core.py:2437-2458` + `2159-2170`  
**Verified:** Yes — early return before follow-up code

**Scenario:** A pytest tool call returns `ToolOutcome.TEST_TARGET_MISSING`. The batch loop detects `missing_observation is not None` and immediately calls `_finish_missing_test_target()` which returns a terminal `RunResult`. The `_finish_tool_turn` code that allows `missing_test_target_max_followups = 2` confirmatory steps is never reached.

**Impact:** The agent never gets its configured follow-up steps to confirm missing paths. The `missing_test_target_max_followups` config is ignored.

**Root cause:** Early return at line 2450 sets `result=run_result` (non-None), causing `_run_body` to return immediately. The follow-up code path is dead code.

---

### BUG 7: [MEDIUM] Observability context manager (Langfuse) leaked on unhandled exception

**File:** `agent/core.py:1132, 866-868`  
**Verified:** Yes — `task_context.__enter__()` not matched by `__exit__()` in error paths

**Scenario:** `log.log_action()` raises IOError (disk full, permission denied). The exception propagates out of `_run_body()` without the task context manager being closed.

**Impact:** The Langfuse observation span is left open, potentially leaking HTTP connections or producing corrupted trace data. Additionally, `state_machine.fail()` is never called, leaving the task state machine in RUNNING state.

**Root cause:** `_run_body()` has no top-level `try/finally` that ensures the Langfuse context manager is closed regardless of error.

---

### BUG 8: [MEDIUM] Environment block skips log_observation for the triggering tool call

**File:** `agent/core.py:2374-2411`  
**Verified:** Yes — environment_block early return before _apply_tool_result_analysis

**Scenario:** A tool call returns `ENVIRONMENT_UNAVAILABLE`. The `environment_block` path is taken (line 2374). The observation for the triggering tool is never recorded in the event log.

**Impact:** The event log has a `TASK_FAILED` event but no `OBSERVATION` event for the tool call that caused it. Event replay fidelity is broken.

**Root cause:** The `analysis.environment_block` check happens before `_apply_tool_result_analysis()` and `log.log_observation()` are called for that tool iteration.

---

### BUG 9: [MEDIUM] `_project_instructions` cached across runs, stale when repo changes

**File:** `agent/core.py:694-697`  
**Verified:** Yes — cache check is `hasattr(self, "_project_instructions")` with no invalidation

**Scenario:** Agent instance reused for multiple runs across different repos. First run uses `/project_a`, loads CLAUDE.md. Second run uses `/project_b` but the cache serves project_a's instructions.

**Impact:** Wrong project instructions injected into system prompt. Unlike `_repo_map_cache` (which has `_repo_map_cache_key != task.repo_path` invalidation), `_project_instructions` has no invalidation.

**Root cause:** Missing invalidation logic. `_initialize_run()` should reset or verify the cache key.

---

### BUG 10: [MEDIUM] Hardcoded `step=1` in ASSEMBLE-stage ContextPlanner call

**File:** `context/manager.py:326`  
**Verified:** Yes — step is hardcoded, not passed from caller

**Scenario:** `build_request_messages()` always passes `step=1` to the planner in ASSEMBLE stage. Currently harmless (ASSEMBLE doesn't branch on step), but future step-dependent logic would silently break.

**Impact:** Low today. Latent bug — any step-dependent ASSEMBLE logic added later will malfunction.

**Root cause:** Placeholder value never updated to receive the real step.

---

## LOW

### BUG 11: [LOW] `_pending_history` persists across `run()` calls — stale context on reuse

**File:** `agent/core.py:1136`  
**Scenario:** `_pending_history` is set externally. `run()` reads it but never sets it to None. Second `run()` on the same instance reuses stale history.

---

### BUG 12: [LOW] Capabilities message unconditionally appended — duplicates on session persist

**File:** `agent/core.py:1150-1154`  
**Scenario:** `_pending_history` already contains conversation history with a capabilities message from session persistence. `_initialize_run()` appends another unconditionally.

---

### BUG 13: [LOW] `log.log_action()` unprotected — IOError bypasses lifecycle cleanup

**File:** `agent/core.py:1733`  
**Scenario:** Disk full during `log.log_action()`. Exception propagates without lifecycle transitions. State machine stays RUNNING. No structured `RunResult` returned.

---

### BUG 14: [LOW] Circuit breaker uses all-or-nothing heuristic for batch failure detection

**File:** `agent/loop/turns.py:606-616`  
**Scenario:** Parallel tool batch: 2 succeed, 1 fails. `all_failed = False`, so `record_success()` resets the consecutive-failure counter. Intermittent failures never trip the breaker.

---

### BUG 15: [LOW] `_feedback_injected_files` not reset after compaction

**File:** `agent/core.py:3046-3049, 1116-1117`  
**Scenario:** After compaction, `record_access=True` never fires again for previously-seen files. Access-count tracking for rule promotion is skewed.

---

### BUG 16: [LOW] Subagent event routing falls back to child's own ID when `parent_id` is None

**File:** `agent/session/subagent.py:393`  
**Scenario:** Defensive edge case: `parent_id` is None, events get the child's own session_id which has no WebSocket listener.

---

### BUG 17: [LOW] Cancellation only checked at step boundaries — long tool executions un-cancellable

**File:** `agent/core.py:1315-1317`  
**Scenario:** Mid-step tool execution (e.g., 10-minute Bash, foreground subagent spawn). Cancellation waits until tool completes. Latency bounded by longest single tool call.

---

### BUG 18: [LOW] `_accumulated_structured_findings` not cleared on non-success exit paths

**File:** `agent/core.py:2945`  
**Scenario:** Agent ends with GAVE_UP/MAX_STEPS. Findings persist. If compaction fires on very first step of next run (before `_initialize_run` resets them), stale findings from the failed run are injected.

---

### BUG 19: [LOW] `tool_call_id=None` in text-fallback mode produces invalid Anthropic message role

**File:** `llm/anthropic_backend.py:148-159`  
**Scenario:** Tool call with `id=None` (possible in text-mode parsing). Observation logged without `tool_call_id`. Next LLM call produces `{"role": "tool", "content": "..."}` — Anthropic rejects "tool" role in user-assistant interleaving.

---

## Verification Notes

### Confirmed (verified against source)
- BUG 1 (NameError): runtime_spawn.py:251 references `parent_session_id`; function signature at line 196 does NOT include it
- BUG 2 (streaming drop): core.py:3191-3196 fallthrough has no tool_calls_raw check
- BUG 3 (type mismatch): compaction.py:1000 returns `list[dict]`; core.py:2909 appends `LLMMessage`
- BUG 4 (double injection): core.py:2832 and 2907 both call `_build_long_term_context()`
- BUG 5 (stale collapse): _attempt_reactive_compact replaces history, collapse_store not invalidated
- BUG 6 (dead follow-up): early return at line 2450 before follow-up code
- BUG 9 (cached instructions): hasattr check, no invalidation key

### Plausible (inferred from code structure, not runtime-tested)
- BUG 7, 8, 10-19

---

## What's NOT Broken (validated correct)

- Session generation tracking: atomic SQL increment, concurrent execution prevention
- Memory context isolation for subagents: non-PRIMARY agents get `memory_context=None`
- Event session_id routing: all current code paths set session_id correctly
- Cancellation token per-session keying: `(session_id, generation)` prevents stale tokens
- EventBus shutdown: `finally` blocks correctly clean up websocket subscriptions
- Drain task lifecycle: no leak found; Python `finally` guarantees correct for all BaseException variants
