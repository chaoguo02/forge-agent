# Batch 4 update: chat skill fork unified into SessionRuntime

Date: 2026-07-17

This batch closes Point 7 from the elegance audit at the implementation level.

What changed:

- `entry/chat.py` no longer executes slash-skill `context: fork` through an ad hoc
  `fork_agent.run(...)` branch.
- Slash-skill fork now creates a runtime-backed parent session and dispatches the
  child through the canonical path:
  - `SessionRuntime.create_root_session()`
  - `SessionRuntime.spawn_agent()`
- The chat-side fork remains foreground for user-invoked `/skill` flows, so the
  result is visible immediately instead of silently running in the background.
- Non-primary chat modes are prevented from silently escalating into a delegated
  skill fork parent. This keeps delegation within a declared parent contract.

Why this matters:

- skill fork is now a runtime fact, not a special chat-only execution trick
- child execution reuses the same session-tree contract as the rest of V2
- future work on notifications, resume, fan-out, and auditing no longer needs to
  handle a parallel chat-only subagent pipeline

Regression coverage:

- `tests/test_chat.py`
  - verifies slash-skill fork routes through `SessionRuntime.spawn_agent()`
  - verifies non-primary chat modes do not trigger delegated skill forks
