# Phased Analysis Strategy

## 1. Why this document exists

This document captures a design lesson from testing forge-agent on broad read-only
analysis tasks such as:

- "audit the tools, MCP, and skills modules";
- "summarize the architecture of a subsystem";
- "identify main problems and propose an optimization roadmap".

The observed failure mode was not a small token-limit problem. Raising the total
task budget from 80k to 120k still failed because the agent handled a broad
analysis request by reading many implementation files linearly. The budget acted
only as a late fuse; it did not teach the agent how to gather information.

The target design is based on a simple rule:

> For broad read-only analysis, move from structure to details, and from evidence
to synthesis. Do not default to reading every file.

## 2. Problem statement

A broad analysis task has a different information shape from a targeted lookup.

A targeted lookup may need one exact symbol or one exact file section. A broad
analysis task needs the architecture, boundaries, trade-offs, and priorities.
Reading every leaf implementation file first is usually wasteful and sometimes
actively harmful because it:

- consumes the task budget before synthesis starts;
- pollutes history with raw tool outputs;
- hides architectural signals under implementation detail;
- encourages repeated or unfocused file reads;
- makes the final answer depend on exhaustiveness rather than relevance.

The correct behavior is not to increase `agent.budget_tokens` indefinitely. The
correct behavior is to use a phased information-gathering strategy.

## 3. Desired agent behavior

For read-only tasks that ask for architecture, audit, comparison, optimization,
prioritization, or roadmap, the agent should follow this default strategy.

### 3.1 Classify the task shape first

Before reading many files, classify the request as one of:

- **targeted lookup**: answer depends on a specific symbol, file, error, or config;
- **broad analysis**: answer depends on subsystem structure and trade-offs;
- **verification pass**: answer checks whether a specific claim is true;
- **implementation task**: user expects code changes.

Only broad analysis needs the phased strategy below.

### 3.2 Start with the map, not the leaves

For broad analysis, start by identifying structure:

- directory layout;
- registration entry points;
- base classes and interfaces;
- managers, registries, routers, factories;
- configuration schema and runtime wiring.

Do not begin by reading every implementation file under a directory.

### 3.3 Read abstraction and wiring first

Prefer files that explain the system boundary:

- `base.py`, `schema.py`, `registry.py`, `manager.py`, `router.py`, `factory.py`;
- CLI or runtime registration paths;
- adapter/proxy layers;
- tests that encode intended behavior.

Read leaf implementation files only when they verify a named claim or fill a
specific gap.

### 3.4 Limit each reading phase

A broad analysis phase should normally read at most 3-5 key files before
synthesizing. After that, the agent should stop and produce a short internal
summary:

- what is confirmed;
- what is inferred;
- what remains unknown;
- which file, if any, would close the next gap.

The next file read must be justified by a specific gap, not by directory
coverage.

### 3.5 Preserve uncertainty instead of chasing exhaustiveness

If the agent has enough evidence for a useful answer, it should answer. If it
lacks evidence, it should say what is uncertain. It should not read the entire
module simply to avoid uncertainty.

A useful final answer should separate:

- confirmed architecture;
- likely issues;
- risks requiring deeper verification;
- prioritized next steps.

## 4. Plan-reflect-test optimization loop

The desired development workflow for improving this behavior is itself phased.

### 4.1 Plan

Write a small plan for the specific analysis behavior to improve. The plan should
state:

- the target scenario;
- the expected tool-use shape;
- the prompt or policy change to try;
- the observable success criteria.

Example target scenario:

> Audit `tools/`, MCP, and skills without reading every implementation file.

Expected shape:

1. discover relevant files;
2. read registration and base abstractions;
3. read MCP manager and skill registry/tool;
4. synthesize architecture and roadmap;
5. stop.

### 4.2 Reflect

After running the scenario, compare actual behavior with the expected shape:

- Did the agent read too many files?
- Did it read leaf implementations before abstractions?
- Did it summarize before continuing?
- Did it cite files it did not read in the current evidence scope?
- Did it stop once the answer was good enough?

Record new failure modes as design notes instead of immediately patching random
symptoms.

### 4.3 Test

Each improvement should have at least one lightweight regression test where
possible. Tests can cover:

- prompt text contains the strategy constraints;
- policy blocks out-of-scope reads;
- loop detection does not punish normal pagination;
- duplicate exact reads are suppressed;
- renderer displays evidence ranges.

For behavior that is hard to unit test, use a repeatable chat prompt and inspect
the tool trace.

### 4.4 Continue

If a test reveals a new issue, add it to the design backlog and repeat the loop:
plan → implement the smallest change → test → reflect.

## 5. Proposed implementation phases

### Phase 0: Prompt-level strategy

Add general read-only analysis guidance to the analysis prompt.

Rules:

- Do not bulk-read all files under a directory for broad analysis tasks.
- Start with discovery and key wiring files.
- Prefer abstractions before leaf implementations.
- After reading 3-5 files, synthesize before reading more.
- Read additional files only to answer a named gap.
- State uncertainty instead of chasing full coverage.

This is the lowest-risk change and teaches the agent the desired behavior.

### Phase 1: Tool-use guardrails

Add soft guardrails for analysis mode:

- track file reads per task;
- warn or reflect after too many distinct file reads without synthesis;
- distinguish normal `file_view` pagination from repeated reads;
- keep exact duplicate read suppression.

The purpose is not to forbid reading. The purpose is to force an intermediate
summary before the agent keeps consuming context.

### Phase 2: Phased analysis controller

Introduce an explicit phased analysis flow for broad read-only tasks:

1. **Discover**: list files and identify likely entry points.
2. **Inspect**: read a small set of wiring/abstraction files.
3. **Synthesize**: produce an intermediate architecture summary.
4. **Verify**: read targeted leaf files only for named claims.
5. **Answer**: produce the final roadmap with confidence boundaries.

This can be implemented as a mode, a policy, or a prompt-injected workflow.

### Phase 3: Context compaction for analysis phases

After each phase, preserve a compact phase summary and avoid carrying raw file
outputs forward unnecessarily. This aligns with the broader context lifecycle
architecture: raw detail belongs inside the current task phase; distilled state
crosses phase boundaries.

### Phase 4: Observability

When Langfuse or equivalent tracing is added, record:

- phase name;
- files read per phase;
- lines/tokens read;
- phase summary tokens;
- claims verified vs. inferred;
- reason for each additional read after the first phase.

This makes it possible to see whether the agent is learning the desired analysis
shape.

## 6. Success criteria

A successful implementation should show these behaviors:

- broad analysis tasks finish without raising the total token fuse;
- the tool trace shows discovery before deep reads;
- only a handful of key files are read before the first synthesis;
- leaf files are read only for specific verification gaps;
- final answers include evidence boundaries;
- repeated exact reads are suppressed;
- normal pagination does not trigger loop detection.

## 7. Phase implementation notes

### 7.1 Phase 0 implemented: prompt-level strategy

Implemented in `prompts/task-analysis.md`.

The analysis prompt now teaches the broad read-only workflow directly:

- classify targeted lookup vs. broad analysis;
- do not bulk-read every file in a directory by default;
- start with discovery/search and key wiring files;
- prefer abstractions before leaf implementations;
- synthesize after reading 3-5 key files;
- read additional implementation files only for named gaps;
- state uncertainty instead of chasing exhaustive coverage.

Regression coverage was added in `tests/test_prompts.py` to ensure the strategy
remains present in future prompt changes.

### 7.2 Phase 0 reflection

This is a low-risk first step because it changes guidance rather than runtime
enforcement. It should improve many broad analysis tasks, but it remains a soft
constraint: a model can still ignore the prompt and bulk-read files.

New issues to carry into the next phase:

- prompt guidance is not enforceable by itself;
- the agent has no runtime counter for distinct files read during analysis;
- there is no automatic "pause and synthesize" trigger after 3-5 key files;
- `/stats` can show high task tokens after the fact, but it does not prevent the
  behavior early;
- phase summaries are not yet a first-class context object.

These issues motivate Phase 1: tool-use guardrails.

### 7.3 Phase 1 implemented: analysis read guardrail

Implemented in `agent/core.py`.

The agent now tracks distinct files read during an analysis task. After five
distinct files, it injects an `analysis_read_guardrail` reflection asking the
model to pause broad exploration and synthesize from current evidence before
reading more. This is intentionally a soft runtime guardrail: it does not fail
the task, and it still allows additional reads when the model names a specific
gap.

Related loop detection was tightened further: exact duplicate reads are still
considered loops, but sequential `file_read` / `file_view` calls with different
files or ranges are treated as progress rather than semantic repetition.

Regression coverage was added in `test_plan_mode.py` for:

- analysis guardrail reflection after many distinct files;
- normal `file_view` pagination not being a loop;
- repeated identical `file_view` ranges still being an exact loop.

### 7.4 Phase 1 reflection

The first Phase 1 test exposed a useful new issue: the previous semantic loop
rule treated repeated `file_read` calls as a loop even when each call read a
different file. That contradicted the intended rule: only the same tool reading
the same file/range should be considered invalid. The loop logic was adjusted to
leave `file_read` and `file_view` progress to exact-parameter checks.

New issues to carry into the next phase:

- the guardrail asks the model to synthesize, but there is no first-class phase
  summary object yet;
- the threshold of five distinct files is hard-coded and should eventually be
  configurable;
- the model can still continue reading after the guardrail if it ignores the
  reflection;
- broad-analysis phases are not yet explicit in traces or `/stats`;
- there is no separate budget for discovery, inspection, synthesis, and
  verification.

These issues motivate Phase 2: an explicit phased analysis controller.

## 8. Phase 2 implementation plan

Phase 2 upgrades complex read-only analysis tasks from prompt-only guidance to an
explicit phased analysis controller. The goal is a precise but non-aggressive
controller that reduces token waste, avoids linear whole-directory reading, and
keeps the behavior testable and easy to roll back.

### 8.1 Goal

For broad analysis tasks, the agent should follow this flow:

1. **Discover**: identify structure and likely entry points first.
2. **Inspect**: read a small set of key abstraction and wiring files.
3. **Synthesize**: produce an intermediate evidence summary.
4. **Verify**: read additional files only for named gaps or claims.
5. **Answer**: produce the final answer from available evidence instead of
   continuing exploration.

### 8.2 Design principles

- Do not affect normal edit tasks.
- Do not affect targeted lookups or explicitly scoped file-reading requests.
- Implement Phase 2 as a small state machine plus phase-aware guardrails, not a
  complex sub-agent workflow.
- Keep Phase 0 prompt guidance and Phase 1 read guardrails in place.
- Do not solve the failure mode by increasing the global token budget.
- Keep each step covered by regression tests and reflected in this document.

### 8.3 Phase 2A: data structure and task detection

Add a lightweight phase state, either in `agent/core.py` or in a small helper such
as `context/analysis_phase.py`:

```python
AnalysisPhase = Literal["discover", "inspect", "synthesize", "verify", "answer"]

@dataclass
class AnalysisPhaseState:
    enabled: bool = False
    phase: AnalysisPhase = "discover"
    files_read: set[str] = field(default_factory=set)
    discovery_tools_used: int = 0
    inspect_reads: int = 0
    verify_reads: int = 0
    synthesize_requested: bool = False
    phase_summaries: list[str] = field(default_factory=list)
```

Enable the controller only when all of these are true:

- `intent == "analysis"`;
- the prompt looks like broad analysis, for example it contains terms such as
  architecture, audit, roadmap, review architecture, optimization, 梳理, 架构,
  审计, 路线图, 优先级, 主要问题, or 优化;
- the user did not explicitly constrain the task to specific files or paths.

Do not enable the controller for targeted scoped analysis such as "only read
A/B". Those tasks should continue to use the existing strict file-scope behavior.

Tests:

- broad analysis prompts enable the controller;
- targeted lookups do not enable the controller;
- explicitly scoped read requests do not enable the controller.

### 8.4 Phase 2B: phase anchor injection

Extend the task anchor so broad analysis tasks include a short controller section:

```text
## Phased Analysis Controller
Current phase: inspect
Files read: ...
Phase rules:
- Discover: use find/search before file reads.
- Inspect: read only key abstraction/wiring files.
- Synthesize: stop reading and summarize evidence.
- Verify: read only for named gaps.
- Answer: no more tools; answer from evidence.
```

The anchor must stay compact. It should show the current phase, read count, and at
most the first five read files so the controller does not become a token-heavy
context object.

Tests:

- broad analysis anchors include the controller;
- targeted analysis anchors do not include the controller;
- the anchor includes the current phase and a compact read-file summary.

### 8.5 Phase 2C: phase transition rules

Start with deterministic transitions:

- initial phase is `discover`;
- after a discovery tool (`find_files`, `search_text`, or `find_symbol`) or the
  first file read, move to `inspect`;
- after 3-5 distinct files are read during inspection, move to `synthesize`;
- when entering `synthesize`, inject a reflection prompt asking for a phase
  summary or final answer;
- if the model continues reading, require it in the prompt to name a specific gap,
  but do not block the read in Phase 2;
- if verification reads exceed the small verification budget, move to `answer`.

The first implementation does not need to parse whether the model truly named a
gap. The runtime should provide the constraint and remain soft.

Tests:

- after five distinct file reads, the phase becomes `synthesize`;
- `file_view` pagination of the same file does not increase distinct file count;
- duplicate synthetic observations do not increase read count;
- the synthesize transition triggers only once.

### 8.6 Phase 2D: phase-aware tool guardrail

Replace the generic analysis read guardrail with a phase-aware reflection.

Previous behavior:

- after five distinct analysis file reads, inject `analysis_read_guardrail`.

New behavior:

- when the inspect threshold is reached, enter `synthesize` and inject
  `analysis_phase_synthesize`.

Reflection prompt shape:

```text
[SYSTEM] Phased analysis controller:
You have completed the Inspect phase after reading N files.
Do not read more files now.
Synthesize:
- confirmed architecture
- confirmed issues
- uncertainty
- named gaps
Then either answer or request one specific verification read.
```

Tests:

- the reflection reason is `analysis_phase_synthesize`;
- the prompt mentions confirmed architecture, uncertainty, and named gaps;
- if the next model action is `finish`, the task succeeds.

### 8.7 Phase 2E: documentation reflection

After implementation, update this document with:

- what Phase 2 implemented;
- the fact that the controller is still soft and not full enforcement;
- the fact that phase summaries are not yet compacted into first-class context;
- the fact that Langfuse or equivalent spans are still future work;
- why Phase 3 should focus on phase summaries and context compaction.

### 8.8 Test plan

Focused regression commands:

```bash
python -m pytest tests/test_prompts.py -q
python -m pytest test_plan_mode.py::test_analysis_read_guardrail_reflects_after_many_distinct_files -q
python -m pytest test_plan_mode.py::test_file_view_paging_is_not_semantic_loop -q
```

New tests to add:

- `test_broad_analysis_enables_phase_controller`;
- `test_targeted_scoped_analysis_does_not_enable_phase_controller`;
- `test_phase_controller_moves_to_synthesize_after_distinct_reads`;
- `test_phase_anchor_includes_current_phase`;
- `test_phase_synthesize_reflection_mentions_named_gaps`.

### 8.9 Risks and mitigations

- Risk: the phase anchor becomes too long and increases token usage. Mitigation:
  keep it short and show at most five files.
- Risk: the controller blocks necessary reads too early. Mitigation: Phase 2 uses
  soft reflection and does not block tool calls.
- Risk: ordinary question answering is affected. Mitigation: enable the
  controller only for broad analysis without explicit file scope.
- Risk: the state machine becomes hard to maintain. Mitigation: keep it in a
  small dataclass and avoid spreading phase logic into policy, context manager,
  and tool implementations.

### 8.10 Implementation order

1. Add broad-analysis detection and `AnalysisPhaseState`.
2. Initialize phase state in `ReActAgent.run()`.
3. Update phase state after successful file reads and discovery tools.
4. Inject the phase controller in `_build_task_anchor()`.
5. Replace or enhance the analysis read guardrail with phase-aware reflection.
6. Add regression tests.
7. Update this document with Phase 2 implementation reflection.

## 9. Phase 2 implementation notes

Implemented in `agent/core.py`.

The agent now creates an `AnalysisPhaseState` for broad, unscoped read-only
analysis tasks. The controller is enabled only when the task intent is
`analysis`, the request matches broad-analysis language, and no explicit or
strict file scope is active. Targeted lookups and ordinary edit tasks keep their
existing behavior.

The active task anchor now includes a compact `Phased Analysis Controller`
section for enabled tasks. It reports the current phase, read count, and a short
summary of up to five read files. The phase rules are intentionally concise so
the anchor does not become a new token sink.

Phase transitions are deterministic and local to the ReAct runtime:

- `discover` starts the broad analysis controller;
- discovery tools or the first successful file read move the task to `inspect`;
- five distinct read files move the task to `synthesize`;
- duplicate reads and additional `file_view` windows of the same file do not
  increase the distinct-file phase count;
- if the model continues reading after synthesis, the next new file read moves the
  task to `verify`;
- the second verification read exhausts the small verification budget and moves
  the task to `answer`, though Phase 2 does not yet parse named gaps from model
  text.

The previous generic `analysis_read_guardrail` remains as fallback behavior for
analysis tasks without the controller. For enabled broad analysis tasks, the
inspect threshold now injects an `analysis_phase_synthesize` reflection that asks
for confirmed architecture, confirmed issues, uncertainty, and named gaps before
any further reading.

Regression coverage was added in `test_plan_mode.py` for controller activation,
scoped-task exclusion, phase transitions, duplicate-read counting, anchor content,
one-time synthesis reflection, phase-aware synthesis reflection, and verification
budget exhaustion. Existing prompt strategy coverage remains in
`tests/test_prompts.py`.

### 9.1 Phase 2 reflection

Phase 2 is still a soft controller, not full enforcement. It changes runtime
state, prompt anchoring, and reflection timing, but it does not block a model that
continues reading after synthesis. That is deliberate: this phase should improve
analysis discipline without preventing necessary verification reads.

Follow-up improvements implemented after the initial Phase 2 pass:

- phase thresholds are now configurable instead of hard-coded;
- context stats expose the current analysis phase, files read, inspect reads, and
  verification reads;
- event logs include lightweight `analysis_phase` transition events;
- the phase anchor can carry a deterministic phase summary after the synthesize
  reflection;
- verification reads after synthesis are counted and can move the controller to
  `answer` when the verification budget is exhausted.

Known limitations to carry forward:

- the deterministic phase summary is metadata only; it does not yet summarize the
  semantic content of evidence read during the phase;
- the controller does not compact or demote raw inspect evidence after synthesis;
- named verification gaps are requested in the prompt but not parsed or enforced;
- there are no Langfuse or equivalent spans for phase timing, files, or token
  counts beyond local event logs and context stats.

These limitations point to Phase 3: preserve richer phase summaries, compact or
demote raw phase evidence, and make verification reads depend on named gaps.

## 10. Phase 3 evidence lifecycle

Phase 3 upgrades phase summaries from deterministic counters to a structured
evidence lifecycle. The goal is not merely to truncate old messages. The goal is
to separate raw observations, evidence records, phase memory, and prompt views.

Implemented in `context/evidence.py`, `context/artifacts.py`, `context/manager.py`,
and `agent/core.py`.

### 10.1 Evidence ledger

Successful broad-analysis read/search observations now create `EvidenceRecord`
objects. Each record captures:

- evidence id;
- phase;
- tool name;
- file path and range when available;
- compact summary;
- artifact id for the raw observation;
- estimated token count;
- whether it is key evidence.

Raw evidence output is also stored in `ArtifactStore`, even for read tools that
are normally exempt from threshold-based artifacting. This preserves raw detail
outside the prompt while letting the prompt carry compact evidence references.

### 10.2 Phase memory

When the controller reaches the synthesize boundary, the ledger creates a
`PhaseSummary` for the inspect phase. The summary contains inspected files,
evidence ids, artifact ids, confirmed fact stubs, open gaps, and token totals.
This summary is injected into the phase anchor as durable phase memory.

This is still deterministic: it does not yet ask an LLM to produce semantic
architecture conclusions. It creates the structural memory needed for a later
semantic summarizer.

### 10.3 Prompt materialization

`ContextManager.build_request_messages()` now accepts a history materializer hook.
For completed analysis phases, `ReActAgent` uses that hook to turn raw tool result
messages into compact evidence references before the prompt is sent to the model.
The underlying conversation history is not mutated, and native tool-calling
pairing is preserved because assistant tool calls and tool result ids remain in
place.

The effective prompt view becomes:

- current phase evidence: still available in more detail;
- completed phase evidence: represented by phase summary and evidence refs;
- raw detail: available through artifacts instead of carried directly in prompt.

### 10.4 Semantic summaries, artifact retrieval, and verification gating

The deeper Phase 3 pass adds three lifecycle behaviors learned from mature agent
systems.

First, phase summaries can now be semantic. `EvidenceLedger` asks the configured
backend for a JSON-only summary with confirmed facts, open gaps, confidence
boundaries, and recommended verification reads. If the summarizer fails or cannot
produce structured JSON, the ledger falls back to deterministic summaries so the
agent run is not blocked.

Second, artifacts are exposed through read-only tools:

- `artifact_list` lists raw evidence artifacts captured during the current run;
- `artifact_read` retrieves raw evidence content by artifact id.

This gives the model a path back to raw details without repeating broad source
reads or carrying every raw observation in the prompt.

Third, post-synthesis source reads are gated by named verification candidates.
When the inspect phase has produced recommended verification reads, later
`file_read` / `file_view` calls outside that set are deferred with a synthetic
observation. The model is directed to use phase summaries and `artifact_read`, or
to answer with confidence boundaries rather than broadening exploration.

### 10.5 Same-round gating and durable evidence

A later trace showed that phase state was updated during a parallel `tool_calls`
round, but the controller still needed to prevent later calls in the same batch
from continuing broad reads. The execution loop now checks the verification gate
before each individual tool call, and each successful read updates phase state
immediately. If the inspect limit is reached by the fifth read in a single batch,
the sixth source read in that same batch is deferred instead of executed.

Another trace showed that counting only distinct file paths was insufficient: the
agent could repeatedly read many ranges from the same large file without reaching
the inspect threshold. The controller now counts unique read units, not just
unique files. A read unit is a normalized file range (`file_read` covers the first
500 lines; `file_view` covers its requested window). This means repeated windows
in `agent/core.py` can trigger synthesis even when the distinct file count stays
low.

Duplicate suppression also understands range coverage. After a `file_read`, a
later `file_view` fully covered by the first 500 lines is treated as duplicate,
while non-overlapping windows are still allowed until the read-unit budget is
exhausted.

A subsequent trace showed that the gate was technically working but still costly:
post-synthesis reads were converted to synthetic deferred observations, yet the
model kept attempting more source reads in later steps. The controller now treats
deferred reads as an explicit answer phase. The first deferred-read batch injects
a reflection that moves the phase to `answer`; on the next LLM call, no tools are
exposed in the schema, so the model must finish from the phase summary and
confidence boundaries. If a backend still returns a tool call despite the empty
tool schema, the runtime uses a deterministic answer boundary instead of spending
more LLM rounds.

Artifacts are now durable. `ArtifactStore` can attach a repo-relative storage
directory, persists artifacts as JSON, and loads existing artifacts when a new
store instance attaches to the same directory. The default durable location is
`.forge-agent/artifacts`.

Event logs now include full `evidence_record` events for each recorded evidence
item. Each event includes evidence id, phase, tool name, path/range, summary,
artifact id, token count, and key-evidence status.

### 10.6 Remaining Phase 3 gaps

- Semantic summary quality depends on the configured backend; deterministic
  fallback preserves safety but is less informative.
- Recommended verification reads are structured paths, not a full proof that the
  model's natural-language gap was valid.
- Langfuse or equivalent tracing is still future observability work.

## 11. Non-goals

This strategy does not try to make the agent omniscient from fewer files. It is
acceptable for the agent to say that a conclusion is based on the key paths it
inspected and that deeper verification could inspect specific additional files.

The goal is better analysis discipline, not artificial confidence.
