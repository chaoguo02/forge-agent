# Session End-to-End Validation Matrix

Last updated: 2026-07-20

Related documents:

- `docs/sessions/session-consistency-contract.md`
- `docs/sessions/session-entrypoint-inventory.md`

## Why this document exists

The contract defines the rules.
The inventory defines the entrypoints.

This document defines how we validate that the session system actually behaves according to those rules.

The objective is to stop relying on “it looks fixed” and instead validate session behavior by scenario.

## How to use this matrix

Each scenario below includes:

- user goal
- trigger path
- critical contract rules
- expected visible behavior
- failure signs
- priority

Recommended execution order:

1. P0 scenarios first
2. then P1 scenarios
3. then P2 polish scenarios

## Priority model

### P0

If this fails, session isolation or truth convergence is broken.

### P1

If this fails, the system is still usable, but user trust or recovery behavior is weak.

### P2

If this fails, the system still works, but semantics, polish, or UX clarity are incomplete.

---

## P0 scenarios

### S1. Create session A, send a message, and observe local growth only in A

- User goal:
  - create a fresh session and use it normally
- Trigger paths:
  - `SessionSidebar.createSession`
  - `sessionStore.createSession`
  - `sessionStore.openSession`
  - `ChatView.connectWs`
  - `chatStore.sendChat`
- Contract rules:
  - I1, I2, I5
- Expected behavior:
  - a new session appears in the sidebar
  - that session becomes active
  - websocket binds to that session
  - user message appears in that session timeline
  - subsequent live events append only to that session bucket
- Failure signs:
  - message appears in the wrong session
  - timeline remains shared across sessions
  - no websocket rebinding on active session change

### S2. Create session B and verify it does not inherit A’s timeline

- User goal:
  - start a second session without contamination from the first
- Trigger paths:
  - `SessionSidebar.createSession`
  - `sessionStore.createSession`
  - `sessionStore.openSession`
  - `ChatView` session-change effects
- Contract rules:
  - I1, I2
- Expected behavior:
  - B opens as a fresh session
  - A’s messages, approvals, child trace state, and running indicators do not appear in B
  - B may have default local mode/model, but not A’s timeline
- Failure signs:
  - A’s old messages still visible in B
  - approvals or trace cards from A appear in B
  - B starts with stale event sidebar data from A

### S3. Switch from B back to A and verify A restores correctly

- User goal:
  - revisit a previous session without losing its local projection
- Trigger paths:
  - `SessionSidebar.openSession`
  - `sessionStore.openSession`
  - `chatStore.loadMessages`
  - `chatStore.loadTraceEvents`
  - `chatStore.connectWs`
- Contract rules:
  - I1, I2, I5
- Expected behavior:
  - A becomes active again
  - A’s messages and trace history are restored
  - B’s current local UI state does not stay visible
  - websocket rebinds to A
- Failure signs:
  - mixed timeline from A and B
  - stale active detail from the wrong session
  - events continue streaming from B after switching to A

### S4. Delete the active session and verify full convergence

- User goal:
  - remove the current session and avoid ghost UI
- Trigger paths:
  - `SessionSidebar.handleDelete`
  - `sessionStore.deleteSession`
  - `sessionStore.loadSessions`
  - `chatStore.pruneSessions`
- Contract rules:
  - I3, I4, I5, I9
- Expected behavior:
  - delete is sent to backend
  - after success, the session disappears from sidebar
  - if it was active, `activeId` clears or a different valid session becomes active
  - active websocket binding is removed if it belonged to that session
  - old center-panel data disappears because the session is no longer valid
- Failure signs:
  - deleted session still selected
  - center panel still shows deleted session content
  - websocket continues trying to stream for deleted session
  - one store forgets the session but another still keeps it

### S5. Delete a non-active session and verify the active session stays untouched

- User goal:
  - clean up another session while continuing work in the current one
- Trigger paths:
  - `SessionSidebar.handleDelete`
  - `sessionStore.deleteSession`
  - `sessionStore.loadSessions`
- Contract rules:
  - I1, I3, I9
- Expected behavior:
  - non-active session disappears from sidebar after success
  - active session view remains unchanged
  - active websocket remains bound to the current session
- Failure signs:
  - current session view clears unexpectedly
  - activeId changes even though deleted session was not active
  - active chat bucket is pruned accidentally

### S6. Force a session 404 and confirm both stores invalidate together

- User goal:
  - ensure stale sessions do not survive after backend truth says they are gone
- Trigger paths:
  - any 404-producing path such as:
    - `refreshActive`
    - `loadMessages`
    - `loadTraceEvents`
    - `switchModel`
    - `compactSession`
    - `resolveToolApproval`
- Contract rules:
  - I4
- Expected behavior:
  - `sessionStore` removes active/detail/tree state for that session
  - `chatStore` removes the session bucket
  - websocket binding is cleared if it belonged to that session
  - no ghost session remains rendered
- Failure signs:
  - sidebar says session is gone but center panel still renders it
  - center panel clears but sidebar still thinks it is active
  - websocket still reconnects for the missing session

### S7. Switch sessions while one is still streaming

- User goal:
  - move to another session during live execution without cross-stream contamination
- Trigger paths:
  - `ChatView` session-change effect
  - `chatStore.disconnectWs`
  - `chatStore.connectWs`
  - `chatStore.handleWsEvent`
- Contract rules:
  - I1, I5
- Expected behavior:
  - leaving session A disconnects its live binding
  - opening session B binds websocket to B only
  - incoming events from A must not mutate B’s timeline
- Failure signs:
  - A’s running events appear in B
  - both sessions appear to stream into the same center panel
  - old reconnect timer reattaches the wrong session

---

## P1 scenarios

### S8. Abnormal websocket close should reconnect only if the session still exists

- User goal:
  - recover from transient disconnect without resurrecting deleted sessions
- Trigger paths:
  - `chatStore.connectWs` abnormal close branch
- Contract rules:
  - I5, I6
- Expected behavior:
  - on abnormal close, client marks a reconnect delay
  - before reconnecting, it checks whether the session still exists
  - if session still exists, reconnect proceeds
  - if backend says 404, session is invalidated instead
- Failure signs:
  - repeated blind reconnect loop after delete
  - stale session remains active only because reconnect keeps retrying

### S9. Plan generation must not locally clear the session before backend accepts

- User goal:
  - ask for a plan without losing current visible state on request failure
- Trigger paths:
  - `PlanView` plan-start action
  - `api.chat(...)`
- Contract rules:
  - I3, I7, I10
- Expected behavior:
  - plan request is sent
  - if accepted, execution moves forward normally
  - if request fails, previous visible session projection is still intact
- Failure signs:
  - center panel empties before backend confirms request
  - failed request leaves the session looking erased

### S10. Delete failure must preserve current view

- User goal:
  - avoid data loss if delete fails
- Trigger paths:
  - `SessionSidebar.handleDelete`
  - `sessionStore.deleteSession`
- Contract rules:
  - I3, I8
- Expected behavior:
  - if delete request fails with non-404 error, active session content remains
  - sidebar selection remains stable
  - no local ghost deletion occurs
- Failure signs:
  - current view clears even though delete failed
  - session disappears locally but returns later on refresh

### S11. Tool approval failure should restore pending approval locally

- User goal:
  - avoid losing the approval card on transient failure
- Trigger paths:
  - `chatStore.resolveToolApproval`
- Contract rules:
  - I8
- Expected behavior:
  - approval card is removed optimistically
  - if request fails without 404, the approval card is restored
  - an error is shown
- Failure signs:
  - approval card disappears permanently after network failure
  - session is invalidated on a normal transient failure

### S12. Model switch failure should preserve session identity

- User goal:
  - switch model without risking session corruption
- Trigger paths:
  - `chatStore.switchModel`
- Contract rules:
  - I4, I8
- Expected behavior:
  - on non-404 failure, session remains active
  - error is shown
  - no unrelated session state is cleared
- Failure signs:
  - model switch failure clears the whole session view
  - wrong session becomes active afterward

### S13. Compact failure should preserve current session projection

- User goal:
  - compact history without losing visible state on failure
- Trigger paths:
  - `chatStore.compactSession`
- Contract rules:
  - I3, I4, I8
- Expected behavior:
  - success returns true
  - 404 invalidates session
  - non-404 failure leaves current projection intact and records error
- Failure signs:
  - failed compact clears visible history
  - compact 404 leaves ghost session active

### S14. Refresh page and reopen active session cleanly

- User goal:
  - see stable recovery after a page reload
- Trigger paths:
  - app bootstrap
  - `SessionSidebar.loadSessions`
  - `openSession`
  - `ChatView` session-change effects
- Contract rules:
  - I1, I9
- Expected behavior:
  - sidebar repopulates from backend
  - opening a session restores its own history only
  - no contamination from previously viewed session
- Failure signs:
  - active detail from one session but timeline from another
  - stale cached bucket shown before real open completes and never corrected

---

## P2 scenarios

### S15. Local clear should be visually understood as local only

- User goal:
  - clear the current local projection without misinterpreting it as server deletion
- Trigger paths:
  - `ChatView.handleClearConversation`
  - `chatStore.clear`
- Contract rules:
  - I10
- Expected behavior:
  - current visible projection resets locally
  - session still exists in sidebar
  - reopening or reloading can repopulate data from backend sources
- Failure signs:
  - user believes the session was deleted server-side
  - local clear triggers unintended session invalidation

### S16. Session tree view should follow active session only

- User goal:
  - inspect child sessions for the current active session
- Trigger paths:
  - `SessionTree.fetchSessionTree`
  - `chatStore.setViewingChild`
- Contract rules:
  - I1, I2, I4
- Expected behavior:
  - tree belongs to current active session
  - child selection does not persist across unrelated sessions
- Failure signs:
  - tree from A still visible in B
  - child trace drawer opens wrong session

### S17. Settings changes should not affect the wrong session

- User goal:
  - toggle thinking/permission/effort for current session only
- Trigger paths:
  - `ChatView.updateSettings`
- Contract rules:
  - I1, I2, I7
- Expected behavior:
  - setting applies only to the active session
  - changing sessions does not visually retroactively mutate another session’s settings presentation
- Failure signs:
  - settings toggle leaks across sessions
  - stale controls remain visible after session switch

### S18. Cancel running session should converge to stable visible state

- User goal:
  - stop an in-flight run and keep UI believable
- Trigger paths:
  - `ChatView.handleCancel`
  - `cancelSession`
- Contract rules:
  - I3, I8
- Expected behavior:
  - cancellation request is sent
  - session eventually stops showing as running after authoritative update
  - existing timeline remains intact
- Failure signs:
  - session keeps appearing as running forever
  - cancellation clears unrelated local state
  - another session’s UI changes instead

---

## Suggested execution order for manual validation

Use this order if we are manually validating after each batch:

1. S1
2. S2
3. S3
4. S4
5. S5
6. S6
7. S7
8. S8
9. S11
10. S13
11. S14
12. S18

This order is designed to surface truth-convergence failures before UX-polish issues.

## Suggested next implementation focus after this matrix

Now that the contract and inventory are frozen, future work should be split into batches:

### Batch A. Remaining session semantics alignment

Focus:

- `updateSettings()` wrapper alignment
- cancellation flow audit
- explicit `clear()` semantics and UI wording

### Batch B. Scenario-driven regression protection

Focus:

- add lightweight reproducible checks for P0 scenarios
- decide whether to formalize them as automated frontend tests or scripted manual checks

### Batch C. Higher-level UI/UX clarification

Focus:

- make local clear vs server lifecycle easier to distinguish
- improve failure messaging when a session is invalidated by 404

## Exit criteria for “session layer is stable”

We should not call the session layer stable until:

- all P0 scenarios pass
- no component performs pre-success destructive UI changes
- every 404 path converges `sessionStore` and `chatStore`
- websocket reconnect never resurrects deleted sessions
- switching between active sessions never leaks timeline/events/approvals across buckets
