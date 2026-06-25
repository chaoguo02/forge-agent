# Context Lifecycle Architecture

## 1. Why this document exists

This document defines the target architecture for context management in forge-agent.
It is not a narrow fix for one `Token budget exceeded` incident. The goal is to make
context a first-class runtime subsystem with explicit lifecycle, budgets,
observability, and persistence boundaries.

The triggering symptom was a long chat session where a later, simple task failed
because prior task history and tool outputs were replayed into the next task. That
symptom points to a deeper architectural issue: the system currently treats
session history, task working context, long-term memory, repo structure, and tool
outputs as variations of one message stream.

The target design is based on a simple rule:

> Preserve high fidelity inside the current task; preserve distilled state across
task boundaries; keep raw large artifacts outside the prompt unless explicitly
recalled.

## 2. External research and design evidence

The design is intentionally aligned with patterns used by mature coding-agent and
agent-memory systems.

### 2.1 Claude Code: task boundaries, compaction, and subagents

Claude Code's public guidance emphasizes that context quality degrades before the
hard context limit is reached. The recommended user workflow is:

- use `/clear` for unrelated new tasks;
- use `/compact` proactively for long related tasks;
- steer compaction with an explicit focus;
- use subagents when the parent only needs the conclusion, not all intermediate
  tool output.

Design implication for forge-agent:

- task boundaries should be represented in code, not left as a manual user habit;
- compaction should happen before context rot, not only after prompt construction
  fails;
- noisy exploration should be isolated and summarized before it reaches the main
  chat history.

Sources:

- Claude session management: https://claude.com/blog/using-claude-code-session-management-and-1m-context
- Claude subagents: https://claude.com/blog/subagents-in-claude-code
- Claude steering with skills/hooks/subagents: https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more

### 2.2 Aider: structural context and dynamic repo-map budgets

Aider's repository map avoids dumping full files into context. It extracts symbols
and references, ranks them, and fits the rendered map into a token budget. The map
budget changes depending on whether concrete files are already in context.

Design implication for forge-agent:

- repo context should prefer structural summaries over raw text;
- context allocation should be dynamic: if exact files are loaded, repo-map budget
  should shrink; if no files are loaded, repo-map budget can grow;
- file/symbol anchors are important because they allow later retrieval without
  keeping full prior outputs in prompt.

Sources:

- Aider ctags/repo-map docs: https://aider.chat/docs/ctags.html
- Aider repo-map implementation: https://github.com/Aider-AI/aider/blob/main/aider/repomap.py
- Aider FAQ: https://aider.chat/docs/faq.html

### 2.3 Mem0-style memory routing: metadata, hybrid retrieval, recency

Mem0's context-engineering material treats memory as a routed data layer rather
than an append-only transcript. Important ideas are hybrid retrieval, metadata
filters, memory type, project/user scoping, and recency-aware ranking.

Design implication for forge-agent:

- long-term memory should not be injected wholesale;
- session summaries should carry metadata such as task id, changed files,
  commands, and anchors;
- retrieval should combine exact anchors, keyword matching, semantic search, and
  recency rather than relying on semantic similarity alone.

Sources:

- Mem0 context routing: https://mem0.ai/blog/context-engineering-for-ai-agents-how-to-route-queries-to-memory
- Mem0 memory decay / recency ranking: https://mem0.ai/blog/memory-decay-for-long-running-agents-how-recency-aware-ranking-fixes-retrieval-staleness
- Mem0 context queries: https://mem0.ai/blog/how-to-build-context-queries-for-ai-agents-with-mem0

### 2.4 Artifact-oriented context systems

Zep, Vectara memory patterns, Context Diamond, LLMFS, and similar systems share a
pattern: raw interaction logs and large outputs are retained outside the prompt;
the prompt receives summaries, references, and relevant retrieved facts.

Design implication for forge-agent:

- large tool outputs should become artifacts with summaries and stable ids;
- compaction should be auditable and recoverable, not destructive truncation;
- context assembly should produce a trace explaining what was included, omitted,
  summarized, or recalled.

Sources:

- Zep Python client: https://github.com/getzep/zep-python
- Vectara agent memory docs: https://docs.vectara.com/docs/agents/memory
- Context Diamond: https://github.com/RainCherb/context-diamond
- LLMFS: https://pypi.org/project/llmfs/0.1.0/

## 3. Current project diagnosis

The project already has meaningful foundations:

- `context/history.py` maintains a bounded `ConversationHistory` with native
  tool-call pairing.
- `context/token_budget.py` computes dynamic allocations and trims history by
  priority.
- `context/compaction.py` supports LLM-based summaries, regex fallback,
  incremental compaction, and persisted `session_summary.md`.
- `agent/core.py` builds layered messages with system prompt, long-term memory,
  short-term history, and task anchor.
- `entry/chat.py` persists `_shared_history` across chat rounds and exposes
  `/compact` and `/clear`.
- `docs/memory-architecture-plan.md` defines the long-term memory taxonomy.

The key architectural gaps are:

1. Prompt-local compaction does not rewrite session state. `_build_messages()` may
   compact `history_dicts`, but `_shared_history` remains large.
2. Chat rounds are not represented as task lifecycle objects. They are just new
   user messages appended to the same history.
3. `agent.budget_tokens` is used both as context-planning input and spend guard.
4. Tool outputs are stored in history as raw messages until later trimming. Large
   outputs therefore pollute the source history even if a later prompt trims them.
5. There is no context trace. When a budget error happens, the user cannot see
   which layer consumed tokens or why compaction did or did not trigger.
6. Long-term memory, session summary, current task state, and raw artifacts are
   not routed through a single context policy.

## 4. Target model: context as a lifecycle

The runtime should distinguish six layers.

```text
L0 System Core
  Stable instructions, tool schemas, safety/policy, cacheable prompt prefix.

L1 Project Structure
  Repo map, project rules, skills metadata, code index summaries.

L2 Long-Term Memory
  Persistent semantic/procedural/episodic memory retrieved by anchors,
  keywords, recency, and semantic similarity.

L3 Session State
  Distilled summaries of completed tasks in the current chat session.
  This survives across rounds but not as raw tool output.

L4 Current Task Working Context
  High-fidelity recent messages, current task plan, recent observations,
  active file anchors, unresolved errors.

L5 Artifacts
  Raw large tool outputs, test logs, file snapshots, search results, and
  generated traces stored outside prompt with stable ids and summaries.
```

This replaces the current implicit model:

```text
system + memory + shared_history + task_anchor
```

with an explicit assembly pipeline:

```text
Task input
  -> classify task relationship
  -> retrieve relevant memories/session summaries/artifacts
  -> allocate budgets per layer
  -> assemble request context
  -> execute task with working context
  -> persist artifacts and task summary
  -> update session state and memory candidates
```

## 5. Core principles

### 5.1 Task-internal fidelity, task-external distillation

Inside a task, the agent needs enough detail to reason, recover from mistakes, and
finish the work. Across task boundaries, the next task rarely needs every command
line and file chunk. It needs outcomes, changed files, decisions, unresolved work,
and pointers to raw artifacts.

### 5.2 Raw output should be durable but not prompt-resident

A large command output or file read may be important for auditability. That does
not mean it belongs in every future LLM request. Store it as an artifact and put a
small summary in context.

### 5.3 Budgets must describe different failure modes

A context-window budget protects a single request. A task-spend budget protects
cost. A session-retention budget protects chat continuity. A memory-injection
budget protects relevance. Combining these into one number hides the root cause of
failures.

### 5.4 Retrieval beats replay

The system should prefer finding the few relevant past facts over replaying all
past interactions. Exact file/symbol anchors should outrank fuzzy semantic search
when code paths are known.

### 5.5 Every omission should be explainable

Context management is part of correctness. The runtime should record why content
was included, compacted, summarized, artifacted, or omitted.

## 6. Proposed components

### 6.1 `ContextManager`

New module: `context/manager.py`.

Responsibilities:

- own context assembly for each LLM request;
- ask `TokenBudget` for a layer budget plan;
- retrieve long-term memory and session state;
- decide which current-task messages remain high fidelity;
- request artifact summaries instead of raw outputs when appropriate;
- emit `ContextTrace` for observability.

The agent should call `ContextManager.build_request()` instead of embedding all
context policy inside `agent/core.py::_build_messages()`.

### 6.2 `SessionState`

New module: `context/session.py`.

A chat session should store structured state instead of only `_shared_history`:

```python
@dataclass
class SessionState:
    session_id: str
    round_count: int
    active_task: TaskContext | None
    completed_tasks: list[TaskSummary]
    rolling_summary: str
    artifacts: list[ArtifactRef]
    compaction_count: int
    last_compaction_reason: str | None
```

`entry/chat.py` should treat each user round as a task boundary. The system can
still support related-task continuation, but continuation becomes an explicit
routing decision rather than accidental history retention.

### 6.3 `TaskContext`

New module or dataclass in `context/session.py`.

```python
@dataclass
class TaskContext:
    task_id: str
    user_goal: str
    intent: str
    relationship_to_previous: Literal[
        "same_task", "related_task", "unrelated_task", "quick_question"
    ]
    started_at: str
    active_files: set[str]
    recent_messages: list[LLMMessage]
    decisions: list[str]
    unresolved: list[str]
```

This object is the high-fidelity working context. It can contain recent tool
results during the task, but at task end it is distilled into `TaskSummary`.

### 6.4 `TaskSummary`

Task summaries are not chat messages. They are structured session records:

```python
@dataclass
class TaskSummary:
    task_id: str
    user_goal: str
    outcome: str
    changed_files: list[str]
    read_files: list[str]
    commands: list[str]
    tests: list[str]
    decisions: list[str]
    unresolved: list[str]
    artifact_refs: list[str]
    memory_candidates: list[str]
    token_stats: ContextStats
```

The rolling session summary should be built from these summaries, not from raw
message history.

### 6.5 `ArtifactStore`

New module: `context/artifacts.py`.

Responsibilities:

- store raw large outputs under `logs/<task_id>/artifacts/`;
- assign stable artifact ids;
- compute compact summaries;
- expose references such as `artifact://<task_id>/<artifact_id>`;
- allow future retrieval by id, file anchor, command, or keyword.

Artifact examples:

- long shell output;
- pytest failure logs;
- file read chunks above a threshold;
- search result pages;
- generated repo maps or context traces.

History should contain:

```text
[Tool artifact]
Tool: shell
Status: failed
Summary: pytest failed in test_context_session_compaction.py with AssertionError...
Artifact: artifact://task_123/step_04_shell_output
```

not the entire raw output.

### 6.6 `ContextTrace`

New module: `context/stats.py` or part of `context/manager.py`.

```python
@dataclass
class ContextStats:
    request_budget_tokens: int
    estimated_total_tokens: int
    system_tokens: int
    project_tokens: int
    memory_tokens: int
    session_tokens: int
    task_tokens: int
    repo_map_tokens: int
    artifact_summary_tokens: int
    omitted_tokens: int

@dataclass
class ContextTrace:
    task_id: str
    step: int
    stats: ContextStats
    included: list[str]
    omitted: list[str]
    compactions: list[str]
    artifacts_created: list[str]
    retrievals: list[str]
```

`/stats` should show a concise summary. Verbose logs should include the full
trace.

## 7. Budget model

Replace the single overloaded meaning of `agent.budget_tokens` with separate
budgets.

Suggested config shape:

```yaml
context:
  request_budget_tokens: 70000
  system_budget_tokens: 12000
  repo_map_budget: 8000
  memory_budget_tokens: 6000
  session_budget_tokens: 12000
  task_working_budget_tokens: 30000
  artifact_summary_budget_tokens: 4000

  session_compact_tokens: 30000
  auto_compact_after_round: true
  compact_every_rounds: 3
  keep_recent_task_messages: 8
  artifact_threshold_tokens: 2000

agent:
  budget_tokens: 80000
```

Definitions:

- `context.request_budget_tokens`: target maximum input context for one LLM call.
- `agent.budget_tokens`: maximum billable task spend before stopping.
- `context.session_compact_tokens`: maximum retained session state before rolling
  summary compaction.
- `context.artifact_threshold_tokens`: output size above which raw content is
  moved to artifact storage.

Important distinction:

- cached prompt tokens still occupy context-window capacity;
- cache-read tokens may be excluded from task spend accounting;
- therefore context fitting must use total request tokens, while cost guard may
  use billable tokens.

## 8. Context assembly policy

Each LLM request should be assembled in this order:

1. System core and tool schemas.
2. Project rules, skills metadata, and repo map.
3. Retrieved long-term memory, ranked by anchors, keywords, recency, and semantic
   relevance.
4. Session summary relevant to the current task relationship.
5. Current task working messages.
6. Artifact summaries for artifacts referenced by the current task.
7. Task anchor.

When the request exceeds budget, trim in this order:

1. low-relevance repo-map entries;
2. low-score long-term memories;
3. older session summaries unrelated to current files;
4. old tool-result summaries;
5. older current-task messages, while preserving native tool-call pairs;
6. finally, ask for a compaction pass before making the next request.

The task anchor should be small and always preserved.

## 9. Task relationship routing

At the beginning of each chat round, classify the new input:

```text
same_task        Continue current task with high-fidelity working context.
related_task     Include previous task summary and shared file anchors.
unrelated_task   Include rolling session summary only if generally relevant.
quick_question   Avoid polluting session history; store only a small Q/A summary.
```

Initial implementation can use heuristics:

- overlapping file paths or symbols;
- pronouns like "继续", "刚才", "这个";
- explicit topic shift words;
- command-like quick questions.

Later implementation can use a small LLM classifier with strict JSON output.

The conservative default should be `related_task`, not `unrelated_task`, because
losing useful context is more harmful than carrying a small summary. But the
system should not preserve raw prior tool output unless classified as `same_task`.

## 10. Compaction pipeline

Compaction should become an explicit pipeline with different triggers.

### 10.1 Request-time compaction

Current behavior belongs here: if a single request is too large, compact the
current working messages before the call.

### 10.2 Task-end compaction

At the end of every chat round:

1. extract `TaskSummary` from EventLog and current task context;
2. move large raw outputs to artifacts;
3. update rolling session summary;
4. clear high-fidelity current-task messages unless the next round is a
   same-task continuation;
5. persist session summary to disk.

### 10.3 Session-threshold compaction

When session summaries exceed `session_compact_tokens`, merge older task summaries
into a rolling summary while preserving:

- changed files;
- commands/tests;
- decisions and rationale;
- unresolved work;
- user corrections;
- artifact references.

### 10.4 Memory extraction

Compaction should produce memory candidates, but not blindly write everything to
long-term memory. Candidates should be classified:

- user preference or correction -> procedural memory;
- stable project fact -> semantic memory;
- specific task episode -> episodic memory, possibly with TTL;
- temporary debugging noise -> no long-term memory.

This complements `docs/memory-architecture-plan.md` instead of replacing it.

## 11. Artifact policy

A tool result should become an artifact when any of these are true:

- estimated output tokens exceed `artifact_threshold_tokens`;
- output is a test/build log;
- output is a file read above a configured line/token threshold;
- output is a web/search result with many entries;
- output is likely useful for audit but not needed verbatim in prompt.

Artifact summaries should preserve operational details:

- exact file paths;
- command strings;
- failing test names;
- error class and first stack frame;
- line numbers;
- exit code/status;
- artifact id.

Do not summarize away identifiers that are hard to reconstruct.

## 12. Observability

The user and developer should be able to answer:

- how many tokens are in shared/session state;
- how many tokens were allocated to each context layer;
- whether compaction triggered, and why;
- what was omitted or artifacted;
- how much was billable vs cache-read;
- which memories were retrieved and why.

Minimal UI:

```text
Context: total 46k/70k · system 11k · repo 7k · memory 2k · session 4k · task 20k · artifacts 2k · compact no
```

`/stats` should include:

- rounds;
- total task spend tokens;
- shared/session estimated tokens;
- compaction count;
- artifact count and total bytes;
- last compaction reason;
- last context trace path.

## 13. Migration plan

### Phase 1: Measurement before mutation

Deliverables:

- `ContextStats` and `ContextTrace`;
- `/stats` context breakdown;
- budget error messages with layer breakdown.

Reasoning:

Before changing retention behavior, make the current failure mode visible. This
reduces the risk of silently losing context.

### Phase 2: Budget separation

Deliverables:

- config fields for request/session/memory/artifact budgets;
- `TokenBudget` renamed or documented as request-context budget;
- `agent.budget_tokens` used only as task spend guard.

Reasoning:

This removes the semantic ambiguity that caused context replay to look like task
execution cost.

### Phase 3: Session and task lifecycle model

Deliverables:

- `SessionState`, `TaskContext`, `TaskSummary`;
- `entry/chat.py` updated to create/finalize tasks at round boundaries;
- high-fidelity current-task context separated from completed-task summaries.

Reasoning:

This is the architectural center. Without it, compaction remains a local prompt
hack.

### Phase 4: Artifact store

Deliverables:

- `ArtifactStore`;
- tool-result artifacting for large outputs;
- summaries in history/session state;
- artifact references in EventLog.

Reasoning:

This prevents large outputs from entering long-lived prompt state while preserving
auditability.

### Phase 5: ContextManager extraction

Deliverables:

- move request assembly out of `agent/core.py::_build_messages()`;
- centralize retrieval, budget allocation, trimming, compaction, and tracing;
- keep `agent/core.py` focused on agent loop control.

Reasoning:

Context policy is becoming large enough to deserve its own subsystem.

### Phase 6: Compaction and memory integration

Deliverables:

- task-end compaction;
- rolling session summary;
- structured memory candidates;
- memory writes gated by type, confidence, and user/project policy.

Reasoning:

Compaction should feed durable knowledge only when the information is likely to
remain useful.

### Phase 7: Task relationship routing

Deliverables:

- heuristic classifier;
- later LLM JSON classifier;
- quick-question mode that avoids polluting task history;
- related/unrelated context retrieval policies.

Reasoning:

Routing is valuable but should come after the system can safely preserve and
retrieve summaries.

## 14. Acceptance criteria

Functional criteria:

- Running three unrelated chat tasks does not replay full prior tool output into
  the third task.
- Running a related follow-up still has access to changed files, decisions,
  unresolved work, and relevant artifact references.
- Large tool outputs are recoverable from artifacts but do not remain raw in
  session prompt state.
- Budget exceeded errors include a context breakdown and task spend breakdown.
- `/compact` and automatic compaction both update session state consistently.

Regression criteria:

- Native tool-call/tool-result pairing remains valid after trimming.
- Prompt caching is not destroyed by unnecessary changes to stable system layers.
- Single-run non-chat mode still works without requiring session state.
- Existing memory files remain backward compatible.

Quality criteria:

- ContextTrace can explain every major inclusion/omission decision.
- Summary prompts preserve file paths, commands, failures, decisions, and
  unresolved work.
- Tests cover at least: unrelated rounds, related rounds, large artifacts,
  compaction persistence, and budget separation.

## 15. Risks and reflections

### Risk: over-aggressive summarization loses crucial details

Mitigation:

- preserve raw artifacts;
- keep exact identifiers in summaries;
- classify same-task continuation conservatively;
- expose artifact recall tools.

### Risk: artifact references become unusable model-only strings

Mitigation:

- store artifacts under deterministic paths;
- include artifact ids in EventLog;
- provide an artifact read/search tool or command;
- keep summaries useful even without immediate artifact retrieval.

### Risk: context manager becomes a monolith

Mitigation:

- keep retrieval, budget, compaction, artifacting, and tracing as separate
  modules with clear interfaces;
- make `ContextManager` an orchestrator, not a storage backend.

### Risk: task relationship classifier makes harmful mistakes

Mitigation:

- start with conservative heuristics;
- default to related summaries rather than raw history;
- never auto-clear irreversible state;
- log classifier decisions in ContextTrace.

### Risk: long-term memory fills with low-value summaries

Mitigation:

- treat compaction output as candidates, not automatic memory;
- require metadata, anchors, confidence, and type;
- apply TTL/decay to episodic memories;
- mark memories stale when anchored files change.

## 16. Non-goals

- Do not solve context issues by merely increasing token limits.
- Do not keep all prior tool output in chat history for convenience.
- Do not write every task summary into permanent memory.
- Do not make semantic vector search the only retrieval mechanism.
- Do not hide trimming/compaction decisions from users and logs.

## 17. Open questions

1. Should task relationship routing run before or after proactive memory retrieval?
2. Should artifact storage be part of EventLog or a separate context subsystem with
   EventLog references?
3. What is the right default TTL for episodic task summaries?
4. Should `/clear` clear only current working context, or also rolling session
   summary?
5. How much of ContextTrace should be shown by default versus only in verbose
   mode?
6. Should compaction use the main model, a cheaper model, or a deterministic
   extractor first with LLM refinement second?

## 18. Recommended first implementation slice

Although the target architecture is broad, implementation should be staged. The
first slice should not be a narrow bugfix; it should lay the foundation for the
new architecture:

1. add `ContextStats` and budget-separated config fields;
2. add `SessionState`, `TaskContext`, and `TaskSummary` structures;
3. update chat round lifecycle to finalize tasks into summaries;
4. add context breakdown to `/stats` and budget errors;
5. only then replace raw shared-history retention with task summaries.

This slice is intentionally larger than a local compaction patch because it
establishes the concepts that later artifact storage, memory routing, and task
relationship classification will depend on.
