# HITL Approval Pipeline Audit

**Date:** 2026-07-24  
**Scope:** `hitl/pipeline.py`, `server/services/approval_broker.py`, `server/services/agent_service.py`  
**Conclusion:** The design is architecturally correct — `threading.Event` with 60s timeout ensures no permanent deadlock. One real UX bug (cancel latency) and one state-machine edge case.

---

## Architecture verified correct

### Threading model

```
Agent thread (SessionRuntime, background)     HTTP/WS thread (async event loop)
  │                                              │
  │  broker.wait_for_decision(request)            │
  │    → pending.event.wait(timeout=60s)          │
  │    [BLOCKED]                                  │
  │                                              │  POST /tool-approve
  │                                              │    → broker.resolve(req_id, decision)
  │                                              │      → pending.event.set()
  │    [UNBLOCKED]                                │
  │    → returns PromptDecision                   │
```

- `threading.Lock` protects only brief dict operations on `_pending`
- `threading.Event.wait(timeout)` always returns — no infinite hang possible
- `resolve()` is called from a different thread → `event.set()` → unblocks agent thread
- No deadlock: lock is not held during `wait()`

### State transitions verified

| State | Action | Next State |
|-------|--------|-----------|
| No pending | `resolve()` | Returns False (no-op) |
| Pending | `wait_for_decision` timeout | Returns DENY with note "timed out" → timeout WS event pushed |
| Pending | `resolve(req_id, ALLOW_ONCE)` | Event.set() → agent continues with ALLOW |
| Pending | `resolve(req_id, DENY)` | Event.set() → agent continues with DENY |
| Pending, frontend disconnected | timeout expires after 60s | auto-DENY → agent continues |

### No signal-before-wait race

The push of `approval_required` WS event happens INSIDE `wait_for_decision()`, AFTER the request is in `_pending` dict, BEFORE `event.wait()`. The frontend can't resolve before the request exists in the dict.

---

## Issue 1: Cancel latency — up to 60s if approval pending

**File:** `server/services/approval_broker.py:132` + `server/services/agent_service.py:1019`

**Problem:** When the user cancels a session while the agent is blocked in `broker.wait_for_decision()`, the agent stays blocked for up to 60s (the approval timeout). The `CancellationToken.cancel()` wakes the agent's step-boundary check, but the agent is mid-step, blocked on `pending.event.wait()`.

**Flow:**
1. Agent calls tool → pipeline → `broker.wait_for_decision()` → `pending.event.wait(60s)` [BLOCKED]
2. User clicks cancel → `cancel_session()` → `token._event.set()` (wakes step check, but agent is mid-step)
3. Agent continues to wait for pending.event → 60s timeout → returns DENY
4. Agent loop next step → checks `is_cancelled` → terminates

**Impact:** Cancel button appears unresponsive for up to 60 seconds.

**Fix:** Add `cancel_pending()` to ApprovalBroker, called from cancel_session:

```python
# approval_broker.py
def cancel_pending(self) -> int:
    with self._lock:
        count = len(self._pending)
        for req_id, pending in self._pending.items():
            pending.decision = PromptDecision(action=PromptAction.DENY, note="Session cancelled")
            pending.event.set()
        self._pending.clear()
        return count
```

```python
# agent_service.py cancel_session
def cancel_session(self, session_id, detail=""):
    broker = self._runtime.get_approval_broker(session_id)
    if broker is not None:
        broker.cancel_pending()
    return self._runtime.cancel_session(session_id, detail=detail)
```

---

## Issue 2: `_handle_non_tool_action` skips COMPLETING transition

**File:** `agent/core.py:1829`

**Problem:** `_handle_non_tool_action` calls `state_machine.complete()` directly, which transitions `RUNNING → COMPLETED`. But the task state machine's valid transitions from RUNNING are `[COMPLETING, FAILED, CANCELLED]` — not COMPLETED.

**Trigger:** MockBackend returns `TOOL_CALL` with empty `tool_calls=[]` (used in tests), or unknown action_type.

**Impact:** ValueError crash in `task_state_machine.py:342`.

**Fix:** (already applied) — go through COMPLETING first:
```python
if state_machine.state is not TaskState.COMPLETING:
    state_machine.transition(TaskState.COMPLETING, detail or "auto-complete")
state_machine.complete(...)
```

---

## Verified safe (no bugs)

| Concern | Verdict |
|---------|---------|
| Two concurrent approvals from same step | Each gets independent PendingApproval with unique request_id. Handled independently. |
| Missing ApprovalBroker | `_ensure_approval_broker()` creates on demand. Never waits without a broker. |
| Frontend disconnect during approval | 60s timeout → auto-DENY → agent continues. Frontend card removed via `WsApprovalTimeout`. |
| Duplicate resolve() | Idempotent — pop from dict, subsequent resolve returns False. |
| ApprovalBroker leak | One per session, lifetime matches session. No explicit cleanup needed (sessions are finite). |
| Concurrent fan-out + approval | `Serial` concurrency for write tools enforces one-at-a-time. |

---

## Unchanged — confirmed correct

- `hitl/pipeline.py` 6-layer evaluator: deny > ask > allow with glob patterns
- `PermissionPipeline` threading model: synchronous callback layer (Layer 6) blocks agent thread
- `web_confirm_callback` closure captures session_id + broker — no cross-session leaks
