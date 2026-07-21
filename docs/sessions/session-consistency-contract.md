# Session Consistency Contract

Last updated: 2026-07-20

## Why this document exists

Recent fixes exposed a pattern: we were correcting session bugs one path at a time, but we did not first freeze the global rules that every path must obey.

This document defines the contract for session consistency in Grace Code. From this point on, any session-related change should be checked against this contract before code is modified.

The goal is simple:

- one session must not leak into another
- frontend state must not outrun backend truth
- 404 means the session is gone everywhere
- reconnect, approval, delete, plan, and mode/model changes must follow the same semantics

## Scope

This contract applies to:

- frontend session selection and rendering
- frontend session-scoped chat/timeline state
- session CRUD actions
- websocket connection ownership and reconnection
- plan approval and tool approval flows
- session compaction and model switching

Primary code areas:

- `web/src/stores/sessionStore.ts`
- `web/src/stores/chatStore.ts`
- `web/src/components/ChatView.tsx`
- `web/src/components/SessionSidebar.tsx`
- `web/src/components/PlanView.tsx`
- `web/src/api/sessions.ts`

## Core architecture model

Session state is split into two layers:

### 1. Backend truth layer

The backend is the only authority for:

- whether a session exists
- which session is active on the server side
- whether a mutation succeeded
- whether a session is running, completed, failed, or deleted

Backend truth is observed through:

- REST responses
- websocket events
- explicit 404 responses

### 2. Frontend projection layer

The frontend may cache and project session state, but only as a derived view of backend truth.

Frontend state is currently split into:

- `sessionStore`
  - session list
  - active session id
  - active detail
  - cached details
  - cached session tree
- `chatStore`
  - per-session timeline/events/messages
  - per-session plan approval
  - per-session tool approvals
  - per-session mode/model/view state
  - active websocket binding

The frontend is allowed to cache. It is not allowed to invent truth.

## Non-negotiable invariants

These are hard rules.

### I1. A rendered session must be keyed by `activeId`

At any time, the center panel must render only the state bucket belonging to the current `activeId`.

Implications:

- no singleton timeline reused across sessions
- no global approval card reused across sessions
- no global child-session trace reused across sessions

### I2. Session-local UI state must be stored per session id

Any state that can vary per session must live under a session key, not in a shared singleton.

Examples:

- timeline
- events
- plan approval
- tool approvals
- current mode
- current model
- selected child trace

### I3. The frontend must not mutate session existence optimistically

Frontend code must not assume a session was deleted, cleared, compacted, or mutated before the backend confirms it.

Allowed:

- optimistic loading indicators
- optimistic disabled buttons
- optimistic local pending flags

Not allowed:

- removing the session locally before delete succeeds
- clearing the conversation before a server mutation is accepted
- disconnecting from a session and dropping data only because a request was attempted

### I4. A 404 means the session is invalid everywhere

If any authoritative session endpoint returns 404 for session `S`, then `S` must be removed from every frontend projection that still treats it as valid.

This includes:

- `sessionStore.activeId`
- `sessionStore.activeDetail`
- `sessionStore.detailById[S]`
- `sessionStore.treeById[S]`
- `chatStore.sessionStateById[S]`
- active websocket binding if it belongs to `S`

### I5. WebSocket ownership is exclusive

The active websocket must belong to exactly one session at a time.

Implications:

- when switching sessions, the previous session websocket must be detached
- websocket events must be ignored unless they match the currently bound session
- reconnect attempts must only continue for the currently bound session

### I6. Reconnect must verify session existence before reattaching

Abnormal websocket closure is not enough reason to blindly reconnect forever.

Before reconnecting, the client must verify that the session still exists. If that existence check returns 404, the client must invalidate the session instead of retrying.

### I7. Component code must not bypass store consistency rules

React components may trigger store actions, but they must not implement their own shadow consistency semantics.

Examples of prohibited component behavior:

- calling `clear()` before delete succeeds
- directly mutating local session UI to simulate a successful backend mutation
- keeping a stale active session visible after backend deletion

### I8. Non-404 failures preserve the current session projection

If an operation fails with a non-404 error:

- keep the current session cache
- keep the active session unless the backend explicitly says it is gone
- surface an error message
- revert only the minimum local optimistic delta that was introduced for that operation

### I9. Session list pruning is authoritative

When the backend session list is refreshed, local caches must be pruned to that authoritative set.

If a cached session is not present in the authoritative list:

- remove it from session caches
- remove its chat bucket
- clear active binding if it was the active session

### I10. “Clear local conversation view” is not “delete session”

Local UI reset and backend session lifecycle are different operations and must not be conflated.

`clear()` may reset the local projection of the current session bucket, but it must not be used as a substitute for:

- delete
- cancel
- compact
- reopen
- regenerate plan

## Standard mutation semantics

Every session mutation path should follow one of the patterns below.

### Pattern A: authoritative success required

Used for:

- delete session
- batch delete
- compact
- switch model
- tool approval
- plan approval/rejection

Rules:

1. optional pending UI state may be applied
2. call backend
3. if success: commit the resulting local projection
4. if 404: invalidate the session globally
5. if non-404 failure: preserve current cache and display error

### Pattern B: authoritative refresh

Used for:

- list sessions
- open session
- refresh active session
- load messages
- load trace events
- fetch session tree

Rules:

1. call backend
2. if success: update the corresponding cache
3. if 404: invalidate the target session globally
4. if non-404 failure: keep old cache and surface recoverable error state

### Pattern C: websocket event projection

Used for:

- thought
- tool_call
- observation
- reflection
- plan_ready
- approval_required
- subagent events

Rules:

1. accept event only if websocket is still bound to that session
2. patch only that session bucket
3. never let an event for session A mutate session B’s bucket

## Current responsibility boundaries

### `sessionStore`

Responsible for:

- authoritative session list projection
- active session selection
- detail cache
- tree cache
- session cache pruning
- invalidating session metadata when a session disappears

Should not own:

- timeline rendering state
- plan approval UI details
- tool approval UI details

### `chatStore`

Responsible for:

- per-session timeline and event buckets
- per-session plan/tool approval UI
- websocket ownership
- reconnect logic
- session-local mode/model/view state

Should not decide:

- whether a session still exists without backend evidence
- whether a delete succeeded

### React components

Responsible for:

- user intent capture
- rendering projections
- invoking store actions

Must not:

- encode their own deletion semantics
- pre-clear local state to simulate mutation success
- keep hidden parallel session state

## Known anti-patterns to reject going forward

The following patterns should be treated as design violations:

### A1. “Try request first, clear UI immediately”

Example shape:

```ts
clear();
await deleteSession(id);
```

Why it is wrong:

- backend truth has not yet confirmed the mutation
- failed requests leave the UI in a fabricated state

### A2. “404 in one store, stale data remains in the other”

Why it is wrong:

- the frontend no longer has a single truth projection
- the user sees ghost sessions or stale traces

### A3. “Global singleton UI reused across sessions”

Why it is wrong:

- session switching leaks previous timeline/approval state into the next session

### A4. “Blind websocket reconnect”

Why it is wrong:

- deleted sessions keep reconnecting
- stale bindings create hard-to-debug ghost activity

### A5. “Component bypasses session API layer”

Why it is wrong:

- semantics diverge
- 404 handling becomes inconsistent
- error behavior drifts across features

## Code review checklist

Any future session-related PR should be checked against this list.

- Does this change introduce any singleton state that should actually be per-session?
- Does any local UI clear/remove happen before backend success?
- If this request gets a 404, do both `sessionStore` and `chatStore` converge?
- If this request fails without 404, is old data preserved?
- Can websocket events from one session mutate another session’s view?
- Does reconnect confirm the session still exists?
- Is the component delegating semantics to stores/API helpers instead of inventing its own?
- Does a session list refresh prune stale caches?

## What this contract does not decide

This document does not prescribe:

- whether Zustand remains the final state library
- whether `sessionStore` and `chatStore` should eventually merge or stay separate
- backend schema redesign
- test framework choice

Those are implementation decisions. This document only defines externally observable consistency requirements.

## Next documents that should follow

This contract should be followed by:

1. session entrypoint and write-path inventory
2. end-to-end scenario matrix
3. targeted remediation batches

Without those follow-up documents, this contract is still useful, but not yet operationalized.
