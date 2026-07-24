Problem Statement
当前 Grace Code Web 前端对 WebSocket 运行轨迹承担了过多“事实来源”和 timeline 重建责任。虽然运行事件由后端 runtime 产生，并且存在 JSONL 事件日志，但前端目前仍需要在本地 Zustand 中维护实时 WebSocket 事件、刷新后重新请求 trace、与 messages 合并、过滤 lifecycle event、dedupe、恢复 plan approval 状态，并基于这些临时状态渲染 Chat / Trace / Review。

这导致几个用户可感知的问题：

页面刷新、WebSocket 断线重连、多 tab 打开时，用户看到的运行历史可能不稳定。
一些通过后端直接推送的 typed WebSocket event 不一定能完整恢复。
前端渲染逻辑被迫理解过多后端运行语义。
Chat、Review、Trace 这些页面都依赖同一类运行轨迹，但当前没有一个统一、数据库持久化的后端事实源。
用户希望 plan、tool approval、diff、review、verification 这些 session 工作流产物都围绕 Chat/session 展示，而不是由前端临时拼装多个近似页面状态。
从产品角度，WebSocket event 应该是后端拥有、后端持久化、前端只消费和渲染的数据。前端不应该是运行轨迹的事实记录者。

Solution
将 WebSocket typed event 的事实来源迁移到后端。

后端在将 runtime event 翻译成 typed WebSocket message 后，应将该 typed event 持久化到 session trace store，再广播给 WebSocket 客户端。前端初始化页面、刷新页面、断线重连时，都从后端 trace endpoint 获取已持久化事件，并使用 WebSocket 只接收增量。

初始实现应优先使用当前项目已有的 SQLite storage layer，以最小部署成本完成数据模型和行为重构。Redis 和外部关系型数据库可以作为后续可选部署能力加入。

推荐架构：


Agent runtime
  ↓ raw runtime Event
EventBus translation
  ↓ typed WebSocket event
Backend trace store append
  ↓
WebSocket broadcast
  ↓
Frontend render
数据职责划分：


Durable DB
  - sessions
  - messages
  - typed trace events
  - review/audit history

Redis
  - hot event stream cache
  - reconnect buffer
  - pub/sub for multi-worker deployments
  - short-term memory with TTL
  - ephemeral running state
当前阶段先实现：


SQLite-backed typed trace persistence
后续再可选加入：


Redis + Postgres/MySQL via Docker Compose
User Stories
As a Grace Code user, I want session execution events to survive page refreshes, so that I can continue reviewing a run without losing context.

As a Grace Code user, I want WebSocket disconnections to recover missing events, so that temporary network issues do not corrupt the visible timeline.

As a Grace Code user, I want Chat to show the same plan, tool, diff, and status events after refresh, so that the session feels stable and trustworthy.

As a Grace Code user, I want plan approval state to restore from backend-owned state, so that I do not lose the ability to approve or reject a plan after reloading the page.

As a Grace Code user, I want Review to rely on the same backend-owned session trace as Chat, so that quality summaries and verification signals match what happened in the run.

As a Grace Code user, I want Trace to show an authoritative event history, so that it can be used for debugging and not just live observation.

As a Grace Code user, I want the frontend to render session history consistently whether events arrived live or were loaded later, so that I do not see duplicates or missing cards.

As a Grace Code user, I want long-running sessions to remain inspectable after browser close/reopen, so that I can step away and resume work.

As a Grace Code user, I want pending approvals to remain recoverable, so that an approval request does not vanish from the UI if the frontend reconnects.

As a Grace Code user, I want plan-ready events to be recoverable from backend trace, so that planning mode remains usable after refresh.

As a Grace Code user, I want worktree resolution events to persist, so that I can audit whether a child worktree was applied, discarded, or retained.

As a Grace Code user, I want subagent lifecycle events to persist, so that subagent progress remains visible after reload.

As a Grace Code user, I want tool calls and observations to persist in their typed frontend-ready shape, so that the UI does not need to reconstruct them from low-level raw logs.

As a Grace Code user, I want event ordering to be stable, so that timeline rendering does not jump around after refresh.

As a Grace Code user, I want reconnect catch-up to fetch only missing events, so that the app does not reload the entire trace unnecessarily.

As a Grace Code user, I want duplicate events to be avoided, so that the timeline does not show the same tool call or observation twice.

As a Grace Code user, I want event history to be scoped per session, so that switching sessions does not mix timeline data.

As a Grace Code user, I want child session events to remain attributable to the parent session timeline, so that subagent activity stays understandable.

As a Grace Code user, I want child session events to preserve child session identity, so that the UI can render subagent lanes correctly.

As a Grace Code user, I want failed, cancelled, completed, and running states to persist clearly, so that session status remains accurate after reload.

As a Grace Code user, I want Review to summarize verification signals from backend-owned session data, so that build/test/lint state is reliable.

As a Grace Code user, I want Review to summarize changed files from backend-owned session data, so that I can trust the changed-file count.

As a Grace Code user, I want Chat to stay the primary workflow surface, so that plan and approval interactions are not split across redundant pages.

As a Grace Code user, I want the frontend to be simpler and more predictable, so that product behavior is easier to reason about.

As a frontend developer, I want a typed backend trace endpoint, so that React components can render event objects without reconstructing backend semantics.

As a frontend developer, I want each event to include a stable sequence number, so that reconnect catch-up and dedupe are straightforward.

As a frontend developer, I want WebSocket events and REST trace events to share the same shape, so that live and replay paths use the same rendering logic.

As a frontend developer, I want the store to track the last seen trace sequence per session, so that reconnect behavior is deterministic.

As a frontend developer, I want lifecycle filtering rules to be minimized in the frontend, so that UI code does not encode backend execution policy.

As a backend developer, I want the EventBus to persist every typed event it broadcasts, so that WebSocket delivery is not the only copy.

As a backend developer, I want direct typed event publishing to persist too, so that approval events and worktree events are recoverable.

As a backend developer, I want raw JSONL EventLog to remain available, so that low-level replay/debug workflows do not break.

As a backend developer, I want typed trace persistence to coexist with raw EventLog, so that migration is incremental and safe.

As a backend developer, I want the trace endpoint to read from durable storage first, so that frontend refresh no longer depends on scanning JSONL files.

As a backend developer, I want JSONL fallback for old sessions, so that existing historical sessions still render.

As a backend developer, I want the trace storage API behind the existing storage protocol, so that future Postgres/MySQL implementations can replace SQLite without changing routers.

As a backend developer, I want trace insertion to be best-effort but observable, so that event broadcasting is not blocked by transient persistence failures.

As a backend developer, I want event sequence generation to be per session, so that clients can request after_seq safely.

As a backend developer, I want trace events indexed by session and event type, so that Chat, Review, and Trace can query efficiently.

As a backend developer, I want session deletion to clean up trace events, so that storage does not leak orphaned trace history.

As an operator, I want SQLite to remain the default storage path, so that local development remains simple.

As an operator, I want optional Docker Compose services for Redis and relational DB, so that production-like deployments can be tested locally.

As an operator, I want Redis to be optional at first, so that the core app does not fail if Redis is not configured.

As an operator, I want external DB support to be introduced behind configuration, so that deployments can choose SQLite, Postgres, or MySQL based on scale.

As an operator, I want Redis to handle hot ephemeral state only, so that durable audit data does not disappear due to TTL expiry.

As an operator, I want durable event history in a relational DB, so that compliance/debug/review workflows can inspect previous sessions.

As a test author, I want backend tests for trace persistence, so that runtime event recording is verified independently of React.

As a test author, I want frontend tests to mock typed trace events with sequence numbers, so that replay and reconnect behavior is covered.

As a test author, I want existing e2e tests to continue validating Chat plan approval, Review readiness, and Trace rendering, so that the IA refactor remains protected.

As a maintainer, I want the data model to support both current UI and future /timeline endpoint, so that later frontend simplification is possible without another schema migration.

Implementation Decisions
The backend should own typed WebSocket event persistence.

Runtime raw events should still be generated by the existing agent runtime and raw EventLog path.

Event translation should continue to happen in the backend event bus layer.

The event bus should persist typed events in the same shape that is sent to the frontend.

The backend should assign a monotonically increasing per-session sequence number to each typed trace event.

The sequence number should be included in the event JSON sent over WebSocket.

The REST trace endpoint should return typed WebSocket-format events directly.

The REST trace endpoint should support sequence-based catch-up.

Existing offset-style trace loading should remain temporarily backward compatible.

The existing raw JSONL EventLog should remain as a raw replay/debug artifact.

The new durable typed trace store should become the frontend source of truth.

SQLite should be used first because the current project already uses SQLite-backed storage for sessions, messages, stats, diffs, and memory.

Redis should not be required for the first implementation phase.

Redis should be positioned as hot ephemeral infrastructure for reconnect buffers, pub/sub, short-term memory, and multi-worker coordination.

A relational database should remain the durable event/audit store.

If the project later moves beyond SQLite, Postgres is preferred for JSON event storage and querying.

MySQL remains acceptable if the project chooses MySQL as the standardized deployment database.

The storage protocol should be extended instead of hardcoding trace persistence directly into one router or service.

The durable trace schema should be session-scoped.

The durable trace schema should preserve event type, timestamp, child session id, source, sequence number, and full typed event payload.

Event persistence should happen for translated runtime events.

Event persistence should also happen for directly published typed events.

Directly published typed events include approval-required events, approval-timeout events, worktree resolution events, and streamed thought deltas.

The frontend should stop relying on reconstructed raw JSONL translation as the primary refresh source.

The frontend should maintain per-session last-seen trace sequence.

On WebSocket reconnect, the frontend should request missing trace events after the last seen sequence.

The frontend should render both loaded and live events through the same event rendering path.

Frontend timeline merging can remain in the first pass, but should become thinner.

A future backend /timeline endpoint may return pre-composed message/event timelines.

Plan approval restoration may still be inferred from persisted plan_ready in the first phase.

A later phase should make plan approval state explicit backend session state instead of purely frontend-restored UI state.

Docker Compose should be optional initially.

Optional Docker Compose should include Redis and one durable relational database service.

The application should continue to work without Docker services in local development.

Existing JSONL trace behavior should be retained as fallback for older sessions that do not have DB-backed typed trace events.

Session deletion should delete associated typed trace events.

Trace persistence should be designed as append-only.

Updating historical trace events should not be part of the core design.

Redaction or payload-size policy should be considered before storing large tool outputs at scale.

The initial version may store full typed event payloads in JSON text because this matches current typed event transport shape.

Later versions may add indexed extracted columns for query-heavy Review dashboard features.

Testing Decisions
The highest-value test seam is the backend trace endpoint plus event bus persistence behavior.

Backend tests should validate externally observable behavior rather than private implementation details.

A good backend test should simulate publishing a runtime event and then query the trace endpoint to confirm the typed event is persisted and returned.

A good backend test should simulate direct typed event publishing and confirm that it is also persisted.

A good backend test should verify sequence numbers are monotonic per session.

A good backend test should verify after_seq only returns events after the requested sequence.

A good backend test should verify trace events are scoped to the requested session.

A good backend test should verify child session metadata is preserved in parent-visible trace events.

A good backend test should verify session deletion removes associated typed trace events.

A good backend test should verify JSONL fallback remains available for old sessions if no DB trace exists.

Frontend tests should treat the backend trace API as the source of session event history.

Frontend tests should mock REST trace responses with typed WebSocket event objects.

Frontend tests should verify Chat renders the same plan-ready event from REST-loaded trace as from live WebSocket.

Frontend tests should verify reconnect catch-up does not duplicate already rendered events.

Frontend tests should verify Review dashboard can read changed-file and verification signals from backend-owned data.

Frontend tests should verify Trace renders persisted typed events after refresh.

Existing e2e tests for Chat plan approval should be updated to rely on Chat, not a separate Plan page.

Existing e2e tests for Review should continue to verify pending change decisions, but should also verify the broader quality/readiness dashboard.

Existing e2e tests for Trace are prior art for rendering event timelines from /trace/events.

Existing backend tests around runtime controller, session lifecycle, and tool result contracts are prior art for behavior-level service tests.

Tests should avoid asserting private storage implementation details unless testing the storage adapter directly.

Storage adapter tests may assert schema-level behavior such as insert/list/delete trace events.

WebSocket tests should not require a real browser if the event bus and trace endpoint seams cover persistence and replay behavior.

Out of Scope
Replacing SQLite as the default storage backend in the first pass.

Making Redis mandatory for local development.

Fully implementing Postgres or MySQL storage adapters in the first pass.

Removing raw JSONL EventLog.

Rewriting the entire frontend timeline into a backend-composed /timeline endpoint in the first pass.

Rebuilding the Review page into a full static-analysis/code-review engine.

Changing the semantics of tool approvals.

Changing the semantics of plan approval.

Changing how the agent runtime creates raw events.

Changing how session messages are persisted.

Building a production-grade Redis pub/sub cluster.

Defining long-term retention, archival, or redaction policy beyond the minimal schema needed for typed trace persistence.

Further Notes
The current codebase already points in this direction: the backend creates runtime events, translates them to typed WebSocket messages, and exposes a trace endpoint. The architectural gap is that the frontend replay path is based on reconstructing typed events from raw JSONL logs, while live delivery uses typed WebSocket messages.

The immediate goal should be to make the typed event stream durable and queryable from the backend. Once this is stable, the frontend can become simpler: load backend-owned trace, append live events, catch up by sequence on reconnect, and render.

Redis is a good fit for short-term memory and hot stream behavior, but it should complement, not replace, durable trace storage. For the current repo, SQLite is the lowest-risk first durable store. For a future Docker-based production profile, Redis plus Postgres is likely the cleanest pairing.