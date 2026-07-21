# Session P0 Manual Checklist

Last updated: 2026-07-20

Related documents:

- `docs/sessions/session-consistency-contract.md`
- `docs/sessions/session-entrypoint-inventory.md`
- `docs/sessions/session-e2e-validation-matrix.md`

## Purpose

This is the shortest practical manual validation pass for session isolation.

Use this checklist after session-layer changes, or before declaring the current session architecture stable.

## How to run it

- Run the web app and backend normally.
- Use a clean browser tab.
- Prefer a repo/task that produces visible websocket events.
- Follow the steps in order.

If a step fails, stop and record:

- exact step id
- visible symptom
- active session id if available
- whether websocket was connected

## Pass criteria

Session P0 can be considered healthy only if all checks below pass.

---

## C1. Create session A and verify isolated startup

Steps:

1. Click `+ New Session`
2. Wait for the new session to become active
3. Send a simple prompt, for example:
   - `Read README.md and summarize the project`

Expected:

- a new session appears in the sidebar
- it becomes the active session
- the center panel shows only this session’s messages/events
- live trace starts attaching to this session only

Fail if:

- no new session appears
- the wrong session becomes active
- old messages from another session are visible immediately

---

## C2. Create session B and verify it does not inherit A

Steps:

1. While session A still exists, click `+ New Session`
2. Do not send a message yet
3. Inspect the center panel, plan view, trace sidebar, and subagent area

Expected:

- session B opens as a fresh session
- A’s messages are not visible in B
- A’s approvals are not visible in B
- A’s trace/event state is not visible in B

Fail if:

- B opens with A’s timeline
- B shows A’s pending plan/tool approvals
- B shows A’s child trace or background agent state

---

## C3. Switch back to A and verify correct restoration

Steps:

1. Click session A in the sidebar
2. Wait 1-2 seconds for detail/messages/events refresh

Expected:

- A becomes active
- A’s own messages return
- B’s blank/fresh state no longer dominates the center panel
- live binding now belongs to A

Fail if:

- timeline is mixed between A and B
- header/detail looks like A but timeline looks like B
- event stream continues from B after switching

---

## C4. Quick-switch race check

Steps:

1. Click A
2. Immediately click B
3. Immediately click A again
4. Repeat this a few times quickly

Expected:

- the final visible session matches the final clicked session
- detail panel, timeline, and trace all converge to the same final session
- no stale detail overwrite appears after a delayed response returns

Fail if:

- final active highlight is A but detail/timeline belong to B
- the center panel visibly “snaps back” to an older session after a delay

---

## C5. Delete a non-active session

Steps:

1. Keep session A active
2. Delete session B from the sidebar

Expected:

- B disappears from the sidebar after confirmation
- A remains active
- A’s center-panel content remains untouched
- websocket remains attached to A

Fail if:

- A clears unexpectedly
- active session changes even though B was deleted
- trace/events reset for A without cause

---

## C6. Delete the active session

Steps:

1. Make sure session A is active
2. Delete session A
3. Observe sidebar, center panel, and trace area

Expected:

- A disappears from sidebar
- active session clears or moves to another valid session
- A’s old content no longer remains rendered as if still valid
- websocket binding for A is gone

Fail if:

- deleted session still appears active
- deleted session content remains in the center panel as if valid
- websocket keeps behaving as if deleted session still owns the stream

---

## C7. Streaming switch isolation

Steps:

1. Create session C
2. Send a prompt likely to generate multiple steps/events
3. While C is still running, switch to another existing session
4. Watch the center panel and trace sidebar for 10-20 seconds

Expected:

- after switching away, the newly active session owns the visible stream
- C’s later events do not leak into the new active session view
- no mixed timeline appears

Fail if:

- C’s live events continue to append into another session’s timeline
- the visible stream belongs to multiple sessions at once

---

## C8. Refresh recovery

Steps:

1. Open any valid session with visible history
2. Refresh the browser page
3. Re-open that session from the sidebar if needed

Expected:

- sessions reload from backend
- reopening the session restores its own history
- no other session’s timeline is shown by mistake

Fail if:

- detail and timeline belong to different sessions
- stale cached UI remains and never converges

---

## C9. 404 convergence check

This one can be done when a session becomes invalid by backend deletion, or during targeted debugging.

Steps:

1. Open a session
2. Cause that session to become unavailable on the backend
3. Trigger one of these paths:
   - reopen it
   - refresh active
   - load messages/events/tree
   - compact
   - switch model
4. Observe sidebar and center panel

Expected:

- both metadata and UI projection converge away from the missing session
- no ghost active session remains
- websocket does not keep reconnecting to the missing session

Fail if:

- sidebar and center panel disagree about whether the session exists
- a deleted/missing session keeps reappearing locally

---

## Recommended execution order

Run in this order:

1. C1
2. C2
3. C3
4. C4
5. C5
6. C6
7. C7
8. C8
9. C9

## Suggested result format

When you run the checklist, record results like this:

```md
- C1: pass
- C2: pass
- C3: pass
- C4: fail — detail briefly snapped to old session after rapid switching
- C5: pass
- C6: pass
- C7: pass
- C8: pass
- C9: not run
```

## Exit rule

Do not continue broad session refactors if:

- any of C1-C7 fails

Fix the failed scenario first, then rerun the checklist.
