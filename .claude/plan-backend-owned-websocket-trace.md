# Plan: backend-owned WebSocket trace persistence and frontend timeline simplification

## Diagnosis

The current project is already partially backend-owned, but not cleanly enough:

- Runtime events are emitted in the backend through `SessionRuntime` → `EventLog` → `EventBus`.
- `EventBus` translates raw agent events into typed WebSocket messages.
- The frontend receives those typed messages and stores them in Zustand as ephemeral UI state.
- Refresh/replay is backed by `GET /api/sessions/{session_id}/trace/events`, but that endpoint reconstructs typed WS messages by scanning raw JSONL event log files through `SessionService.get_events()`.
- Some backend-originated typed events, especially direct `publish_typed()` / `publish_raw()` events like approval events, streaming deltas, and worktree resolution, are not guaranteed to be in the raw EventLog path.
- Frontend `chatStore` currently owns too much timeline reconstruction logic: load messages, load trace events, filter lifecycle statuses, merge, dedupe, restore plan approval from trace, then append live WS events.

So the current answer is:

- Data is not purely frontend-recorded.
- But the frontend is currently doing too much state reconstruction.
- Backend persistence is file-based JSONL for raw agent events, not a normalized database-backed trace source.
- The typed WS stream should become backend-persisted and queryable as the source of truth.

## Storage recommendation

Use both durable DB and Redis, but for different responsibilities.

### Durable DB: SQLite now, Postgres/MySQL later

For this repo's current architecture, the immediate durable trace store should be added to the existing SQLite-backed storage layer because:

- The app already uses `SessionStore` / `SqliteStorageBackend` for sessions, messages, stats, diffs, and memory.
- SQLite WAL is already enabled.
- Adding Redis/MySQL immediately would expand deployment and dependency surface before the data model is settled.
- The trace table belongs next to sessions/messages because it is part of the session audit trail.

If deploying multi-user or multi-server, upgrade the same storage protocol to Postgres or MySQL. I would prefer Postgres for JSONB/event querying, but MySQL is also acceptable if the project standardizes on it.

### Redis: optional realtime buffer / short-term memory

Redis is useful, but not as the only source of truth:

- Good for recent event stream buffers, pub/sub, reconnect catch-up, and short-lived agent working state.
- Good for TTL-based short-term memory.
- Not ideal as the only authoritative audit/history store unless Redis persistence and retention policies are carefully configured.

Recommended split:

- DB: durable session messages, typed trace events, review/audit trail.
- Redis: hot stream cache, reconnect buffer, optional short-term memory, pub/sub if multiple backend workers exist.

## Target architecture

```
Agent runtime
  ↓ raw Event
EventBus.translate()
  ↓ typed WsMessage
TraceStore.append(session_id, typed_event)
  ↓
WebSocket broadcast
  ↓
Frontend renders backend-owned timeline
```

The key change: every typed event that can reach the frontend over WS should also be persisted by the backend before or alongside broadcast.

## Backend implementation steps

1. Add a trace event table to SQLite

   In `app/storage/sqlite.py`, add something like:

   - `session_trace_events`
     - `id INTEGER PRIMARY KEY AUTOINCREMENT`
     - `session_id TEXT NOT NULL`
     - `seq INTEGER NOT NULL`
     - `event_type TEXT NOT NULL`
     - `timestamp TEXT NOT NULL`
     - `event_json TEXT NOT NULL`
     - `source TEXT NOT NULL DEFAULT 'event_bus'`
     - `child_session_id TEXT NOT NULL DEFAULT ''`
     - unique index `(session_id, seq)`
     - index `(session_id, id)`
     - index `(session_id, event_type)`

   Use monotonically increasing `seq` per session so reconnect/catch-up can ask for `after_seq`.

2. Extend the storage protocol

   In `app/storage/protocol.py` add methods:

   - `insert_trace_event(session_id, event_type, event_json, timestamp, child_session_id='', source='event_bus') -> int`
   - `list_trace_events(session_id, after_seq=0, limit=200) -> list[dict]`
   - optionally `delete_trace_events(session_id)` if session deletion does not cascade through a shared helper.

3. Persist typed events in `EventBus`

   Update `server/services/event_bus.py` so:

   - `publish()` translates raw events to typed WS messages.
   - For each typed message, call a new trace recorder before broadcast.
   - `publish_typed()` and `publish_raw()` also persist their typed messages.
   - Messages get a backend sequence number before being sent, e.g. `seq` added to event JSON.

   This ensures approval events, worktree events, and other direct WS events are not lost on refresh.

4. Replace file-scan trace endpoint with DB-backed trace endpoint

   Update `GET /api/sessions/{session_id}/trace/events` in `server/routers/sessions.py`:

   - Read from `session_trace_events` by `after_seq` and `limit`.
   - Keep `after` backward-compatible for current frontend/tests, mapping it to old offset behavior if needed.
   - Return typed WS-format event objects directly.

   Keep the JSONL EventLog as a lower-level raw audit/replay artifact for now, but stop using it as the frontend trace source.

5. Add optional Docker services

   Add `docker-compose.yml` only if we decide to standardize external services now:

   - `redis:7-alpine` for hot stream / short-term memory.
   - `postgres:16-alpine` or `mysql:8` for future durable storage.

   For this pass, I recommend adding compose as optional infrastructure, not making app startup require it yet.

## Frontend implementation steps

1. Treat backend trace as source of truth

   Update `web/src/stores/chatStore.ts`:

   - Track `lastTraceSeq` per session.
   - `loadTraceEvents(sessionId)` loads typed events from backend and stores them.
   - WS `onMessage` appends events that already include `seq`.
   - On reconnect, fetch `trace/events?after_seq=<lastTraceSeq>` before or after reconnecting to fill gaps.

2. Reduce timeline reconstruction in the frontend

   Current frontend merges messages and WS events locally. Keep this in a smaller form initially, but remove responsibility for reconstructing plan approval from indirect raw logs.

   Better end state:

   - Backend provides either:
     - `GET /api/sessions/{id}/trace/events` for events only, and frontend still merges messages, or
     - `GET /api/sessions/{id}/timeline` for pre-composed message/event timeline.

   I recommend a staged approach:

   - Phase A: keep current frontend rendering components, but consume DB-backed typed events.
   - Phase B: add backend `/timeline` endpoint and simplify frontend merge/dedupe logic.

3. Plan approval restoration

   The frontend can still infer `planApproval` from persisted `plan_ready`, but that event will now come from DB, not JSONL reconstruction.

   Later, plan approval state should become explicit backend session state rather than frontend-restored UI state.

4. Tests

   Update e2e mocks to include `seq` where useful.
   Add backend tests that verify:

   - raw runtime event → EventBus → persisted typed trace event
   - `publish_typed()` events are persisted
   - `GET /trace/events` returns persisted events after refresh
   - `after_seq` returns only new events

## Migration strategy

Do not delete existing JSONL behavior in the first pass.

- JSONL remains raw low-level replay/debug log.
- DB trace becomes frontend source of truth.
- Existing sessions without DB trace can optionally fall back to JSONL reconstruction if DB returns empty.

This gives backward compatibility while moving the product architecture in the right direction.

## Implementation phases

### Phase 1 — durable typed trace in SQLite

- Add schema and storage methods.
- Persist all typed WebSocket events from EventBus.
- Serve `/trace/events` from DB with JSONL fallback.
- Add backend tests.

### Phase 2 — frontend consumes backend-owned trace

- Add `seq` tracking in `chatStore`.
- Add reconnect catch-up by `after_seq`.
- Keep rendering components but reduce ad-hoc trace restoration where possible.
- Update frontend tests.

### Phase 3 — optional Redis / external DB deployment

- Add optional `docker-compose.yml` for Redis and Postgres/MySQL.
- Add config env vars but keep SQLite default.
- Use Redis only for hot stream/cache once DB trace is stable.

## Recommendation

Implement Phase 1 and Phase 2 first with SQLite, because it matches the current repo and fixes the actual architectural issue without requiring new services. Then add Redis/Postgres/MySQL as optional deployment infrastructure once the trace data model is proven.
