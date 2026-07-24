Spec: Session-Aware Active Memory Recall System
Problem Statement
Grace Code 当前已经具备基础的 Memory 能力：运行结束后可以通过 RunFinalizer 做记忆提取与存储，页面上也有 Memory inventory、CRUD、详情查看和搜索能力。

但从用户视角看，Memory 目前仍偏“被动资料库”：

Agent 运行时没有稳定、可解释的 active recall 闭环。
运行前/运行中，相关 memory 不一定会被主动检索并注入上下文。
Memory 页面只能看“有哪些 memory”，但看不到当前 session 到底召回了哪些 memory、为什么召回、是否注入、是否被使用。
多 session 场景下，MemoryContext 内部存在 session/run mutable state，可能导致 session 间上下文污染。
RunFinalizer 虽然能提取 memory，但提取出的 memory 与 session、turn、source、recall 行为之间的关联不够清晰。
用户无法在页面上调校当前 session 的 memory 行为，例如 pin、disable、preview recall、查看本 session 生成的 memories。
这导致 Grace Code 的 Memory 系统相比 Claude Code 的 proactive memory extraction / active recall 能力更基础，无法充分支撑长期、多轮、多 session 的项目协作。

Solution
将 Memory 模块升级为 session-aware active recall system。

从用户视角，目标是：

Agent 在每轮运行前主动检索与当前任务相关的 memories。
Agent 注入 memory 时有清晰、可记录、可解释的 recall 结果。
多 session 同时运行或快速切换时，Memory recall 不会串线。
Memory 页面不仅是 inventory，还能展示当前 session 的 memory recall 状态。
用户可以看到某条 memory 为什么被召回、是否注入、是否被使用。
用户可以针对当前 session pin 或 disable 某些 memories。
RunFinalizer 写入的新 memories 能关联到来源 session，并在页面中展示。
Memory 系统在 embedding/RAG 不可用时仍有 deterministic scoped recall fallback。
最终闭环：


User prompt / session context
→ session-aware recall query
→ always inject + semantic recall + scoped deterministic recall
→ injection text + recall records
→ agent run
→ memory access/write events
→ RunFinalizer extracts new memories
→ Memory page shows inventory + recalls + generated memories
→ user tunes memory behavior
→ next turn uses updated recall state
User Stories
As a Grace Code user, I want the agent to remember relevant project decisions automatically, so that I do not need to repeat context across sessions.

As a Grace Code user, I want memory recall to be scoped to the active session, so that another session cannot pollute the current run.

As a Grace Code user, I want the agent to proactively recall relevant memories before responding, so that answers use prior project knowledge.

As a Grace Code user, I want to see which memories were injected into the current run, so that I can understand why the agent behaved a certain way.

As a Grace Code user, I want to see why a memory was recalled, so that I can judge whether the recall was appropriate.

As a Grace Code user, I want to see memory recall scores, so that I can distinguish strong matches from weak matches.

As a Grace Code user, I want to see whether a memory came from always-inject, semantic search, scoped recall, or manual pinning, so that I understand the source of context.

As a Grace Code user, I want to disable a memory for the current session, so that irrelevant or stale context stops influencing the agent.

As a Grace Code user, I want to pin a memory to the current session, so that important context is consistently injected.

As a Grace Code user, I want disabled memories to remain visible but marked, so that I can re-enable them later.

As a Grace Code user, I want pinned memories to be visibly distinct, so that I know which context is intentionally forced.

As a Grace Code user, I want to preview what memories would be recalled for a query, so that I can debug memory behavior before running the agent.

As a Grace Code user, I want the Memory page to show memories generated from the current session, so that I can review what the agent learned.

As a Grace Code user, I want newly extracted memories to include source session information, so that I can trace where knowledge came from.

As a Grace Code user, I want generated memories to include anchors where possible, so that I can validate whether the memory is still relevant.

As a Grace Code user, I want stale memory anchors to be detected, so that outdated knowledge is not silently injected.

As a Grace Code user, I want memory confidence to influence recall, so that low-confidence memories do not dominate context.

As a Grace Code user, I want deprecated memories excluded from normal recall, so that old decisions do not keep affecting runs.

As a Grace Code user, I want global/user preferences to be injected consistently, so that my working preferences are always respected.

As a Grace Code user, I want project-specific memories to be recalled only when relevant, so that context stays focused.

As a Grace Code user, I want reference memories to be discoverable on demand, so that external resources can be used without bloating every prompt.

As a Grace Code user, I want session-specific memories to remain tied to the session unless promoted, so that temporary context does not leak globally.

As a Grace Code user, I want memory recall to work even without embeddings installed, so that the system remains useful in minimal environments.

As a Grace Code user, I want semantic recall when embeddings are available, so that relevant memories can be found even when wording differs.

As a Grace Code user, I want deterministic scoped recall as a fallback, so that known project memories are still surfaced without vector search.

As a Grace Code user, I want active recall to consider the current task, prompt, mode, session title, recent tools, and active files, so that memory retrieval is context-aware.

As a Grace Code user, I want memory recall to avoid repeating the same memory excessively within one session, so that prompt space is not wasted.

As a Grace Code user, I want recall de-duplication to be session-scoped, so that one session does not suppress recall in another session.

As a Grace Code user, I want memory edits from the Memory page to affect future turns, so that UI changes are not disconnected from runtime behavior.

As a Grace Code user, I want memory delete/deprecate actions to invalidate runtime memory cache, so that stale memory is not reused.

As a Grace Code user, I want the agent to record memory access, so that frequently useful memories become more visible.

As a Grace Code user, I want memory recall logs to survive page refresh, so that I can inspect what happened after a run.

As a Grace Code user, I want memory recall logs to be associated with session IDs, so that I can audit multi-session behavior.

As a Grace Code user, I want the Event/Trace UI to optionally show memory recall and memory write events, so that memory activity is part of the execution story.

As a Grace Code user, I want the Memory page to show active session context, so that inventory is grounded in the current work.

As a Grace Code user, I want memory-generated records to appear after a run finishes, so that I can accept, edit, or deprecate them.

As a Grace Code user, I want memory extraction to avoid saving facts already present in code, so that memory does not duplicate the repository.

As a Grace Code user, I want memory extraction to avoid saving temporary plans, so that long-term memory remains durable and useful.

As a Grace Code user, I want memory extraction to save important user preferences, so that personal workflow guidance persists.

As a Grace Code user, I want memory extraction to save recurring defect patterns, so that future work benefits from prior debugging.

As a Grace Code user, I want memory extraction to save verified architectural decisions, so that future sessions do not re-litigate them.

As a Grace Code user, I want memory extraction to include confidence and source reason, so that I can decide whether to trust it.

As a Grace Code user, I want memory recall to respect token budgets, so that active recall does not crowd out task context.

As a Grace Code user, I want omitted memories to be visible with an omitted reason, so that I know what was considered but not injected.

As a Grace Code user, I want memory recall behavior to be testable, so that future changes do not reintroduce context contamination.

As a Grace Code developer, I want active recall state to be session/run scoped, so that concurrent sessions are safe.

As a Grace Code developer, I want MemoryContext to avoid global mutable recall state, so that recall behavior is predictable.

As a Grace Code developer, I want a dedicated recall service, so that storage, retrieval, injection, and logging responsibilities are separated.

As a Grace Code developer, I want a structured recall result, so that both prompt injection and UI display use the same source of truth.

As a Grace Code developer, I want recall records persisted or queryable, so that MemoryView can display runtime behavior.

As a Grace Code developer, I want API endpoints for session recall, so that the frontend does not infer memory behavior from inventory alone.

As a Grace Code developer, I want memory session overrides, so that UI pin/disable actions have backend semantics.

As a Grace Code developer, I want memory write events, so that frontend can refresh after RunFinalizer creates memories.

As a Grace Code developer, I want tests for two sessions recalling different memories, so that cross-session contamination is caught.

As a Grace Code developer, I want tests for active recall injection, so that retriever integration cannot silently regress.

As a Grace Code developer, I want tests for Memory page recall APIs, so that UI has stable contracts.

As a Grace Code developer, I want tests for generated memories from a session, so that source attribution is preserved.

As a Grace Code developer, I want tests for deprecated memory exclusion, so that stale memories do not affect runs.

As a Grace Code developer, I want tests for pin/disable overrides, so that user tuning is reliable.

As a Grace Code developer, I want active recall to degrade gracefully when semantic search is unavailable, so that core memory still works.

Implementation Decisions
Introduce a dedicated Memory Recall Service responsible for building session-aware recall results.

Keep Memory Store responsible for CRUD, list, read, write, stats, and persistence.

Keep External Memory Store responsible for embedding-backed semantic search.

Keep RunFinalizer responsible for post-run extraction, but enrich extracted memories with stronger source attribution.

Reduce MemoryContext to a thinner injection-facing wrapper. It should assemble memory injection text from recall results rather than owning cross-session mutable recall state.

Move mutable recall state out of shared MemoryContext fields and into run/session scoped data structures.

Treat active recall as a structured operation, not just formatted text generation.

Recall input should be modeled as a structured query containing:

session ID
task description
current user message
agent mode/name
repo path
session title
active or recently accessed files
recent tools
optional turn/run ID
Recall output should include both injection text and structured recall records.

Recall records should include:

memory name
source
score
reason
confidence
scope
injected flag
omitted reason when applicable
timestamp
session ID
optional turn/run ID
Active recall should combine multiple strategies:

always-inject user and feedback memories
semantic recall via the external memory store when available
deterministic scoped recall based on project/global scope, confidence, recency, anchors, and source session
manual session pin overrides
session disable overrides
Always-inject memories should remain short and high-priority.

Semantic recall should be budgeted and should not exceed a configured memory token budget.

Deterministic scoped recall should act as fallback when embeddings are unavailable.

Recall de-duplication must be scoped per session, not global.

A memory surfaced in one session must not prevent another session from recalling it.

Memory cache invalidation should occur after memory create, update, delete, deprecate, pin, or disable actions.

Memory page edits must affect subsequent agent turns.

Add session-level memory override support:

pin
unpin
disable
enable
Session overrides should not mutate the global memory record itself.

Add a recall log source of truth. This may start as session metadata but should be designed so it can migrate to a dedicated table.

Preferred persistent model:


memory_recalls (
  id,
  session_id,
  turn_id,
  memory_name,
  source,
  score,
  reason,
  injected,
  omitted_reason,
  created_at
)

memory_session_overrides (
  session_id,
  memory_name,
  action,
  created_at
)
Add APIs for session memory recall inspection.

Add an API to preview recall for a query without running the agent.

Add an API to list memories generated by the current session.

Add an API to set session memory overrides.

MemoryView should evolve from inventory-only into an inspection and tuning surface.

MemoryView should add a Current Session Recall area.

MemoryView should show:

injected memories
retrieved but omitted memories
recall reasons
recall source
scores
last recall timestamp
pin/disable controls
MemoryView should add a Generated From This Session area.

Generated memories should show:

source session
source run/turn if available
extraction source
confidence
anchors
created timestamp
Add WebSocket events for memory activity if the event stream remains the primary UI update channel.

Candidate WebSocket events:

memory_recall
memory_written
Memory recall events should summarize counts, not dump large memory contents.

Memory written events should include memory name, description, source, and confidence.

RunFinalizer should write source session metadata when creating memories.

RunFinalizer should avoid saving:

facts already present in code
temporary plans
one-off execution details
vague summaries
low-confidence assumptions
RunFinalizer should prefer saving:

user preferences
durable project constraints
repeated defect patterns
verified architectural decisions
non-obvious context future sessions need
The memory extraction prompt should become stricter and more preservation-oriented.

Memory extraction should support consolidation with existing memories rather than uncontrolled growth.

Memory recall should update access counts only for memories actually injected or read, not all candidates considered.

Memory recall should never fail the agent run. Recall failures should degrade to no injected recall and be logged.

Memory recall should avoid adding large memory bodies to UI responses unless explicitly requested.

Existing memory CRUD APIs should remain compatible.

Existing memory search API should remain available as manual semantic search.

Existing Memory inventory should remain the base view.

Testing Decisions
The highest-value seam is the session-level memory recall service. Tests should call the service with structured recall queries and assert structured recall results.

A good test should validate external behavior:

which memories are recalled
which memories are injected
which memories are omitted
whether session overrides apply
whether sessions are isolated
whether records are available through API
Tests should avoid asserting private ranking implementation details unless they are part of the documented recall contract.

Add backend unit tests for active recall with:

user/feedback always-inject
project scoped recall
semantic recall available
semantic recall unavailable
deprecated memories excluded
low-confidence memories omitted
token budget enforcement
pin override
disable override
Add multi-session tests:

Session A and Session B use different user messages.
Session A recall state does not affect Session B recall.
Session A surfaced memory does not suppress Session B injection.
Session B override does not affect Session A.
Add cache invalidation tests:

update memory
delete memory
deprecate memory
pin memory
disable memory
Add API tests for:

session recall list
recall preview
generated memories for session
session override mutation
Add RunFinalizer tests:

extracted memory includes source session ID
extracted memory includes anchors where available
extraction skips already-code-backed facts when possible
extraction skips temporary plans
extraction consolidates duplicate memories
Add WebSocket/event tests if memory_recall and memory_written events are introduced.

Add frontend tests at the highest available seam:

Memory page loads recall records for active session
recalled memories render score/reason/source
pin/disable controls call the override API
generated-from-session section renders new memories
Existing prior art:

Event translation and WebSocket contract tests already exist around core loop events.
Session/API smoke tests already validate endpoint behavior.
Memory CRUD API and MemoryView provide the current UI/API seam to extend.
Build validation should include:

frontend TypeScript build
focused backend memory/session tests
existing core loop tests
Out of Scope
Replacing the entire Memory storage layer.

Replacing the existing Memory page inventory and CRUD functionality.

Introducing a new frontend state management library.

Building a full vector database product.

Requiring embeddings for memory to function.

Full code generation from backend memory schema to frontend TypeScript types.

Rewriting RunFinalizer completely.

Making memory extraction block user responses.

Exposing full memory contents in every event stream payload.

Solving all memory quality problems in the first implementation pass.

Global cross-project memory governance beyond the existing type/scope model.

UI polish unrelated to recall visibility and tuning.

Further Notes
The recommended implementation order is:

Make MemoryContext and recall state session-safe.
Introduce MemoryRecallService.
Wire ProactiveRetriever into active recall injection.
Persist or expose recall records.
Add session recall APIs.
Extend MemoryView with Current Session Recall.
Add session pin/disable overrides.
Show memories generated from the current session.
Add stricter RunFinalizer extraction discipline.
Add memory_recall and memory_written events if needed for live UI.
The most important architectural constraint is avoiding cross-session contamination. Active recall makes memory more powerful, but also makes isolation bugs more dangerous.

The first implementation milestone should prove:


Session A and Session B can run with different prompts,
recall different memories,
record different recall results,
and never mutate or suppress each other's recall state.