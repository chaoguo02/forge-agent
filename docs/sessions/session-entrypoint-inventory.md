# Session Entrypoint and Write-Path Inventory

Last updated: 2026-07-20

Related contract:

- `docs/sessions/session-consistency-contract.md`

## Purpose

This document turns the session consistency contract into an operational inventory.

It answers four questions:

1. Which code paths can create, destroy, or mutate session state?
2. Which code paths can project or refresh session state?
3. Which code paths can invalidate a session?
4. Which code paths still need tighter alignment with the contract?

This is the table we should use before changing session behavior again.

## Reading guide

Each entry is labeled with a contract pattern:

- Pattern A: authoritative success required
- Pattern B: authoritative refresh
- Pattern C: websocket event projection

See `session-consistency-contract.md` for the exact semantics.

## Layer map

### Backend authority

- REST endpoints under `/api/sessions/*`
- websocket stream under `/api/ws/sessions/{id}`

### Frontend state projection

- `web/src/stores/sessionStore.ts`
- `web/src/stores/chatStore.ts`

### Frontend intent entrypoints

- `web/src/components/SessionSidebar.tsx`
- `web/src/components/ChatView.tsx`
- `web/src/components/PlanView.tsx`
- `web/src/components/SessionTree.tsx`

## A. SessionStore inventory

### 1. `loadSessions()`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern B
- Purpose:
  - fetch authoritative session list
  - prune stale local session caches
  - clear active session if it no longer exists
  - instruct `chatStore` to prune session UI buckets
- Contract mapping:
  - I3, I4, I8, I9
- Notes:
  - this is one of the most important convergence paths
  - any future session cache should also be pruned here

### 2. `openSession(id)`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern B
- Purpose:
  - select a session
  - reuse cached detail/tree optimistically for display
  - refresh authoritative detail from backend
- Contract mapping:
  - I1, I4, I8
- Notes:
  - 404 must invalidate the session globally
  - should never leave an active ghost session after 404

### 3. `createSession(agentName, repoPath)`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern A + Pattern B follow-up
- Purpose:
  - create a backend session
  - reload the session list
  - open the created session
- Contract mapping:
  - I3, I8, I9
- Notes:
  - should not create local fake sessions before backend returns

### 4. `deleteSession(id)`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern A
- Purpose:
  - request deletion
  - remove local metadata only after backend confirms deletion
  - reload authoritative list after success
- Contract mapping:
  - I3, I4, I8, I9
- Notes:
  - previously violated by component-side pre-clear behavior

### 5. `deleteSessionsBatch(ids)`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern A
- Purpose:
  - delete multiple sessions
  - reload authoritative list after success
- Contract mapping:
  - I3, I4, I8, I9
- Notes:
  - should continue to rely on authoritative list refresh rather than guessed local removal

### 6. `refreshActive()`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern B
- Purpose:
  - refetch detail for current `activeId`
  - invalidate locally and globally if the active session no longer exists
- Contract mapping:
  - I4, I8
- Notes:
  - this is the main “does the active session still exist?” refresh path outside websocket reconnect

### 7. `fetchSessionTree(id)`

- File: `web/src/stores/sessionStore.ts`
- Type: Pattern B
- Purpose:
  - fetch subagent/session tree for active session
- Contract mapping:
  - I1, I4, I8
- Notes:
  - tree cache must stay aligned with session existence

### 8. `invalidateSessionLocally(id)`

- File: `web/src/stores/sessionStore.ts`
- Type: local convergence helper
- Purpose:
  - remove session metadata caches from `sessionStore`
  - clear active selection if that session was active
- Contract mapping:
  - I4
- Notes:
  - this is not an authoritative operation by itself
  - it is only valid when backend evidence already exists

## B. ChatStore inventory

### 1. `sendChat(sessionId, prompt, intent)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern A
- Purpose:
  - append user message projection
  - mark session as running
  - submit prompt to backend
- Contract mapping:
  - I1, I2, I4, I8
- Notes:
  - currently guarded so it only runs if `sessionId` is still the bound session
  - 404 invalidates the session

### 2. `loadMessages(sessionId)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern B
- Purpose:
  - fetch authoritative message history
  - merge messages into session timeline
- Contract mapping:
  - I1, I4, I8

### 3. `loadTraceEvents(sessionId)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern B
- Purpose:
  - fetch saved trace events for the selected session
- Contract mapping:
  - I1, I4, I8

### 4. `connectWs(sessionId)`

- File: `web/src/stores/chatStore.ts`
- Type: connection control + Pattern C transport
- Purpose:
  - bind the websocket to one active session
  - receive live event projection for that session
- Contract mapping:
  - I1, I5, I6
- Notes:
  - reconnect logic lives inside this control path
  - websocket binding is global, but projected data is per-session

### 5. `disconnectWs()`

- File: `web/src/stores/chatStore.ts`
- Type: connection control
- Purpose:
  - stop receiving events for the bound session
- Contract mapping:
  - I5

### 6. `handleWsEvent(ev)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern C
- Purpose:
  - project websocket events into the currently bound session bucket
- Contract mapping:
  - I1, I2, I5
- Notes:
  - this is the single most sensitive anti-leakage path
  - any new event type must keep per-session projection discipline

### 7. `approvePlan(comment)` / `rejectPlan(reason)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern A
- Purpose:
  - resolve a waiting plan approval
- Contract mapping:
  - I1, I4, I8
- Notes:
  - 404 must invalidate the entire session

### 8. `resolveToolApproval(requestId, decision, opts)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern A
- Purpose:
  - resolve pending permission request for a session
- Contract mapping:
  - I1, I4, I8
- Notes:
  - local removal is optimistic but restored on non-404 failure

### 9. `compactSession()`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern A
- Purpose:
  - compact the active session
- Contract mapping:
  - I3, I4, I8
- Notes:
  - must not clear current view just because compaction was attempted

### 10. `switchModel(model, provider)`

- File: `web/src/stores/chatStore.ts`
- Type: Pattern A
- Purpose:
  - change model for the current session
- Contract mapping:
  - I3, I4, I8
- Notes:
  - now aligned with shared API client semantics

### 11. `setMode(mode)`

- File: `web/src/stores/chatStore.ts`
- Type: local session-scoped projection
- Purpose:
  - update current mode for the active session bucket
- Contract mapping:
  - I1, I2
- Notes:
  - local-only UI state, not session existence truth

### 12. `setViewingChild(id)`

- File: `web/src/stores/chatStore.ts`
- Type: local session-scoped projection
- Purpose:
  - choose which child trace to inspect for the current session
- Contract mapping:
  - I1, I2

### 13. `clear()`

- File: `web/src/stores/chatStore.ts`
- Type: local UI reset
- Purpose:
  - reset the active session bucket projection while preserving local mode/model preferences
- Contract mapping:
  - I10
- Notes:
  - must not be used as a delete/cancel/plan-generation surrogate

### 14. `forgetSession(id)`

- File: `web/src/stores/chatStore.ts`
- Type: local convergence helper
- Purpose:
  - drop the UI bucket and active websocket binding for a missing session
- Contract mapping:
  - I4, I5
- Notes:
  - valid only when backed by authoritative evidence

### 15. `pruneSessions(validIds)`

- File: `web/src/stores/chatStore.ts`
- Type: local convergence helper
- Purpose:
  - remove session buckets not present in authoritative list
- Contract mapping:
  - I4, I9

### 16. `registerSessionMissingHandler(handler)`

- File: `web/src/stores/chatStore.ts`
- Type: store bridge
- Purpose:
  - lets `chatStore` notify `sessionStore` when backend evidence shows a session is gone
- Contract mapping:
  - I4
- Notes:
  - important because session invalidation must converge across stores

## C. Component entrypoint inventory

These are the places where user intent enters the system.

### 1. `SessionSidebar`

- File: `web/src/components/SessionSidebar.tsx`
- Entrypoints:
  - create session
  - open session
  - delete session
  - batch delete
- Contract-sensitive areas:
  - I3, I7, I9
- Current stance:
  - component no longer pre-clears current session before delete

### 2. `ChatView`

- File: `web/src/components/ChatView.tsx`
- Entrypoints:
  - bind websocket on active session change
  - load messages/events on active session change
  - send chat
  - cancel session
  - local clear
  - mode switch
  - model switch
  - settings update
  - tool approval
  - plan approval/rejection
  - subagent trace selection
- Contract-sensitive areas:
  - I1, I5, I7, I10
- Important note:
  - this is the densest control surface in the frontend
  - most regressions will likely reappear here first

### 3. `PlanView`

- File: `web/src/components/PlanView.tsx`
- Entrypoints:
  - refresh active session
  - start plan analysis
  - approve plan
  - reject plan
- Contract-sensitive areas:
  - I3, I7, I10
- Current stance:
  - no longer clears local timeline before requesting plan generation

### 4. `SessionTree`

- File: `web/src/components/SessionTree.tsx`
- Entrypoints:
  - fetch session tree
  - choose child session trace
- Contract-sensitive areas:
  - I1, I2, I4

## D. Backend-facing API inventory

### Authoritative CRUD and mutation APIs

- `createSession()`
- `getSession()`
- `listSessions()`
- `deleteSession()`
- `deleteSessionsBatch()`
- `cancelSession()`
- `compactSession()`
- `approveSession()`
- `rejectSession()`
- `resolveToolApproval()`
- `updateSession()`
- `updateSessionModel()`

### Authoritative refresh APIs

- `getMessages()`
- `getTraceEvents()`
- `fetchSessionTree()`

### Outstanding style note

There is still a direct settings mutation in `ChatView` via:

- `apiPost(/api/sessions/{id}/settings, ...)`

This is not currently a session-isolation bug, but it does not yet follow the same named API wrapper style as the rest of `web/src/api/sessions.ts`.

It should be tracked as a style-alignment item.

## E. Invalidation sources

These are all the currently known ways a session can become invalid in the frontend.

### Source 1. REST 404 on detail fetch

- example paths:
  - `openSession`
  - `refreshActive`

### Source 2. REST 404 on messages/events/tree fetch

- example paths:
  - `loadMessages`
  - `loadTraceEvents`
  - `fetchSessionTree`

### Source 3. REST 404 on mutation

- example paths:
  - `sendChat`
  - `approvePlan`
  - `rejectPlan`
  - `resolveToolApproval`
  - `compactSession`
  - `switchModel`

### Source 4. Authoritative list refresh pruning

- path:
  - `loadSessions`

### Source 5. Websocket reconnect existence check

- path:
  - `connectWs` abnormal close retry branch

## F. Current gaps and attention points

This inventory is mostly healthy now, but a few attention points remain.

### Gap 1. Settings mutation wrapper consistency

- Location: `ChatView.updateSettings()`
- Severity: low
- Problem:
  - not routed through named session API helper
- Impact:
  - style drift, not session corruption

### Gap 2. Cancellation semantics have not yet been fully audited

- Location:
  - `ChatView.handleCancel()`
  - backend cancel flow
- Severity: medium
- Problem:
  - cancellation affects running state and user expectations
  - we have not yet fully mapped whether local state always converges after cancel

### Gap 3. Local clear semantics still need explicit UX guidance

- Location:
  - `chatStore.clear()`
  - `ChatView.handleClearConversation()`
- Severity: medium
- Problem:
  - technically allowed as a local projection reset
  - but still easy to misuse or misinterpret as “server conversation cleared”

## G. Review checklist for this inventory

When touching session code, ask:

- Is this path listed here?
- If not, why can it mutate session behavior without being in the inventory?
- Which contract pattern does it follow?
- What is the 404 behavior?
- What is the non-404 failure behavior?
- Can this path leak state across sessions?

If those questions cannot be answered cleanly, the change is not ready.
