# Plan: Finish runtime hardening and test cleanup

## Goals

1. Preserve the current defensive runtime design while documenting intentional simplifications.
2. Clean up the three known full-suite failures:
   - `tests/test_langfuse_observability.py::test_append_failure_dataset_item_for_top_level_failure`
   - `tests/test_v2_e2e_behavioral.py::TestE2EBehavioral::test_complex_task_triggers_delegation`
   - `tests/test_v2_e2e_behavioral.py::TestE2EBehavioral::test_context_passed_to_child_prompt`
3. Add integration coverage for aggressive streaming execution + context compression.

## Proposed changes

### 1. Runtime fail-closed comment

File: `runtime/streaming_executor.py`

Add a short comment in `_is_tool_concurrency_safe()` near the `isinstance(tool_input, dict)` guard:

- The current runtime `ToolCall.input` contract is object/dict-shaped.
- This mirrors Claude Code's schema-parse success gate in a simplified way.
- If future tools support scalar inputs, this should be replaced by per-tool schema validation rather than removed.

No behavior change.

### 2. Fix failure dataset path resolution

File: `observability/datasets.py`

Current issue: `_resolve_dataset_path(repo_path, dataset_path)` prepends `repo_path` to every relative explicit `dataset_path`. In the failing test, `dataset_path` is already relative to the current working directory and already includes the temp repo prefix, so it becomes duplicated:

`tmpxxx/failures.jsonl` → `tmpxxx/tmpxxx/failures.jsonl`

Plan:

- Keep current behavior for the default path (`dataset_path is None`): `repo_path / DEFAULT_FAILURE_DATASET_PATH`.
- For explicit `dataset_path`, return it as provided after `Path(dataset_path)` normalization.
- Absolute paths remain absolute.

Rationale: an explicit dataset path should be authoritative. Only the default path should be repo-relative.

### 3. Stabilize V2 delegation behavioral tests

Files likely involved:

- `agent/v2/runtime.py`
- possibly `tests/test_v2_e2e_behavioral.py` only if the current tests are inherently nondeterministic and should be marked/adjusted, but prefer production prompt fix first.

Observed failure: real LLM did not call `task` in two prompts that explicitly requested/required task delegation.

Plan:

- Strengthen primary-agent runtime injection in `_build_runtime_messages()`:
  - Keep existing guidance for normal cases.
  - Add explicit instruction: when the user explicitly says to use the `task` tool, call it instead of answering directly.
  - Add required parameter reminder: `subagent_type` and `prompt`.
  - Add context-passing reminder: include all user-provided constraints and key facts in the child prompt.
- Avoid forcing delegation for all complex work; preserve the negative test where user says not to delegate.

If this is still nondeterministic under real DeepSeek after the prompt fix, second-stage option:

- Add deterministic preflight in `SessionRuntime.run_session()` only for clear explicit delegation commands (e.g. Chinese/English phrases like `必须使用 task 工具`, `use the task tool`) is probably too invasive and could conflict with the intended LLM-behavior test, so do not do this unless prompt-only remains flaky.

### 4. Add integration tests for aggressive executor mode

File: new or existing runtime test file, likely `tests/test_sibling_abort.py` or a new `tests/test_streaming_executor.py`.

Coverage:

- `add_tool(..., execute_fn=...)` starts safe tools immediately.
- With more safe tools than concurrency slots, results still return in original tool order. To avoid mutating global env/module constants mid-test, use short sleeps and assert order/status rather than exact max concurrency unless simple monkeypatching is safe.
- Unsafe tool acts as a barrier:
  - safe A/B can run together
  - unsafe C waits for A/B
  - safe D/E wait for C
- `get_remaining_results()` drains queued and executing tasks.

### 5. Add integration tests for compression pipeline

File: new `tests/test_context_compression.py` or runtime query-loop test.

Coverage:

- Oversized `tool_result` content is truncated by `compress_messages()` and reports `budget` in `layers_applied`.
- Very small `context_window` triggers `blocking_limit`.
- Autocompact failure increments `AutoCompactTrackingState.consecutive_failures`, and after 3 failures it skips further summary attempts.

### 6. Add streaming query-loop combination test

File: `tests/test_runtime_query_loop.py` or a new streaming-specific test.

Coverage:

- `call_model` yields text + complete `tool_use` events.
- `_streaming_query_loop` registers tools aggressively and emits `ToolResultEvent` followed by continuation.
- Configure small `context_window`/large message only in a separate test to verify terminal `BLOCKING_LIMIT` without mixing too many concerns.

## Verification

Run focused suites first:

```powershell
pytest -q tests/test_runtime_tool.py tests/test_runtime_query_loop.py tests/test_sibling_abort.py
pytest -q tests/test_context_compression.py tests/test_streaming_executor.py
pytest -q tests/test_langfuse_observability.py::test_append_failure_dataset_item_for_top_level_failure
pytest -q tests/test_v2_e2e_behavioral.py::TestE2EBehavioral::test_complex_task_triggers_delegation tests/test_v2_e2e_behavioral.py::TestE2EBehavioral::test_context_passed_to_child_prompt
```

Then run full suite:

```powershell
pytest -q
```

## Risks

- V2 behavioral tests use a real LLM, so prompt-only stabilization may still be probabilistic.
- Compression tests should avoid depending on exact token estimates beyond obvious threshold cases.
- Aggressive executor tests should avoid timing-sensitive assertions where possible.
