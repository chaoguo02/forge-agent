# Harness Replay and Verification Spec

## Problem Statement

From the user's perspective, the agent already has many of the right pieces, but the harness still does not feel trustworthy enough.

When a run goes well, the system is usable. When a run goes wrong, it is still too hard to answer basic questions:

- What exactly happened in each step?
- What did the model see?
- Which tools were visible and why?
- Why did the runtime continue, compact, block, or terminate?
- Can the same run be replayed later with confidence?
- If the run failed, did the harness preserve its boundaries or silently degrade into arbitrary retry behavior?

The user needs the harness to become a system of record for execution, not just a runner that calls tools.

## Solution

The harness should become replayable, auditable, and verifiable.

That means each run should produce a structured, step-oriented execution record that captures:

- the original run input
- the runtime decision taken at each step
- the exact tool inputs and outputs
- the visible tool set at the time of the decision
- the reason for termination or continuation
- the provenance of the model, prompt, tools, permissions, and runtime budget

The harness should also support failure injection so we can intentionally exercise permission denial, tool failure, and budget exhaustion and verify that the system preserves its boundaries instead of falling back to uncontrolled retry loops.

The goal is not more logs. The goal is a harness that can prove what happened and why.

## User Stories

1. As a developer, I want each run to have a stable identity, so that I can trace one execution across steps, sessions, and persisted records.
2. As a developer, I want each step to be recorded as a structured record, so that I can inspect the causal chain of a run without reading ad hoc logs.
3. As a developer, I want to know which tools were visible before each model call, so that I can verify the permission boundary was respected.
4. As a developer, I want runtime decisions to be recorded explicitly, so that I can tell whether a turn continued, compacted, stripped tools, or terminated.
5. As a developer, I want tool inputs and outputs to be captured in a normalized form, so that I can replay or compare a run later.
6. As a developer, I want termination reasons to be typed and stable, so that I can distinguish budget exhaustion from permission denial, tool failure, model error, cancellation, and completion guard rejection.
7. As a developer, I want the harness to preserve its boundary after a failure, so that a failed step does not cause the system to enter uncontrolled retry behavior.
8. As a developer, I want failure injection tests for permission rejection, tool failure, and budget exhaustion, so that I can verify boundary handling under stress.
9. As a developer, I want the same input under the same version to produce the same key decisions, so that replay has meaning.
10. As a developer, I want run provenance to include the model, provider, prompt version, tool snapshot version, and permission snapshot version, so that I can reproduce the environment of a run.
11. As a developer, I want the harness to capture the original user input and the runtime-injected context, so that I can reconstruct what the model actually saw.
12. As a developer, I want a single verifiable step record per turn, so that I can reason about the run at the same granularity as the runtime.
13. As a developer, I want audit records to survive compaction and long runs, so that I can still inspect a run after recovery or trimming.
14. As a developer, I want a run to be explainable from persisted facts alone, so that I do not need memory of the live session to debug it.
15. As a developer, I want replay records to use versioned schemas, so that future changes do not silently break old records.
16. As a developer, I want tool visibility to be recorded with source and reason, so that I can understand why a tool appeared or disappeared.
17. As a developer, I want runtime decision snapshots to include strip-tool behavior and terminate reasons, so that I can verify the authority boundary at each step.
18. As a developer, I want termination records to explain whether the run ended by budget, max steps, loop detection, permission, tool failure, model error, cancellation, or completion guard, so that I can classify outcomes consistently.
19. As a developer, I want replay validation to fail closed when invariants break, so that corrupt or partial records are never treated as trustworthy.
20. As a developer, I want the harness to support regression tests around replay, so that boundary changes are caught before they reach users.
21. As a developer, I want step-level metrics such as retry depth, termination reason distribution, and compaction frequency, so that I can see when the harness starts behaving poorly.
22. As a developer, I want session and subagent boundaries to remain explicit in the run record, so that child behavior can be distinguished from parent behavior.
23. As a developer, I want the tool execution layer to preserve duration and outcome data, so that concurrency and abort behavior can be inspected later.
24. As a developer, I want the harness to make failure cases first-class, so that success is not the only thing that can be proved.
25. As a developer, I want the system to retain enough provenance to compare two runs, so that I can tell whether a behavior change came from code, config, prompt, model, or tool visibility.
26. As a developer, I want verification to focus on observable behavior rather than implementation internals, so that the tests remain stable across refactors.

## Implementation Decisions

- The harness will be organized around a step-oriented replay contract rather than free-form logs.
- Each step record will include the step number, runtime decision, tool visibility, model action, tool result summary, and terminal or continuation outcome.
- The run record will carry immutable identity fields such as run identity, session identity, task identity, and generation.
- Run provenance will include the model/provider pair, prompt version, tool snapshot version, permission snapshot version, and runtime budget snapshot.
- Tool visibility will be represented as a snapshot with tool name, schema, role/effects, visibility flag, and reason/source for visibility.
- Runtime decision snapshots will explicitly record decision, reason, strip-tools state, injected message, and termination reason.
- Tool execution snapshots will preserve the tool name, tool call identifier, params, success flag, output summary, error text, and duration.
- Termination classification will be normalized through the existing runtime-owned termination taxonomy and its mapping to run status.
- Replay data will be versioned so that old records can still be interpreted after future schema changes.
- The system will capture the original user input plus a normalized version and source metadata so the replay contract can distinguish what the user said from what the runtime consumed.
- Runtime-injected context will be captured as part of the replay contract, including system prompt variants, memory injection, skill injection, hook injection, and permission-related messages.
- Permission state will be snapshot at the time of a step, including allow/deny rules, permission mode, session overrides, and path/tool scope constraints.
- Tool snapshots will include the visible tool set and the contract version that governed them.
- The harness will keep `step` as the primary unit of verification and use event records as supporting detail rather than the other way around.
- Failure injection will be a required part of the harness design, not an optional diagnostic add-on.
- The first failure-injection coverage will focus on permission rejection, tool failure, and budget exhaustion.
- After failure, the harness must preserve the boundary that caused the failure instead of falling back to uncontrolled retry loops.
- The highest test seam should be the public run boundary and the persisted event record, not internal helper methods.
- Existing step/state machinery should be reused where possible instead of introducing parallel tracking systems.

## Testing Decisions

- Good tests should exercise observable run behavior: final status, recorded step data, replay consistency, and boundary preservation.
- Good tests should not assert private implementation details unless those details are part of the public harness contract.
- The most important tests are end-to-end run tests that inspect persisted records after a run completes.
- Step-level tests should verify that each step produces a complete and coherent record.
- Replay tests should verify that the same input under the same version yields the same key runtime decisions and termination path.
- Failure injection tests should intentionally trigger permission denial, tool failure, and budget exhaustion and verify the resulting boundary behavior.
- Recovery tests should verify that compaction, retry, and termination stay within the declared policy.
- Regression tests should cover the public run boundary, persisted session state, and event-log output rather than internal helper functions.
- Existing prior art in the codebase includes the current e2e tests, lifecycle tests, quality gate checks, and harness-style regression scripts; those patterns should be reused rather than replaced.
- Harness tests should fail when replay data is incomplete, ambiguous, or schema-incompatible.
- Harness tests should verify that failure does not erase the reason the run stopped.

## Out of Scope

- Rewriting the entire agent architecture.
- Adding new user-facing agent capabilities unrelated to harness behavior.
- Broad prompt rewording that does not strengthen runtime contracts.
- Replacing the current model provider abstraction.
- Introducing a second parallel execution framework.
- Making every internal helper individually testable if the same behavior is already covered at the public run seam.
- Redesigning the frontend unless a harness record needs to be surfaced there later.

## Further Notes

The most important harness principle for this phase is:

> After a failure, the system must still behave like a bounded harness, not like an improvising loop.

The current codebase already has most of the ingredients for that. The next step is to make the execution record strong enough that replay and verification become first-class features rather than manual debugging techniques.

Recommended seam for implementation: use the public run/session execution boundary as the primary test seam, with the persisted event record as the authoritative assertion surface.

If that seam is not what you had in mind, I can revise the spec before we turn it into implementation work.
