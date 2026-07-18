# V2 ReAct Architecture

This is the canonical runtime architecture document for the current verified
Subagent / SessionRuntime implementation. When older design docs still mention
`TaskToolV2`, `task`-only child control, or pre-runtime split orchestration,
prefer this document.

## 1. V2 Overall Goal

`V2` is a persistent ReAct runtime built around `SessionRuntime` and `ReActAgent`.

- `SessionRuntime` owns the V2 session tree, session store integration, runtime modes, tool registry construction, and child delegation flow.
- `ReActAgent` owns the main `Thought -> Action -> Observation -> Finish` loop.
- `V2` supports both primary agents and subagents.
- `V2` supports `Agent`-based child delegation, with `task` retained only as a
  compatibility alias.
- Child results are returned to the parent as compact payloads instead of full child message history, which reduces the risk of parent-context re-inflation.

This document describes the currently verified architecture and test coverage. It does not describe unverified or planned behavior.

## 2. Core Flow Diagrams

### Standard ReAct Flow

```text
entry/cli.py
  -> SessionRuntime.run_session()
  -> ReActAgent.run()
  -> ToolRegistry.execute_tool()
  -> ToolResult.to_observation()
  -> history
  -> next LLM turn / finish
```

### Agent Delegation Flow

```text
parent ReAct loop
  -> AgentTool.execute()
  -> child SessionRuntime.run_session()
  -> ChildSessionResult
  -> to_store_dict() / to_parent_dict()
  -> parent compact observation
  -> post_child_synthesis / finish
```

## 3. SessionRuntime And ReActAgent

### SessionRuntime responsibilities

`SessionRuntime` is the V2 runtime coordinator.

- Creates and tracks V2 sessions.
- Builds the per-session tool registry.
- Injects runtime rules and mode-specific guidance.
- Starts child sessions for `task` delegation.
- Persists session messages and compact child results.
- Applies runtime overlays such as `post_child_synthesis`, `delegation_recovery`, and `synthesis_lockdown`.

Verified code references:

- `SessionRuntime.run_session()` creates the session controller, builds the registry, creates `ReActAgent`, and runs the task.
- `SessionRuntime._build_registry_for_session()` injects the session-bound
  delegation/runtime surface (`Agent`, `SendMessage`, `WaitForAgent`,
  `CancelAgent`, compatibility `agent_control`, and worktree review tools when
  applicable) plus runtime callbacks for completion facts and child completion
  notifications.

### ReActAgent responsibilities

`ReActAgent` is the execution loop.

- Builds request messages for the current turn.
- Calls the backend.
- Parses the returned action.
- Executes tool calls through the registry.
- Converts tool results into observations.
- Writes observations back into history.
- Continues to the next turn or finishes.

Verified code references:

- `agent/core.py`: `ReActAgent.run()`
- `agent/core.py`: `_build_messages()`
- `agent/core.py`: tool execution path and history write-back

### Integration boundary

V2 does not replace the ReAct loop with a separate executor. Instead, V2 connects policy and delegation behavior into the existing loop by:

- building a V2-specific registry
- adding tool guard callbacks
- adding tool result transformation callbacks
- adding post-tool execution callbacks
- injecting runtime messages into subsequent LLM turns

## 4. Tool Observation Mechanism

The standard tool observation mechanism is:

1. A tool returns `ToolResult`.
2. `ToolResult.to_observation()` converts it into an `Observation`.
3. `ReActAgent.run()` writes the observation back into conversation history.
4. The next backend call can see that observation in the request messages.

This has been verified by runtime tests using `MockBackend`:

- a first turn returns a tool call
- the tool executes through the registry
- the second backend call receives the tool observation
- the run finishes successfully

The current tests verify both:

- successful tool observation roundtrips
- tool error observations returned to the next turn

## 5. AgentTool And Child Result Flow

`Agent` is treated as a normal ReAct action. `task` remains a compatibility alias.

### Child execution

When the parent calls `Agent`:

1. `AgentTool.execute()` validates the request and delegation policy.
2. `SessionRuntime.run_child_session()` creates a child V2 session.
3. The child runs through `SessionRuntime.run_session()`.
4. The child result is compacted into `ChildSessionResult`.

### Store payload vs parent payload

`ChildSessionResult` has two output paths:

- `to_store_dict()`
  - used for persistence
  - includes store-oriented fields such as evidence and per-path findings
- `to_parent_dict()`
  - used for parent observation
  - returns a compact payload for parent synthesis

Verified boundary:

- parent receives `child_result.to_parent_dict()`
- parent does not directly receive child full `messages` or `history`
- compact child results are persisted separately through `to_store_dict()`

### Parent observation

The parent receives a compact observation in tool-result form rather than a replay of the entire child transcript. This is the key mechanism used to avoid full child history flowing back into the parent ReAct context.

## 6. Runtime Modes

V2 currently uses three important runtime modes:

### post_child_synthesis

Used on the turn immediately after the parent receives child completion
payloads, whether they arrived as foreground `Agent` observations or as
persisted background `<task-notification>` messages.

Current Runtime behavior:

- keeps the run inside the same ReAct loop
- withdraws fresh `Agent` spawning for that turn
- keeps child-control and worktree-review tools available
- pushes the parent toward synthesis or explicit resolution of child results

### delegation_recovery

Used when delegation is blocked or the parent must recover from an over-delegation pattern.

Behavior:

- prevents continued broad delegation behavior
- injects compact child-result summaries
- requires synthesis or explicit child-resolution behavior

### synthesis_lockdown

This remains a design target rather than a separately named Runtime mode.
Today, the minimal enforced version is the post-child synthesis withdrawal of
new `Agent` spawns for one recovery turn, plus normal policy/path/finish guards.

### Important architectural point

## 7. Child control contract

The current child-control surface is intentionally narrower than a full live
agent-team communication channel.

Current contract:

- `SendMessage` resumes a direct child only after that child is terminal.
- `WaitForAgent` observes Runtime-owned in-process liveness for a running child.
- `CancelAgent` requests cooperative cancellation of a running child.
- compatibility `agent_control` maps to the same three contracts.

Not currently implemented:

- live steering of a still-running child
- arbitrary mailbox delivery into the middle of a child turn

This boundary is deliberate. The runtime currently owns cancellation and
terminal resume, but it does not yet own a stable message-delivery channel for
running children.

These modes are not a separate executor.

They are runtime overlays inside the same ReAct loop. They work by:

- changing tool availability
- blocking guarded tool calls
- injecting runtime messages before the next backend turn
- forcing the parent toward synthesis over renewed exploration

## 8. Test Coverage

Current V2 runtime tests cover the following categories.

### Child result lifecycle tests

- `ChildSessionResult.to_parent_dict()` compact payload behavior
- `ChildSessionResult.to_store_dict()` store payload behavior
- `SessionStore.save_child_result()` and `get_child_result()` roundtrip behavior
- `SessionRuntime.read_child_result()` summary/evidence boundary behavior

### ReAct roundtrip observation tests

- successful `tool -> observation -> next turn -> finish`
- observation written into the second backend call
- observation recorded in persisted session messages

### Tool error observation tests

- tool failure returned as observation
- second backend turn receives the error observation

### Task compact child observation tests

- parent `task` call starts a child session
- child returns compact payload
- parent follow-up turn sees compact child observation
- parent does not receive full child messages/history

### Fake-backend runtime smoke tests

- standard runtime smoke test: `run_session() -> tool call -> observation -> finish`
- task smoke test: `parent task -> child session -> compact observation -> parent finish`

### Current verified test result

Command:

```powershell
python -m pytest tests/test_v2_runtime.py -q --basetemp .tmp/pytest-basetemp-react-smoke-20260627
```

Verified result:

```text
64 passed
```

## 9. Known Risks And Follow-Up Enhancements

The following are known follow-up areas, not confirmed failures in the current ReAct loop.

- More complex multi-tool roundtrips can still use stronger smoke coverage.
- A dedicated smoke test for `blocked tool -> recover -> finish` would improve confidence.
- `post_child_synthesis` can still benefit from a more complete end-to-end smoke test.
- `artifacts` and broader context-budget pressure remain an engineering stability topic for later work, but are separate from the basic ReAct loop verification documented here.

## 10. Current Summary

The currently verified architecture is:

- `V2` uses `SessionRuntime` as the persistent orchestration layer.
- `ReActAgent` remains the main execution loop.
- tools and child delegation are integrated into that loop rather than replacing it
- compact child result return paths are in place
- parent sessions synthesize from compact child observations instead of replaying full child history
- the main runtime loop and the main child-compaction boundary both have passing fake-backend coverage today
