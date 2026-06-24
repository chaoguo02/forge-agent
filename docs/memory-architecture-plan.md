# Memory Architecture Plan

## 1. Architecture Principles

### 1.1 Two-Layer Physical Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  SHORT-TERM (Session-Scoped)                                 │
│  ConversationHistory + Compaction + TokenBudget               │
│  ─────────────────────────────────────                        │
│  当前任务的完整对话上下文。                                     │
│  滑动窗口管理，超出窗口的由 compaction 压缩为摘要。              │
│  任务结束时清除。不需要 SQLite、不需要向量、不需要索引。          │
├──────────────────────────────────────────────────────────────┤
│  LONG-TERM (Persistent, Cross-Session)                       │
│  MemoryStore (文件) + ExternalMemoryStore (SQLite + fastembed) │
│  ─────────────────────────────────────                        │
│  三个记忆类型（同一个 store，不同检索策略）：                     │
│                                                                │
│  EPISODIC  │ SEMANTIC  │ PROCEDURAL                           │
│  发生了什么  │ 什么是真的  │ 怎么做                               │
│  时间检索    │ 语义检索    │ 场景精确匹配                          │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 What "Working Memory" Actually Is

"Working memory" in an LLM agent is **not a separate memory module**.
It is simply the entire message array the model can see at inference time:

```
[system prompt]       ← permanent rules
[long-term context]   ← injected once at task start
[conversation history] ← short-term memory (compaction-managed)
[task anchor]         ← per-step injection: what am I doing right now?
```

The per-step `task anchor + mode + policy` injection is **prompt engineering**,
not a memory subsystem. It exists to remind the model of its current task
after compaction may have trimmed the original task message from history.

### 1.3 Theoretical Basis for Memory Types

The three-type taxonomy (episodic / semantic / procedural) is grounded in:

| Source | Contribution |
|---|---|
| Tulving (1972) | Original episodic-semantic distinction in human cognition |
| Anderson ACT-R | Mathematical activation/decay model: A_i = B_i + Σ(W_j·S_ji) |
| CoALA (arXiv:2309.02427, 2023) | Formal Tulving → LLM agent mapping |
| "Memory in the Age of AI Agents" (2025, 47 authors incl. Google DeepMind, Stanford, Yale) | Definitive survey: factual/experiential/working functional categories |
| LangMem SDK (2025) | Direct implementation: EpisodicMemory, SemanticMemory, ProceduralMemory |
| MongoDB Agent Memory Guide (2025) | Industry reference: episodic, semantic, procedural, associative |

These are not three separate stores — they are **three retrieval strategies
on the same persistent storage layer**, distinguished by how they are
triggered and retrieved.

---

## 2. Memory Type Definitions

### 2.1 Episodic Memory

**Cognitive definition** (Tulving): Time-stamped personal experiences.
"What happened, when, in what context."

**In our coding agent**:
- Records of specific tool calls, their outcomes, and the surrounding context
- Example: "`pytest test_plan_mode.py::test_edit_scope_blocks_other_file_reads`
  failed with AssertionError at line 306 on 2025-06-23"
- Example: "Read `agent/core.py` lines 1140-1230 and identified that
  `_run_planning_phase` passes `policy` to `_run_execution_phase`"

**Storage**: Full content with timestamp, file anchors, and tool context in
MemoryStore + vector embedding in ExternalMemoryStore.

**Retrieval**: Primarily by file/symbol anchor + recency. Secondary by
semantic similarity. Retention follows ACT-R activation decay: frequently
accessed episodes have slower decay.

**Lifecycle**: 
- Formation: Auto-extracted from EventLog on task completion (Stage 2)
- Consolidation: Similar episodes merged into semantic knowledge (Stage 3)
- Decay: Ebbinghaus curve: R(t) = e^(-t/S), where S depends on importance
- Expiry: Episodes older than N days with zero accesses are pruned (Stage 5)

### 2.2 Semantic Memory

**Cognitive definition** (Tulving): Decontextualized facts and concepts.
"What is generally true, independent of when it was learned."

**In our coding agent**:
- Project knowledge: file responsibilities, module relationships, config values
- Example: "`agent/core.py` contains `ReActAgent` (the main loop) and
  `PlanExecuteAgent` (plan-then-execute orchestrator)"
- Example: "The project uses `config/default.yaml` loaded via
  `config/schema.py::load_config()`"

**Storage**: Compact fact statements with entity links (file paths, symbol
names). Vector embedding for semantic search. No strong time dependency.

**Retrieval**: Primarily semantic search (cosine similarity) with keyword
boosting. Injected at task start as part of long-term context.

**Lifecycle**:
- Formation: Auto-extracted from EventLog and user interactions. Also
  consolidated from episodic memories (Stage 3)
- Update: When contradictory evidence appears, semantic knowledge is updated
  rather than duplicated
- Decay: Slower than episodic. Access frequency prevents decay.
- Expiry: Only when explicitly contradicted or when linked files are deleted

### 2.3 Procedural Memory

**Cognitive definition** (Tulving extension, Anderson ACT-R): Skills,
routines, and behavioral patterns. "How to do things."

**In our coding agent**:
- User corrections extracted as precise behavioral rules
- Example: "When processing YAML config files, use `yaml.safe_load()` instead
  of regex-based parsing"
- Example: "When modifying the FINISH path in `agent/core.py`, you must
  also update `CompletionValidator.validate()` to match"
- Example: "Before modifying `agent/policy.py`, read `agent/policy_registry.py`
  first — they are tightly coupled"

**Storage**: Rule text with mandatory file/symbol anchors. High importance
flag. Does not expire unless explicitly invalidated.

**Retrieval**: NOT semantic search. Exact match on file/symbol anchors +
task type activation. When the agent reads `agent/core.py`, all procedural
memories anchored to that file are automatically injected.

**Lifecycle**:
- Formation: Extracted from user corrections and repeated patterns (Stage 2)
- Validation: When anchored file changes, rule is marked stale (Stage 5)
- Expiry: Only when user explicitly contradicts or file validation shows rule
  no longer applies

---

## 3. Retrieval Strategy Matrix

|  | Episodic | Semantic | Procedural |
|---|---|---|---|
| **Trigger** | File/symbol access | Task start | File/symbol access |
| **Method** | Anchor match + recency sort | Semantic search (cosine) | Anchor exact match |
| **Injection** | Optional (per-step if relevant) | At task start (long-term ctx) | Per-step when anchor matches |
| **Limit** | Top 3 by recency | Top 5 by similarity | All matches (expect few) |
| **Fallback** | Semantic search if no anchor match | Keyword search if cosine low | None |

---

## 4. Multi-Stage Implementation Plan

### Stage 1: Memory Type System + File Anchors

**Learn from**: LangGraph Store namespace design, Letta Memory Blocks

**Changes**:

| File | What |
|---|---|
| `memory/models.py` | `MemoryMetadata.type`: `Literal["episodic", "semantic", "procedural"]` (was `user/feedback/project/reference`). `Memory.anchors`: `list[Anchor] \| None` |
| `memory/store.py` | `_build_memory_file()` updated for new fields. Backward compat mapping: `user→episodic`, `feedback→procedural`, `project→semantic`, `reference→semantic` |
| `memory/context.py` | `_build_filtered_section()` groups by type, shows procedural first |
| `tools/memory_tool.py` | `memory_write` schema: add `type` enum + `anchors` param |
| `test_plan_mode.py` | Type tests, anchor roundtrip, backward compat |

**New data structures**:

```python
@dataclass
class Anchor:
    kind: str           # "file" | "symbol" | "task"
    path: str | None    # file path (for file/symbol)
    name: str | None    # symbol name (for symbol)
    value: str | None   # task type keyword (for task)

@dataclass
class MemoryMetadata:
    type: str = "semantic"  # "episodic" | "semantic" | "procedural"
```

**Tests**:
- `test_memory_types_episodic_semantic_procedural`
- `test_memory_anchors_roundtrip`
- `test_memory_backward_compat_old_types`

**Verification**: `python -m pytest test_plan_mode.py -k "memory_type or anchor"`

**Reflection**: The anchor field is the critical enabler for procedural
memory retrieval. Without it, procedural rules can't be triggered precisely.
The type enum replaces the vague `user/feedback/project/reference` with
cognitively grounded categories.

---

### Stage 2: Auto-Extraction Pipeline (Formation)

**Learn from**: Mem0's Extract phase, Generative Agents' reflection mechanism

**Changes**:

| File | What |
|---|---|
| `memory/extractor.py` (new) | `MemoryExtractor.extract(task, log_events) → list[MemoryCandidate]` |
| `agent/core.py` | `_run_body` FINISH path: call extractor, write candidates |
| `test_plan_mode.py` | Extraction tests |

**Extraction flow**:

```
EventLog (last N steps)
    ↓
Build context summary:
  - task description
  - tools used (names only, not full output)
  - final summary
    ↓
LLM call (temperature=0, structured JSON output):
  [
    {
      "type": "episodic" | "semantic" | "procedural",
      "content": "...",
      "description": "...",
      "anchors": [...],
      "confidence": "high" | "medium" | "low"
    }
  ]
    ↓
Filter: drop confidence="low"
    ↓
For each candidate: MemoryStore.consolidate() (Stage 3)
```

**LLM prompt design** (critical):
- Episodic: "What specific tool interaction happened? Focus on outcomes."
- Semantic: "What general fact about this project was confirmed?"
- Procedural: "What rule or constraint was applied? What pattern was followed?"
- NOT: "Summarize the conversation." This produces useless text.

**Trigger timing**:
- SUCCESS: always extract
- GAVE_UP: don't extract
- FAILED/MAX_STEPS: don't extract
- Extraction failure (LLM error): log warning, don't block

**Tests**:
- `test_extractor_extracts_episodic_from_success`
- `test_extractor_extracts_procedural_from_correction`
- `test_extractor_no_extraction_on_gave_up`
- `test_extractor_no_block_on_llm_failure`

**Verification**: `python -m pytest test_plan_mode.py -k "extractor"`

**Reflection**: The extraction prompt is the single most important design
decision. It determines whether memories are useful or noise. Start with a
conservative prompt (fewer, higher-quality memories) and iterate.

---

### Stage 3: Consolidation (Merge/Dedup)

**Learn from**: Mem0's ADD/UPDATE/MERGE/NOOP pipeline, LangGraph Store's
key-identity writing

**Changes**:

| File | What |
|---|---|
| `memory/store.py` | `consolidate(candidate) → str` (returns action) |
| `memory/extractor.py` | Write via `consolidate()` instead of `write_memory()` |
| `test_plan_mode.py` | Consolidation tests |

**Pipeline**:

```
MemoryCandidate
    ↓
ExternalMemoryStore.search(query=candidate.content, top_k=3)
    ↓
    ├─ max cosine < 0.5  → ADD (no similar memory exists)
    ├─ 0.5 ≤ max < 0.85  → LLM judge: ADD | UPDATE | MERGE | NOOP
    └─ max ≥ 0.85        → MERGE (very similar, combine)
```

**LLM judge prompt** (for the 0.5-0.85 gray zone):

```
Existing memory (id=X): "{content}"
New candidate: "{content}"

Decide:
- ADD: entirely new information
- UPDATE: same topic, new information supersedes old
- MERGE: complementary information, combine both
- NOOP: already captured
```

**Tests**:
- `test_consolidate_add_new` → ADD
- `test_consolidate_update_changed` → UPDATE
- `test_consolidate_merge_complementary` → MERGE
- `test_consolidate_noop_identical` → NOOP

**Verification**: `python -m pytest test_plan_mode.py -k "consolidate"`

**Reflection**: Thresholds (0.5, 0.85) are based on Mem0's published values
but should be tuned against our embedding model (`BAAI/bge-small-zh-v1.5`).
Monitor false-merge rate and adjust.

---

### Stage 4: Differentiated Retrieval

**Learn from**: LangGraph Store's semantic search, Letta Block's direct
injection, ACT-R spreading activation

**Changes**:

| File | What |
|---|---|
| `memory/context.py` | Rewrite `build_memory_section()` with type-differentiated retrieval |
| `memory/context.py` | Add `_build_procedural_section(current_file_paths)` |
| `agent/core.py` | Track `_current_file_reads: set[str]` per step for procedural trigger |
| `test_plan_mode.py` | Retrieval strategy tests |

**Per-type retrieval**:

```
TASK START (once):
  semantic:  ExternalMemoryStore.search(query=task_description, top_k=5)
  episodic:  ExternalMemoryStore.search(query=task_description, top_k=3,
              filter=type="episodic", sort=recency)
  → injected into long-term context message

PER STEP (when file anchor matches):
  procedural: MemoryStore.list(type="procedural", anchor_path in current_files)
  → injected into task anchor message
```

**Procedural trigger mechanism**:

```python
# In _run_body, after tool execution:
if tool_name in ("file_read", "file_view"):
    self._accessed_files.add(normalize_repo_path(path, repo_path))

# In _build_task_anchor():
procedural = self._build_procedural_section(self._accessed_files)
```

**Tests**:
- `test_procedural_triggered_when_file_read`
- `test_procedural_not_triggered_for_unrelated_file`
- `test_semantic_injected_at_task_start`
- `test_episodic_injected_at_task_start`

**Verification**: `python -m pytest test_plan_mode.py -k "procedural_trigger or semantic_inject or episodic_inject"`

**Reflection**: The file access tracker (`_accessed_files`) must handle
path normalization consistently with `normalize_repo_path`. This is the
bridge between the agent's runtime behavior and memory retrieval.

---

### Stage 5: Memory Validation and Expiry

**Learn from**: ACT-R activation decay, Ebbinghaus forgetting curve,
Letta's file-based memory validation

**Changes**:

| File | What |
|---|---|
| `memory/models.py` | `Memory` add `validated_at`, `stale`, `access_count` |
| `memory/store.py` | `mark_stale_for_file(path)` — marks memories anchored to a path as stale |
| `memory/store.py` | `prune_expired()` — episodic memories with no access in N days |
| `agent/core.py` | After `file_write`/`file_edit`: call `mark_stale_for_file` |
| `test_plan_mode.py` | Staleness and expiry tests |

**Staleness flow**:

```
file_write("agent/core.py")
    ↓
MemoryStore.mark_stale_for_file("agent/core.py")
    ↓
All memories with anchor.path="agent/core.py" → stale=True
    ↓
Next time agent reads agent/core.py:
    procedural section includes note: "⚠ This rule may be outdated. Verify."
    ↓
Agent can confirm or update the rule
    ↓
Reset stale=False, validated_at=now
```

**Expiry** (Ebbinghaus curve):

```
episodic retention: R(t) = e^(-t / S)
  S = base_S × importance_factor
  base_S = 30 days
  importance_factor = 0.5 (low) | 1.0 (normal) | 2.0 (high)
  → low importance: 50% retention at ~15 days
  → normal: 50% retention at ~30 days
  → high: 50% retention at ~60 days
```

When R(t) < 0.1, the memory is eligible for pruning.

**Tests**:
- `test_file_memory_stale_on_file_write`
- `test_procedural_no_stale_on_file_read`
- `test_episodic_decay_prunes_old_memories`

**Verification**: `python -m pytest test_plan_mode.py -k "stale or decay or prune"`

**Reflection**: Staleness detection is inherently imprecise — a file change
may or may not invalidate the rule. The `stale` flag is a heuristic signal,
not a guarantee. The agent should treat stale rules as "verify before applying"
rather than "discard immediately."

---

### Stage 6: Integration and Cleanup

**Changes**:

| File | What |
|---|---|
| `agent/core.py` | Remove `_build_working_context` naming; rename to `_build_task_anchor`. Update comments: "Layer 3" → "Per-step task anchor (not a memory layer)" |
| `agent/core.py` | Rename `_long_term_context_cached` to `_long_term_context` |
| `memory/context.py` | MemoryContext integration with new type system |
| `memory/store.py` | Remove old `_rebuild_index` dead branches if any (already done in P0) |

**Manual CLI regression**:

1. **纠正被记住**: 
```powershell
python -m entry.cli run --repo . --mode plan --auto-approve \
  --task "请在处理 YAML 时使用 yaml.safe_load 而不是正则"
```
→ Check that a procedural memory is created with file anchor

2. **重复纠正不产生重复记忆**:
Same task run twice → consolidate recognizes NOOP, no duplicate

3. **下次任务 procedural 自动激活**:
```powershell
python -m entry.cli run --repo . --mode plan --auto-approve \
  --read "config/default.yaml" \
  --task "读取配置"
```
→ Check that the procedural rule appears in the task anchor message

**Final verification**:
```powershell
python -m pytest test_plan_mode.py
python -m compileall agent entry tools llm context memory
git diff --check
```

**Reflection**: This is the end-to-end validation gate. If any stage
produced thresholds that are wrong (too many memories, too few triggers,
noise in injection), this is where we tune them.

---

## 5. What We Explicitly Do NOT Build

| Feature | Reason |
|---|---|
| Background sleep-time agents | Coding agent is not a long-running service |
| Knowledge graph (Neo4j/Neptune) | File→symbol mapping already in `repo_map` |
| Multi-modal memory (image/audio) | Pure code and text scenario |
| RL-trained memory policies | Single-user scenario, no training data pipeline |
| Distributed storage (PostgreSQL/Redis/MongoDB) | Single-user, SQLite + files sufficient |
| "Working memory" as a separate module | The context window IS working memory |

---

## 6. Dependency Between Stages

```
Stage 1 (types + anchors) ──▶ Stage 2 (extraction) ──▶ Stage 3 (consolidation)
                                                             │
Stage 4 (retrieval) ◀── Stage 1 (anchors needed for procedural trigger)
Stage 4 (retrieval) ◀── Stage 3 (deduped memories)
Stage 5 (validation) ◀── Stage 1 (anchors needed for file staleness)
Stage 5 (validation) ◀── Stage 2 (auto-created memories to validate)
Stage 6 (integration) ◀── All previous stages

Recommended execution order: 1 → 2 → 3 → 4 → 5 → 6
Stages 4 and 5 can theoretically run in parallel after 3.
```

---

## 7. Success Metrics

| Metric | Target | How to measure |
|---|---|---|
| Type accuracy | Procedural memories always have anchors | Assertion in `consolidate()` |
| Dedup rate | >90% of duplicate facts recognized | Log ADD/NOOP ratio in Stage 3 tests |
| Procedural trigger precision | >80% of triggered rules are relevant | Manual CLI review in Stage 6 |
| Extraction noise | <30% of auto-extracted memories are discarded later | Track extraction count vs. later prune count |
| Token budget for memory | Long-term context < 15% of history budget | Estimate in `_build_messages` |
| Staleness catch rate | >50% of file-modified procedural rules flagged stale | Manual CLI review |
