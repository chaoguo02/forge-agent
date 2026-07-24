# Trace storage deployment notes

Grace Code now persists typed WebSocket trace events in the durable session database. SQLite remains the default local backend.

## Current runtime: no Redis required

Redis is not supported as an application dependency yet. The server uses:

- SQLite for durable typed trace events.
- An in-process bounded trace cache for hot reconnect reads.
- JSONL EventLog as a raw low-level replay/debug fallback.

The in-process cache intentionally has the same product role Redis should take later, but it works without Docker or external services.

## Optional Docker services

The root `docker-compose.yml` is strictly optional and profile-gated. It is a placeholder for future Redis/Postgres work and is not required to run Grace Code today.

If Docker is available and you explicitly want to inspect the future infrastructure shape:

```bash
docker compose --profile optional-infra up -d
```

This starts:

- Redis: future hot event buffers, pub/sub, reconnect cache, short-term TTL memory.
- Postgres: future durable relational storage for sessions/messages/typed trace events.

## Storage responsibilities

- Durable DB: session messages, typed trace events, review/audit data.
- In-process cache today: single-process hot reconnect cache.
- Redis later: multi-process hot event cache, pub/sub, short-term memory.
- JSONL EventLog: raw low-level replay/debug fallback.

## Redis follow-up

`docs/todo.md` tracks the follow-up to replace the in-process trace cache with Redis Streams/pub-sub once Redis support is actually implemented.

## Next migration step

When external DB support is added, implement the existing storage protocol methods for the new backend, including typed trace methods:

- `insert_trace_event`
- `list_trace_events`

The frontend should not need to change when durable storage moves from SQLite to Postgres.
