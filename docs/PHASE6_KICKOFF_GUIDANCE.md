# Phase 6 Kickoff — 功能增量与安全加固

> **版本**: 1.0
> **日期**: 2026-07-22
> **前序闭合**: Phase 5 (P1 35/35·100%, P2 27/53·51%, ACC-1~5 all PASS)
> **目标定位**: Phase 6 = 功能增量 (observability, validation) + 安全加固 (16 deferred P2) + 架构优化 (token budget, compaction)
> **预计总工时**: 24h

---

## 目录

1. [Phase 6 目标定义](#1-phase-6-目标定义)
2. [8 模块遗产接口契约冻结清单](#2-8-模块遗产接口契约冻结清单)
3. [Deferred P2 重评估](#3-deferred-p2-重评估)
4. [ACC 基线继承与扩展](#4-acc-基线继承与扩展)
5. [Phase 6 批次概览](#5-phase-6-批次概览)
6. [Readiness Checklist](#6-readiness-checklist)
7. [元数据](#7-元数据)

---

## 1. Phase 6 目标定义

### 功能增量 (12 项)

| 优先级 | 目标 | 说明 |
|--------|------|------|
| HIGH | Observability 升级 | P2-18 LLM retry metrics → Langfuse `RetryMetrics`; session-level token accounting |
| HIGH | 输入验证加固 | P2-45 Session ID regex, P2-46 Pydantic settings, P2-47 attachment filename |
| MEDIUM | 前端体验收尾 | P2-13/14 dynamic config endpoints, P2-26 CSS consolidation, P2-27 timeline key stability, P2-28 user identity |
| LOW | 死代码清理 | P2-29 AbortController, P2-33 plan trace cast, P2-34 Share button (done) |

### 安全加固 (16 deferred P2 — 见 §3)

| 风险 | 数量 | 焦点 |
|------|------|------|
| HIGH | 6 | P2-49/50/51/52/54/55 — 深度安全 bypass (permission pipeline, worktree TOCTOU, symlink races) |
| MEDIUM | 5 | P2-18 Langfuse, P2-38 hook FAIL_CLOSED, P2-40/41 tool validator/retry |
| LOW | 5 | P2-36 MicroCompactor, P2-37 token overhead, P2-44 hash normalization, P2-45-48 validation |

### 架构优化 (4 项)

| 目标 | 说明 |
|------|------|
| Token budget accuracy | P2-37: per-message overhead constant (+5 tokens/msg) |
| Compaction safety | P2-36: MicroCompactor returns new list |
| Atomic write hardening | P2-42 done in Phase 5; P2-44 line-ending normalization |
| Session Service performance | P2-48: `SELECT COUNT(*)` for msg_count |

---

## 2. 8 模块遗产接口契约冻结清单

> **约束**: Phase 6 所有变更不得破坏这些模块的公开 API 签名。若需变更，必须更新此 SSOT 并重新评审。

### 2.1 agent/loop/types.py — 循环控制类型

```python
# Public API — FROZEN
from agent.loop.types import (
    LoopAction,              # Enum[CONTINUE, RETRY_WITH_COMPACT, RETURN]
    StepResult,              # Dataclass(action, return_result, history_messages, step_increment, tokens_consumed)
    CompletionBlockTracker,  # Dataclass(threshold, should_block(reason) -> bool)
)
```

**健康**: 64 lines, doc=OK, types=OK, 3 public symbols.  
**Phase 6 约束**: 不可修改 `LoopAction` enum 成员；新增 `StepResult` 字段需保持向后兼容。

### 2.2 agent/constants.py — 配置常量

```python
# Public API — FROZEN (18 constants)
from agent.constants import (
    COMPLETION_BLOCK_THRESHOLD, DIFF_PREVIEW_MAX_CHARS,
    DEFAULT_REQUEST_BUDGET_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS,
    BUDGET_WARNING_PCT, BUDGET_COMPACT_PCT,
    SUMMARY_TRUNCATION_CHARS, DEFAULT_TRUNCATE_OUTPUT_CHARS,
    # ... + 10 more
)
```

**健康**: 55 lines, doc=OK, pure constants (0 functions — expected).  
**Phase 6 约束**: 可新增常量，不可删除/重命名已有常量（core.py 引用点需同步更新）。

### 2.3 server/services/chat_pipeline.py — ChatPipeline

```python
# Public API — FROZEN
from server.services.chat_pipeline import (
    ChatExecutionContext,  # Dataclass with 8 fields
    ChatPipeline,          # 6-stage orchestrator
    # ChatPipeline methods (in execution order):
    #   resolve_mentions(ctx) -> None
    #   apply_model_switch(ctx) -> LLMBackend | None
    #   inject_session_context(ctx) -> None
    #   build_callbacks(ctx) -> None
    #   execute(ctx) -> RunResult
    #   finish(ctx, result) -> None
    #   run_in_background(ctx) -> None
)
```

**健康**: 349 lines, doc=OK, 2 public classes, types=OK.  
**Phase 6 约束**: 方法签名不可变。可新增 `validate(ctx)` 插入管道。

### 2.4 web/src/utils/format.ts

```typescript
export function formatBytes(size: number): string;
export function formatRuntime(createdAt?: string | null): string;
export function runtimeSeconds(createdAt?: string | null): number;
export function formatValue(v: unknown): string;
```

### 2.5 web/src/utils/status.ts

```typescript
export function summarizeStatus(status?: string): string;
```

### 2.6 web/src/utils/target.ts

```typescript
export function summarizeTarget(name: string, params: Record<string, unknown>): string;
```

### 2.7 web/src/utils/markdown.ts

```typescript
export function renderMarkdownSafe(text: string | undefined | null): { __html: string } | null;
```

### 2.8 web/src/hooks/useWebSocket.ts

```typescript
export function connectWebSocket(sessionId: string, callbacks: WsCallbacks): void;
export function disconnectWebSocket(): void;
export function scheduleReconnect(sessionId: string, retries: number, cb: (sid: string) => void): void;
```

---

## 3. Deferred P2 重评估

### 3.1 自动解决检查 — 0 items

经逐项检查，Phase 5 的架构变更（ChatPipeline, useWebSocket extraction, constants externalization, BlockTracker）**均未** 自动解决任一 deferred P2。所有 16 项仍需 Phase 6 主动处理。

### 3.2 依赖关系重评估

| P2 | 依赖 Phase 5 模块? | 与新功能依赖? | 建议 Phase 6 批次 |
|----|-------------------|-------------|-----------------|
| P2-18 RetryMetrics | 依赖 ChatPipeline.execute | **是** — 与 Observability 目标耦合 | Batch A (优先) |
| P2-38 Hook FAIL_CLOSED | 依赖 hooks/dispatcher (Phase 5 B3 修改过) | 否 | Batch A |
| P2-40 Tool validator | 否 | **是** — 与 Validation 目标耦合 | Batch A |
| P2-41 Retry classification | 依赖 llm/invoker (Phase 5 E1-3 修改过) | 否 | Batch A |
| P2-49 SessionMemory bypass | 是 — 需通过 ToolRegistry 重写 | 否 | Batch B |
| P2-50 bypassPermissions prop | 依赖 SessionRuntime (Phase 5 A2 修改过) | 否 | Batch B |
| P2-51 ROOT_REMOVAL patterns | 否 | 否 | Batch B |
| P2-52 scoped callback share | 依赖 hitl/pipeline (Phase 5 B1 修改过) | 否 | Batch C |
| P2-54 Worktree TOCTOU | 否 | 否 | Batch C |
| P2-55 safe_open_for_write | 否 | 否 | Batch C |
| P2-36 MicroCompactor | 否 | 否 | Batch C |
| P2-37 Token overhead | 是 — 依赖 constants.py | 否 | Batch C |
| P2-44 Hash normalization | 否 | 否 | Batch C |
| P2-13/14 Config endpoints | 否 | **是** — 前端体验目标 | Batch B |
| P2-25 WS cast | 是 — 依赖 useWebSocket hook | **是** — 前端体验目标 | Batch B |
| P2-45/46/47/48 Validation | 否 | **是** — 输入验证目标 | Batch A |

### 3.3 风险评级调整

| P2 | 原评级 | 新评级 | 调整理由 |
|----|--------|--------|---------|
| P2-18 | MEDIUM | **HIGH** | ChatPipeline 管道完成，观测集成风险降低但需求紧迫度提升 |
| P2-25 | MEDIUM | LOW | useWebSocket 提取后 WS 消息流已封装，cast 范围缩小 |
| P2-38 | MEDIUM | MEDIUM | 不变 — dispatcher 已在 Phase 5 B3 修改，集成测试基线就绪 |
| P2-40/41 | MEDIUM | MEDIUM | 不变 |
| P2-13/14 | LOW | MEDIUM | 需后端 config endpoint 新增 — 依赖链延长 |
| P2-45/46/47/48 | LOW | LOW | 纯输入验证 — 低影响，高覆盖 |

---

## 4. ACC 基线继承与扩展

### 4.1 继承基线 (Phase 6 最低质量门禁)

| ACC | 内容 | Phase 5 状态 | Phase 6 继承 |
|-----|------|------------|------------|
| ACC-1 | 无循环依赖 | PASS | 每次 import 新增时重检 |
| ACC-2 | 类型注解+docstrings | PASS | 新增代码强制 |
| ACC-3 | 零裸魔数 | PASS | constants.py 扩展 |
| ACC-4a/b/c | 原子性/可见性/有序性 | PASS | 新增共享状态时复检 |
| ACC-5a/d/e | XSS/A11y/Contract | PASS | 每次前端变更时复检 |

### 4.2 Phase 6 扩展 — ACC-6 (Runtime Quality Baselines)

| 条款 | 内容 | 通过标准 |
|------|------|---------|
| **ACC-6a** Observability | Langfuse retry metrics 已上报 | `RetryMetrics` counter visible in Langfuse dashboard |
| **ACC-6b** Input Validation | Session/attachment 输入有 schema 校验 | Pydantic model + regex + filename sanitization |
| **ACC-6c** E2E Coverage | 核心对话流程有自动化测试 | `test_abort_e2e.py` self-contained, passes 5/5 runs |

---

## 5. Phase 6 批次概览

### Batch A — Observability + Validation (8h, HIGH priority)

| P2/Feature | 内容 |
|-----------|------|
| P2-18 | LLM retry → Langfuse `RetryMetrics` |
| P2-40 | Tool call validator param type check |
| P2-41 | Retry classification → HTTP status code |
| P2-45 | Session ID regex validation |
| P2-46 | Session settings Pydantic model |
| P2-47 | Attachment filename sanitization |
| P2-48 | Session list msg_count optimization |

### Batch B — Frontend UX + Pipeline Security (8h)

| P2/Feature | 内容 |
|-----------|------|
| P2-13/14 | MODEL_OPTIONS / SUGGESTED_PROMPTS → `/api/config` |
| P2-25 | WS parse type guard |
| P2-26/27/28 | CSS consolidation / timeline keys / user identity |
| P2-29 | EventSidebar AbortController |
| P2-33 | Plan trace cast → typed guard |
| P2-49 | SessionMemory → ToolRegistry routing |
| P2-50 | bypassPermissions child cap |

### Batch C — Security Deep Audit + Cleanup (8h)

| P2/Feature | 内容 |
|-----------|------|
| P2-36 | MicroCompactor return-new-list or doc |
| P2-37 | Token overhead constant |
| P2-38 | Hook exception FAIL_CLOSED |
| P2-44 | Memory hash line-ending |
| P2-51/52/54/55 | ROOT patterns / callback share / worktree / safe_open |

---

## 6. Readiness Checklist

| # | 条件 | 状态 |
|---|------|------|
| 1 | Phase 5 Closure Report 已归档 (`docs/PHASE5_CLOSURE_REPORT.md`) | DONE |
| 2 | 8 模块遗产健康检查通过 (7/8 explicit public API; constants.py is declaration-only) | DONE |
| 3 | 16 deferred P2 重评估完成 (0 auto-resolved, 3 risk-adjusted, 12 retain) | DONE |
| 4 | ACC 基线已编码 (ACC-1~5 inherited, ACC-6 added) | DONE |
| 5 | Phase 6 目标与范围已获利益相关方确认 (3 batches, 24h estimated) | **PENDING** |
| `-->` Phase 6 正式启动门禁 = item 5 确认 | | |

---

## 7. 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **日期** | 2026-07-22 |
| **输入基线** | PHASE5_CLOSURE_REPORT.md + 8 module SSOT |
| **Deferred P2** | 16 items, 0 auto-resolved by Phase 5, 3 risk-adjusted |
| **ACC 继承** | ACC-1~5 inherited, ACC-6 (Runtime Quality) added |
| **预计总工时** | 24h (3 batches: 8h + 8h + 8h) |
| **下一阶段** | Stakeholder confirmation `->` Batch A execution |
