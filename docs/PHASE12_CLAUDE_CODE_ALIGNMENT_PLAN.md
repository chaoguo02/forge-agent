# Plan: Claude Code Alignment Hard Boundaries

## Context

We already have the major subsystems in place: ReAct loop, plan mode, subagents, MCP, skills, memory, and hooks. The main problem is not missing features; it is that several critical boundaries are still soft, implicit, or split across prompt text and runtime code.

This first pass focuses on the hard edges we agreed on during grilling:

- ReAct / Runtime must be the first decision gate
- termination must be immediate and tool-stripping
- permissions must default deny with explicit allow
- subagents must be isolated execution units with minimal contracts
- MCP must have explicit lifecycle management
- skills should be loaded on demand
- long-term memory should be retrieval output, not prompt paste
- hooks must be auditable and conflict-aware

This plan is constrained to the current codebase and references the current implementation directly. No speculative redesigns beyond what the code already supports.

## Current state — file:line references

### ReAct / Runtime

- [agent/runtime_controller.py:136-241](../agent/runtime_controller.py#L136-L241) — step-level runtime checks exist, but the controller still bundles multiple concerns together and relies on the caller to obey injected messages and stripped tools.
- [agent/core.py:980-1156](../agent/core.py#L980-L1156) — the main loop applies runtime decisions, then performs additional trimming, message assembly, and tool selection in the same turn, so the boundary between “decided” and “visible” is still spread across layers.
- [agent/task.py:57-86](../agent/task.py#L57-L86) — `TerminationReason` already exists, but the runtime boundary is broader than the enum itself.
- [agent/session/task_state_machine.py:262-320](../agent/session/task_state_machine.py#L262-L320) — the task state machine already owns transition safety, but it is not yet the single place where every terminal cause is normalized.
- [agent/session/execution_budget.py:133-280](../agent/session/execution_budget.py#L133-L280) — budget escalation already knows how to inject messages and exhaust the run, but its termination semantics still need to stay aligned with the runtime controller.

### Permissions / tool visibility

- [hitl/pipeline.py:145-260](../hitl/pipeline.py#L145-L260) — permission evaluation is already layered, but the effective tool visibility boundary still depends on multiple moving parts (`permission_mode`, rules, callbacks, and registry filtering).
- [core/policy.py:148-260](../core/policy.py#L148-L260) — `PhasePolicy` already models allow/deny sets and scoped rules, but the precedence model needs to stay explicit and auditable.
- [agent/core.py:1148-1212](../agent/core.py#L1148-L1212) — tool schemas are assembled after runtime decisions, which is good, but the exact “permission before visibility” guarantee should be made more explicit in the control flow.

### Subagents

- [agent/session/subagent.py:84-260](../agent/session/subagent.py#L84-L260) — `run_child_agent()` currently handles spawn validation, worktree creation, registry construction, parent pipeline inheritance, approval behavior, and execution setup in one path.
- [agent/session/runtime_spawn.py:34-194](../agent/session/runtime_spawn.py#L34-L194) — spawn planning already validates typed inputs, but the child context boundary is still assembled across multiple functions.
- [agent/session/run_context.py:58-182](../agent/session/run_context.py#L58-L182) — `AgentSpawnContext` and `RunContext` already provide the right typed shape for isolation, but the contracts are not yet the only source of truth everywhere they should be.
- [agent/session/task_contract.py:27-77](../agent/session/task_contract.py#L27-L77) — task limits are already typed, but the subagent boundary should keep shrinking toward explicit contract-only inheritance.

### MCP

- [agent/session/mcp_integration.py:17-253](../agent/session/mcp_integration.py#L17-L253) — MCP integration exists, but tool discovery, connection state, and teardown are still managed through mutable lists and ad-hoc lifecycle calls.
- [agent/mcp/tool_adapter.py:15-183](../agent/mcp/tool_adapter.py#L15-L183) — the adapter already bridges runtime tools, but the sync bridge still depends on `asyncio.run()` in a way that is fragile in active event loops.
- [agent/mcp/registry.py:9-25](../agent/mcp/registry.py#L9-L25) — tool pooling is deterministic, but server ownership still leans on naming conventions rather than a stronger lifecycle contract.

### Skills / memory / hooks

- [agent/session/runtime_prompt_builder.py:19-160](../agent/session/runtime_prompt_builder.py#L19-L160) — skills and memory are currently injected into prompts, but selection and ranking are still mostly prompt-time concerns rather than runtime selection results.
- [memory/injection_service.py:23-88](../memory/injection_service.py#L23-L88) — memory injection concatenates memory, project rules, skills, and session context, which is workable but not yet a real ranked retrieval pipeline.
- [hooks/dispatcher.py:51-148](../hooks/dispatcher.py#L51-L148) — hook dispatch is centralized, but internal hook failures are swallowed and input merging is still optimistic.

## Target state — what Claude Code does, and what we should mirror

Claude Code’s public docs describe a layered agentic loop where runtime, permissions, subagents, skills, memory, MCP, and hooks each have a distinct role rather than sharing responsibility in prompt text.

Relevant sources:

- [Claude Code: Runtime, Tool Permissions, Subagents, Skills, Memory & MCP](https://code.claude.com/docs/en/tools-reference?utm_source=aiwithremy.beehiiv.com&utm_medium=referral&utm_campaign=claude-obsidian-will-change-your-life#monitor-tool)
- [Claude Code: Extend Claude Code](https://code.claude.com/docs/en/features-overview)
- [Claude Code: Permission modes](https://code.claude.com/docs/en/permission-modes?ck_subscriber_id=3262398805&utm_source=convertkit&utm_medium=email&utm_campaign=The+#what-the-classifier-blocks-by-default)
- [Claude Code: Explore the context window](https://code.claude.com/docs/en/context-window?utm_source=Youtube&utm_medium=Influencer&utm_campaign=Stock_Learners_YT_10_July_2024)

What we should mirror in this repository:

1. **Runtime first**
   - runtime makes the decision before the model can act
   - termination is authoritative, not advisory
   - tools are stripped before the final boundary

2. **Permissions before visibility**
   - tools should not be visible to the model until permission resolution is complete
   - deny-by-default should be enforced in code, not only described in prompt text
   - session-level overrides should remain auditable

3. **Subagents as isolated workers**
   - child execution gets minimal explicit context
   - the parent does not implicitly inherit all child state back
   - child results should be normalized into structured reports

4. **Skills on demand**
   - select the relevant skill first, then load it
   - avoid bulk prompt injection of unrelated skills
   - preserve compaction survivability without inflating every turn

5. **Memory as retrieval output**
   - memory should be selected, ranked, and compacted before injection
   - the prompt should receive a curated result, not an unbounded dump

6. **MCP as a managed lifecycle**
   - connect, refresh, disconnect, close are explicit operations
   - execution should not depend on mutable global state
   - async boundaries should not be solved with incidental `asyncio.run()` calls

7. **Hooks as deterministic policy**
   - hooks should be traceable and conflict-aware
   - failures should not disappear silently
   - input updates need an explicit merge policy

## Gap analysis

| Severity | Gap | Why it matters |
|---|---|---|
| 🔴 | Runtime decision, termination, and tool visibility are split across multiple layers | This can let the model see or attempt actions before the runtime has fully closed the boundary. |
| 🔴 | Subagent execution handles too many responsibilities in one path | This makes isolation and auditing harder, and increases the chance of hidden coupling. |
| 🔴 | MCP connection state is mutable and partly convention-based | This makes lifecycle bugs and async failures harder to reason about. |
| 🟠 | Memory is still mostly concatenation-based | It will grow noisy as the project accumulates more history. |
| 🟠 | Skills are loaded, but selection is not yet strongly separated from injection | This can inflate context and weaken relevance. |
| 🟠 | Hooks can fail or merge input without a strong conflict contract | That makes debugging and auditing harder. |
| 🟡 | Plan mode already has a structured contract, but validation is not yet the only source of truth | The structure is better than plain text, but the runtime enforcement should stay tighter. |

## Implementation steps

### Batch 1 — Runtime hard boundary consolidation

**Files**
- [agent/runtime_controller.py](../agent/runtime_controller.py)
- [agent/core.py](../agent/core.py)
- [agent/task.py](../agent/task.py)
- [agent/session/execution_budget.py](../agent/session/execution_budget.py)
- [agent/session/task_state_machine.py](../agent/session/task_state_machine.py)

**Goal**
- make termination and tool stripping a single, explicit runtime outcome
- keep the terminal reason typed and auditable
- ensure the caller cannot accidentally keep tools visible after the runtime has decided to stop

**Planned changes**
- normalize runtime stop reasons through `TerminationReason`
- keep `StepDecision` as the only runtime output the loop obeys
- ensure tool removal happens before the model sees the next tool list
- align budget exhaustion, max steps, loop detection, and circuit breaker behavior under one termination flow

**Verification**
- unit test that a terminal decision strips tools and returns immediately
- unit test that budget exhaustion, max steps, and breaker all emit stable termination reasons
- manual read-through of the main loop to confirm no later layer can reintroduce tools after a terminal decision

### Batch 2 — Permission and visibility boundary tightening

**Files**
- [hitl/pipeline.py](../hitl/pipeline.py)
- [core/policy.py](../core/policy.py)
- [agent/core.py](../agent/core.py)
- [agent/session/agent_factory.py](../agent/session/agent_factory.py)
- [agent/session/runtime.py](../agent/session/runtime.py)

**Goal**
- keep the default-deny model explicit
- make tool visibility follow permission resolution rather than precede it
- keep session-level approval the highest-precedence override inside a run

**Planned changes**
- preserve deny → ask → allow order, but make the resulting visibility boundary easier to reason about
- tighten the control flow around tool schema assembly so the runtime has already resolved the effective policy first
- keep plan-mode and read-only behavior explicit instead of relying on prompt phrasing

**Verification**
- unit test that denied tools never appear in the visible tool set
- unit test that session-level overrides win over broader policy sources
- read-through of the registry/build path to confirm permission resolution precedes model exposure

### Batch 3 — Subagent contract and isolation cleanup

**Files**
- [agent/session/subagent.py](../agent/session/subagent.py)
- [agent/session/runtime_spawn.py](../agent/session/runtime_spawn.py)
- [agent/session/run_context.py](../agent/session/run_context.py)
- [agent/session/task_contract.py](../agent/session/task_contract.py)
- [agent/session/models.py](../agent/session/models.py)

**Goal**
- make child execution an isolated runtime unit with explicit parent-to-child contracts
- keep inherited context minimal and typed
- normalize child completion into structured state rather than free-form summary text

**Planned changes**
- split child spawning into clearer phases: validation, execution placement, runtime execution, normalization
- keep parent snapshot inheritance explicit and minimal
- keep child result status typed (`success`, `partial`, `failed`, `needs_clarification`)
- preserve worktree handling as an explicit lifecycle decision, not an implicit side effect

**Verification**
- unit test that invalid or missing spawn contracts fail before execution
- unit test that child result status is normalized and distinguishable by the parent
- read-through of worktree and background paths to confirm parent/child boundaries stay explicit

### Batch 4 — MCP lifecycle hardening

**Files**
- [agent/session/mcp_integration.py](../agent/session/mcp_integration.py)
- [agent/mcp/tool_adapter.py](../agent/mcp/tool_adapter.py)
- [agent/mcp/registry.py](../agent/mcp/registry.py)
- [agent/mcp/sync_bridge.py](../agent/mcp/sync_bridge.py)
- [agent/session/runtime.py](../agent/session/runtime.py)

**Goal**
- make MCP discovery and teardown explicit and predictable
- reduce reliance on mutable shared lists and incidental async behavior
- keep server ownership easier to audit

**Planned changes**
- keep initialize / refresh / disconnect / shutdown as explicit lifecycle steps
- introduce a clearer server-to-tool ownership contract
- reduce fragile sync-over-async execution paths where possible
- keep tool snapshots stable within a turn

**Verification**
- unit test that initialize and shutdown leave MCP state empty and deterministic
- unit test that async execution errors are surfaced as typed failures
- read-through of registration and cleanup paths to confirm lifecycle edges are explicit

### Batch 5 — Skills and memory selection hardening

**Files**
- [agent/session/runtime_prompt_builder.py](../agent/session/runtime_prompt_builder.py)
- [agent/session/agent_definition.py](../agent/session/agent_definition.py)
- [memory/injection_service.py](../memory/injection_service.py)
- [memory/session_memory.py](../memory/session_memory.py)
- [memory/retriever.py](../memory/retriever.py)

**Goal**
- make skills load on demand rather than by default bulk injection
- make memory injection ranked and bounded rather than concatenative
- keep the prompt payload smaller and more relevant

**Planned changes**
- preserve skill loading, but make the selection step clearer and more intentional
- make memory injection consume retrieval output rather than raw accumulated text wherever the current architecture allows it
- keep project/user/session memory separation explicit

**Verification**
- unit test that unrelated skills are not injected by default
- unit test that memory injection remains bounded and stable for the same retrieval result
- manual check that prompt payload size drops for typical runs

### Batch 6 — Hook auditability and conflict behavior

**Files**
- [hooks/dispatcher.py](../hooks/dispatcher.py)
- [hooks/registry.py](../hooks/registry.py)
- [hooks/executor.py](../hooks/executor.py)
- [hooks/protocol.py](../hooks/protocol.py)

**Goal**
- make hook decisions traceable and conflict-aware
- avoid silent swallowing of meaningful hook failures
- keep hook merges deterministic

**Planned changes**
- keep internal and external hooks separate but auditable
- make conflicts explicit rather than silently merged
- preserve block/approve semantics while improving diagnostics

**Verification**
- unit test that conflicting input updates are reported clearly
- unit test that hook failures are logged in a way the caller can act on
- read-through of blockable event handling to confirm policy remains deterministic

## Verification strategy

For every batch:

1. run focused unit tests for the touched subsystem
2. do one code read-through against the exact file lines in this plan
3. confirm the hard boundary is enforced in code, not just in prompt text
4. keep changes small enough that each batch can be reviewed independently

## Non-goals for this pass

- No full redesign of the prompt stack
- No frontend behavior changes unless they are strictly required for the runtime boundary
- No attempt to reimplement Claude Code exactly; only the behavior we can justify from the current code and the public docs
- No broad feature additions beyond the agreed hard-boundary fixes

## Approval checkpoint

If this plan is approved, the next step is implementation in the batch order above, starting with Batch 1.
