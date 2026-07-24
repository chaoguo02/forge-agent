# Tool Invocation Gate and Result Contract

## Problem Statement

From the user's perspective, the agent can already call tools, validate some inputs, and feed results back into the conversation, but the tool path still feels split across too many modules.

Today it is hard to answer these questions with confidence:

- Did the model produce a fully structured tool intent?
- Did the system validate tool names and parameters before execution?
- Did permission checks happen before the tool was allowed to run?
- Did the system normalize tool results into a single outcome vocabulary?
- Did invalid, denied, or failed tool calls get turned into a consistent observation?
- Did the runtime write the right trace and replay facts for each tool call?

The user needs a single, trustworthy tool invocation pipeline that makes tool calls safe, observable, and replayable instead of only “usually working.”

## Solution

The tool path should become a unified invocation gate followed by a normalized result contract.

That means the runtime should treat every tool call as a structured request that goes through a clear sequence:

1. model emits structured tool intent
2. tool intent is validated against the registered contract
3. permission and risk policy are applied
4. duplicate and idempotency checks run
5. eligible calls execute, including parallel-safe batches when allowed
6. tool results are normalized into a shared outcome vocabulary
7. results are written back into history, event logs, and replay records

The goal is not just to run tools. The goal is to make tool execution a controlled harness boundary with consistent behavior for success, empty output, partial output, blocked calls, and failures.

## User Stories

1. As a developer, I want every tool call to be represented as structured intent, so that the runtime can validate it before execution.
2. As a developer, I want tool names and parameters to be checked against the registered schema, so that invalid calls never reach the execution layer.
3. As a developer, I want permission checks to happen before tool execution, so that denied actions are blocked at the control plane.
4. As a developer, I want tool risk to be evaluated before execution, so that dangerous calls can be stopped early.
5. As a developer, I want duplicate tool calls in the same model response to be detected, so that repeated work does not run twice accidentally.
6. As a developer, I want cross-turn idempotency rules to exist, so that retries and recovery do not replay unsafe actions blindly.
7. As a developer, I want parallel-safe tool calls to continue running in parallel, so that the system stays efficient without sacrificing safety.
8. As a developer, I want non-parallel-safe calls to serialize correctly, so that conflicting tools do not interfere with each other.
9. As a developer, I want every tool result to normalize into a shared result vocabulary, so that the rest of the harness can reason about outcomes consistently.
10. As a developer, I want empty, partial, blocked, skipped, and failed outcomes to be distinguishable, so that the runtime does not collapse different situations into the same error bucket.
11. As a developer, I want tool results to be written back into the conversation in a consistent format, so that the model can self-correct on the next turn.
12. As a developer, I want invalid tool calls to return a structured observation instead of crashing the run, so that the model gets a chance to repair the call.
13. As a developer, I want permission denials to be recorded as explicit boundary decisions, so that audit and replay can tell why a call did not run.
14. As a developer, I want tool execution duration and outcome metadata preserved, so that concurrency and performance behavior can be inspected later.
15. As a developer, I want tool call traces to show the validated intent, the policy decision, and the normalized result, so that I can debug the whole path end to end.
16. As a developer, I want tool calls to be reflected in the event log as structured facts, so that replay is possible without reconstructing behavior from prose.
17. As a developer, I want tool result backfill to survive both native function-calling mode and fallback text mode, so that the harness behaves consistently across providers.
18. As a developer, I want the runtime to preserve its boundary when a tool fails, so that failure does not turn into uncontrolled retry or silent degradation.
19. As a developer, I want the invocation gate to be the same regardless of whether a tool was called by the main agent or by a delegated child run, so that tool policy is not split by execution context.
20. As a developer, I want replay records to capture the tool visibility snapshot and the tool result snapshot together, so that I can explain what the model saw and what the runtime did.
21. As a developer, I want tool-call validation to be strict but understandable, so that the model can self-correct when a call is malformed.
22. As a developer, I want the harness to preserve a clear distinction between tool failure and policy denial, so that recovery logic can act on the right cause.
23. As a developer, I want a single invocation gate to own tool-call admission, so that validation, permissions, idempotency, and risk are not scattered across unrelated layers.
24. As a developer, I want the tool-result contract to be stable over time, so that replay and regression tests do not break when formatting changes.
25. As a developer, I want the tool path to be explainable from persisted records alone, so that I do not need to inspect live memory to understand a run.

## Implementation Decisions

- The tool path will be treated as a single invocation gate rather than a set of disconnected checks.
- Structured tool intent is the required input to the gate; the runtime should not rely on unstructured prose to decide what to execute.
- Validation will happen before execution and will reject unknown tools, missing required parameters, malformed parameter types, and duplicate calls in the same response.
- Permission evaluation will remain a first-class pre-execution decision and will be recorded separately from tool execution itself.
- Risk and safety checks will be applied before execution, including tool-level denial reasons and path safety where relevant.
- Parallel execution will remain supported, but only for calls that are explicitly concurrency-safe at the call level.
- Tool results will normalize into a shared result contract that can represent at least success, empty output, partial output, blocked, skipped, and failed outcomes.
- The observation layer will become a presentation layer over the normalized tool result instead of the place where core semantics are invented.
- Invalid or denied tool calls will be converted into structured observations so the model can self-correct without losing harness state.
- Tool call identifiers will be preserved or synthesized deterministically so trace and replay can correlate call intent with execution result.
- Event logging will continue to exist, but tool execution records will need to be rich enough to support replay and audit without reading free-form text.
- The same invocation gate should apply regardless of whether the call came from the primary agent or a child/delegated run.
- Tool result backfill will be preserved in both native function-calling mode and text fallback mode.
- The runtime should keep the current concurrency model where possible rather than introducing a second executor.
- The highest test seam for this work is the public run/session execution boundary plus the persisted event record, not internal helper methods.

## Testing Decisions

- Good tests should exercise externally visible behavior: whether a tool ran, whether it was blocked, what observation was written back, and what got persisted.
- Good tests should not depend on private helper internals if the same behavior is already visible at the run boundary.
- The most important tests are end-to-end run tests that inspect the resulting event log and session state.
- Tool-call validation tests should verify rejection behavior for unknown tools, missing required parameters, invalid parameter types, and duplicate same-response calls.
- Permission tests should verify that denied calls never reach execution and are recorded as explicit boundary decisions.
- Result-format tests should verify that success, empty, partial, blocked, skipped, and failed outcomes are all distinguishable.
- Replay-oriented tests should verify that the normalized tool record is sufficient to reconstruct what happened later.
- Existing prior art in the codebase includes the current ReAct regression tests, lifecycle tests, event-log assertions, and quality gate checks; those patterns should be reused.
- Failure-path tests should verify that tool errors are converted into structured observations rather than collapsing the run.
- Concurrency tests should verify that parallel-safe calls can batch and non-safe calls serialize correctly.

## Out of Scope

- Rewriting the model provider abstraction.
- Adding a second tool execution framework.
- Redesigning the frontend.
- Changing every tool implementation at once.
- Broad prompt rewording that does not strengthen the runtime contract.
- Making every internal helper individually testable if the same behavior is already covered at the public run seam.
- Replacing existing permission or concurrency infrastructure wholesale.

## Further Notes

This spec is intentionally narrower than the full harness replay work.

It focuses on a single high-value boundary:

> model intent → validation → permission/risk → execution → normalized result → history/trace backfill

That boundary is the most likely place for hidden bugs, inconsistent behavior, and replay gaps. If it becomes reliable, the broader harness replay work becomes much easier to trust.

Recommended seam for implementation: the public run/session execution boundary, with persisted event records as the authoritative verification surface.

If you want, I can also turn this into a ticket chain next, starting from the invocation gate as the first slice.
