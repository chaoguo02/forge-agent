# Phase 5 Batch A 精准定位与理论指导方案

> **文档版本**: 1.0
> **生成日期**: 2026-07-21
> **Phase 5 定位**: 架构整合 — `_run_body` 拆分、`run_chat_async` 重构、core.py 配置化
> **输入基线**: CORE_ARCHITECTURE_REPORT.md SSOT + Phase 4 deferred P1 ×11
> **前置条件**: Phase 4 全 6 批次闭合，P0 13/13·100%，P1 24/33，VESP 7/7·100%
> **预计总工时**: 22h

---

## 目录

1. [11 项 Deferred P1 全景](#1-11-项-deferred-p1-全景)
2. [Refactoring Risk Matrix](#2-refactoring-risk-matrix)
3. [A1: `_run_body` 1470 行拆分 — 模块边界定义](#a1-_run_body-1470-行拆分--模块边界定义)
4. [A2: `run_chat_async` 重构 — 接口契约](#a2-run_chat_async-重构--接口契约)
5. [A3: core.py 魔数清理 — 配置化方案](#a3-corepy-魔数清理--配置化方案)
6. [Architecture Compliance Check 维度](#6-architecture-compliance-check-维度)
7. [VESP Phase 5 升级](#7-vesp-phase-5-升级)
8. [Phase 5 Readiness Checklist](#8-phase-5-readiness-checklist)
9. [元数据](#9-元数据)

---

## 1. 11 项 Deferred P1 全景

| # | TODO | 文件 | 类型 | 在 Batch A | 理由 |
|---|------|------|------|----------|------|
| **P1-1** | `_run_body` 1470 行拆分 | agent/core.py | 🔴 架构 | **A1** | 最高风险 — 调用链深度 3+，影响 1 文件但逻辑 1500 行 |
| **P1-2** | `_finish_run` 嵌套闭包提取 | agent/core.py | 🔴 架构 | **A1** | A1 前置 —— 拆分必然涉及 |
| **P1-3** | 恢复逻辑去重 (`_attempt_reactive_compact`) | agent/core.py | 🟠 去重 | **A1** | 提取为独立方法，低风险 |
| **P1-4** | `fact_check` + `verify_callback` 合并 | agent/core.py | 🟠 去重 | **A1** | `_apply_completion_check` 通用化 |
| **P1-5** | `_block_tracker` 状态机化 | agent/core.py | 🟡 类型 | **A1** | 随 A1 拆分重构类型 |
| **P1-6** | Git diff 截断魔数 `3000` | agent/core.py | 🟡 配置 | **A3** | 配置化 |
| **P1-7** | `max_tokens=32000` 重复 | agent/core.py | 🟡 配置 | **A3** | 配置化 |
| **P1-8** | 模块导入置于文件中间 | agent/core.py | 🟡 卫生 | **A1** | 拆分后自动消除（文件拆分） |
| **P1-9** | 私有属性访问 `.`_messages | agent/core.py | 🟡 卫生 | **A1** | 添加公共访问器 |
| **P1-10** | `run_chat_async` 280 行拆分 | agent_service.py | 🔴 架构 | **A2** | 调用链深度 3 |
| **P1-17** | core.py 2609 行 | agent/core.py | 🔴 元任务 | **A1+A2** | A1 完成后消除 |

---

## 2. Refactoring Risk Matrix

> **评分规则**: Risk = Impact × Regression Coverage × Rollback Viability。
> Impact: 影响文件数 + 调用链深度。Coverage: 现有测试对该代码路径的覆盖。Rollback: 能否单 commit revert 且不损坏数据。

| TODO | 影响范围 | 调用链深度 | 回归覆盖 | 回滚可行 | 风险等级 |
|------|---------|-----------|---------|---------|---------|
| **P1-1** `_run_body` 拆分 | 1 文件 → 6 文件 | **depth=4** | **低** — 无 `_run_body` 级集成测试 | ✅ 单 commit revert | 🔴 **HIGH** |
| **P1-2** `_finish_run` 提取 | 1 文件 → RunResult builder | depth=3 | **低** | ✅ 含在 P1-1 revert | 🔴 **HIGH** |
| **P1-3** 恢复逻辑去重 | 1 文件，2 个重复块 | depth=2 | **中** — prompt-too-long 路径被 test_e2e_core 部分覆盖 | ✅ 独立 revert | 🟡 **LOW** |
| **P1-4** check 合并 | 1 文件，2 个重复块 | depth=2 | **低** | ✅ 独立 revert | 🟡 **LOW** |
| **P1-5** 状态机化 | 1 文件，dict→dataclass | depth=1 | **中** | ✅ 独立 revert | 🟢 **NEGLIGIBLE** |
| **P1-6/7** 魔数→常量 | 1 文件 | depth=1 | **高** — 所有测试覆盖常量路径 | ✅ 独立 revert | 🟢 **NEGLIGIBLE** |
| **P1-8** 导入移动 | 1 文件 → 拆分后自动 | depth=0 | N/A | ✅ | 🟢 **NEGLIGIBLE** |
| **P1-9** 私有属性 | 3 文件（访问器添加） | depth=1 | **高** | ✅ 独立 revert | 🟢 **NEGLIGIBLE** |
| **P1-10** `run_chat_async` 拆分 | 1 文件 → 5 文件 | **depth=3** | **低** — 无集成测试 | ✅ 单 commit revert | 🔴 **HIGH** |
| **P1-17** 文件大小 | 元任务 — A1+A3 后自动解决 | | | | |

### HIGH 风险项特别预案

| 项 | 集成测试 | 回滚步骤 | 批次内优先级 |
|----|---------|---------|------------|
| P1-1 + P1-2 | 拆分后所有 `test_e2e_core.py` 28 项 + 新增 `test_react_core_split.py` 覆盖 6 个提取方法的独立调用路径 | `git revert <commit>` 回退到 2609 行单体 | **1st** — A1 中最先执行 |
| P1-10 | 拆分后新增 `test_chat_pipeline.py` 覆盖 @mention → model switch → session inject → agent run 全链路 | `git revert <commit>` | **2nd** — A2 优先 |

---

## 3. A1: `_run_body` 1470 行拆分 — 模块边界定义

### 3.1 当前结构诊断

[_run_body()](../agent/core.py#L519-L2043) 的 1524 行代码可划分为以下 12 个逻辑块：

```
Block 1 (lines 519-590):   Run context initialization
Block 2 (lines 590-810):   Setup: budget, controller, TSM, _finish_run (nested closure)
Block 3 (lines 812-920):   Pre-step checks: cancellation, circuit breaker, runtime ctl, TSM guard
Block 4 (lines 926-1014):  Pre-LLM trimming: Budget → Snip → Micro → AutoCompact
Block 5 (lines 1016-1071): Message assembly: _build_messages + spawn context capture
Block 6 (lines 1073-1191): LLM invocation: streaming dispatch or classic complete
Block 7 (lines 1198-1229): Recovery A: output truncation escalation + nudge
Block 8 (lines 1236-1341): Control plane: tool call validation, protocol normalization
Block 9 (lines 1341-1640): FINISH action: fact_check → verify_callback → stop_hook → completion_guard → TSM transition
Block 10 (lines 1648-1927): TOOL_CALL: batch dedup → streaming executor → observation processing → history injection
Block 11 (lines 1983-2024): Reflection triggers: test_failed, missing_test_target
Block 12 (lines 2030-2043): Post-loop: max_steps → _extract_summary_from_history → return
```

### 3.2 模块边界设计

```
agent/
├── core.py                          (~600 lines — ReActAgent class + run() + property accessors)
├── loop/
│   ├── __init__.py
│   ├── step_context.py              (Block 1+2: setup RunContext dataclass + _finish_run builder)
│   ├── pre_step.py                  (Block 3: cancellation → circuit breaker → runtime ctl → TSM guard)
│   ├── trimming.py                  (Block 4: 5-layer pre-LLM context trimming pipeline)
│   ├── message_assembly.py          (Block 5: _build_messages + spawn context)
│   ├── llm_invocation.py            (Block 6+7: LLM call dispatch + truncation recovery)
│   ├── control_plane.py             (Block 8: tool call validation, protocol normalization, error injection)
│   ├── finish_handler.py            (Block 9: fact_check → verify_callback → stop_hook → completion_guard)
│   ├── tool_executor.py             (Block 10: batch dedup → executor dispatch → observation → history)
│   └── reflection.py                (Block 11: test_failed + missing_test_target reflection triggers)
```

### 3.3 模块接口契约

每个提取的方法签名必须满足以下约束：

1. **纯输入**: 不通过 `self.` 访问可变状态，通过参数传递。
2. **纯输出**: 返回 `ContinueLoop | TerminateLoop` 枚举，调用方 decision。
3. **无副作用**: 不在方法内修改 `history`、`log`、`_state` —— 返回变更描述，由主循环 apply。

```python
# agent/loop/types.py (新文件 — 循环控制类型)

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core import RunResult
    from agent.task import Action, Observation, RunStatus
    from llm.base import LLMMessage
    from agent.session.task_state_machine import TerminationReason


class LoopAction(Enum):
    CONTINUE = auto()           # 进入下一轮迭代
    RETRY_WITH_COMPACT = auto() # compact 后重试 LLM 调用（不增加 step）
    RETURN = auto()             # 终止循环，返回 RunResult


@dataclass
class StepResult:
    """A single step's output — the main loop applies these mutations."""
    action: LoopAction
    # Only set when action == RETURN
    return_status: "RunStatus | None" = None
    return_result: "RunResult | None" = None
    # History mutations to apply (CONTINUE only)
    history_messages: list["LLMMessage"] = field(default_factory=list)
    observations: list["Observation"] = field(default_factory=list)
    # State transitions
    new_child_turn_phase: str | None = None
    step_increment: int = 1  # normally 1; 0 for retry-with-compact
    tokens_consumed: int = 0
```

### 3.4 方法签名

```python
# agent/loop/pre_step.py
def check_pre_step(
    step: int, task: "Task", state: "AgentTurnState",
    history: "ConversationHistory", tsm: "TaskStateMachine",
    total_tokens: int, cancellation: "CancellationToken",
    runtime_ctrl: "RuntimeController", budget: "ExecutionBudget",
    circuit_breaker: "CircuitBreaker",
    log: "EventLog",
) -> StepResult: ...

# agent/loop/trimming.py
def trim_context(
    step: int, history: "ConversationHistory", compactor: "ConversationCompactor",
    total_tokens: int, request_budget: int, compact_history: bool,
) -> int:  # returns tokens_freed
    ...

# agent/loop/finish_handler.py
def handle_finish(
    action: "Action", step: int, task: "Task", tsm: "TaskStateMachine",
    state: "AgentTurnState", history: "ConversationHistory",
    git_state: "_GitState", completion_ctx: "CompletionContext",
    fact_check: Callable | None, verify_callback: Callable | None,
    hook_dispatcher, log: "EventLog",
    total_tokens: int, cumulative_cache: "CacheStats",
    stop_hook_fn: Callable,
) -> StepResult: ...
```

### 3.5 主循环简化后形态

```python
# agent/core.py — ReActAgent._run_body (split target: ~200 lines)
def _run_body(self, task, log, *, policy):
    ctx = self._setup_run_context(task, log)  # Block 1+2
    state = AgentTurnState(turn_count=0)

    for step in range(1, task.max_steps + 1):
        # Pre-step
        pre_result = check_pre_step(step, task, state, ctx.history, ctx.tsm, ...)
        if pre_result.action == LoopAction.RETURN:
            return pre_result.return_result

        # Trimming
        trim_context(step, ctx.history, self.compactor, ...)

        # Message assembly + LLM call
        messages = self._build_messages(ctx.history, ...)
        action = self._invoke_llm(messages, tools, ...)  # includes recovery

        # Control plane
        control_result = self._check_control_plane(action, tools, ...)
        if control_result.needs_continue:
            continue

        # Dispatch by action type
        if action.action_type == ActionType.FINISH:
            finish_result = handle_finish(action, step, task, ctx.tsm, ...)
            if finish_result.action == LoopAction.RETURN:
                return finish_result.return_result
            elif finish_result.action == LoopAction.CONTINUE:
                continue

        if action.action_type == ActionType.TOOL_CALL:
            tool_result = execute_tool_batch(action, step, ctx, ...)
            if tool_result.action == LoopAction.RETURN:
                return tool_result.return_result
            # Apply observations + check reflection
            ...

    return ctx.make_max_steps_result()
```

### 3.6 测试方案

```
T-A1-1: _setup_run_context 独立调用 → 返回完整 RunContext dataclass
T-A1-2: check_pre_step 输入各种状态 → 返回 CONTINUE / RETURN + 正确 return_result
T-A1-3: trim_context 标准 → 返回 tokens_freed >= 0
T-A1-4: handle_finish 正常完成 → RETURN(SUCCESS) + patch 非空
T-A1-5: handle_finish fact_check blocking → CONTINUE（注入 feedback）
T-A1-6: handle_finish 3 次 blocking → RETURN(GAVE_UP)
T-A1-7: execute_tool_batch 正常 → CONTINUE + observations
T-A1-8: execute_tool_batch ENVIRONMENT_UNAVAILABLE → RETURN(BLOCKED)
T-A1-9: 完整 _run_body 回归 — 所有 test_e2e_core 通过
```

---

## 4. A2: `run_chat_async` 重构 — 接口契约

### 4.1 当前结构

```
run_chat_async() (lines 544-794):
  ├── _resolve_mentions(prompt)        — 嵌套函数
  ├── _run_and_notify()                 — 嵌套函数 (~120 lines)
  │   ├── _maybe_reload_rules()
  │   ├── _resolve_mentions(prompt)
  │   ├── pop_pending_model()           → backend switch
  │   ├── pop_pending_effort/thinking/permission_mode
  │   ├── _inject_session_context()
  │   ├── _build_web_confirm_callback()
  │   ├── build stream_callback
  │   ├── _runtime.run_session()
  │   └── event_bus push (plan_ready | completed | failed)
  └── threading.Thread(target=_run_and_notify)
```

### 4.2 目标架构 — ChatPipeline

```
server/services/
├── agent_service.py                   (AgentService — 保留配置/注册/生命周期管理)
├── chat_pipeline.py                   (新文件 — 管道编排)
│   ├── class ChatPipeline
│   │   ├── resolve_mentions(text) → str
│   │   ├── apply_model_switch(session_id) → LLMBackend | None
│   │   ├── inject_context(session_id) → bool
│   │   ├── build_callbacks(session_id) → (ConfirmCB, StreamCB)
│   │   └── execute(session_id, ...) → RunResult
│   └── def run_in_background(pipeline, ...) → None
```

### 4.3 接口契约

```python
# server/services/chat_pipeline.py

from dataclasses import dataclass
from typing import Callable

@dataclass
class ChatExecutionContext:
    """All data needed for one chat run — immutable, per-invocation."""
    session_id: str
    prompt: str
    agent_name: str
    intent: "TaskIntent | None"
    permission_mode: str
    # Resolved
    resolved_prompt: str = ""
    # Callbacks (set by build_callbacks)
    confirm_callback: Callable | None = None
    stream_callback: Callable | None = None


class ChatPipeline:
    """Orchestrates a single chat execution.

    Replaces the nested _run_and_notify() in AgentService.run_chat_async().
    Each step is a pure method that reads from / writes to ChatExecutionContext.
    """

    def __init__(self, service: "AgentService") -> None:
        self._service = service

    def resolve_mentions(self, ctx: ChatExecutionContext) -> None:
        """Scan @path references in prompt → resolved_prompt."""
        ...

    def apply_model_switch(self, ctx: ChatExecutionContext) -> "LLMBackend | None":
        """Pop pending model, create per-session backend. Returns new backend."""
        ...

    def inject_session_context(self, ctx: ChatExecutionContext) -> None:
        """Inject previous session summary once per root session."""
        ...

    def build_callbacks(self, ctx: ChatExecutionContext) -> None:
        """Create web_confirm_callback + stream_callback."""
        ...

    def execute(self, ctx: ChatExecutionContext, backend: "LLMBackend") -> "RunResult":
        """Run the agent via SessionRuntime.run_session()."""
        ...

    @staticmethod
    def run_in_background(pipeline: "ChatPipeline", ctx: ChatExecutionContext) -> None:
        """Spawn a daemon thread and run the pipeline steps."""
        ...
```

### 4.4 AgentService.run_chat_async 简化后

```python
# server/services/agent_service.py
def run_chat_async(self, session_id, prompt, agent_name="build", intent=None):
    if not self._runtime.try_acquire_session(session_id):
        raise RuntimeError(f"Session {session_id} is already running")

    pipeline = ChatPipeline(self)
    ctx = ChatExecutionContext(
        session_id=session_id, prompt=prompt,
        agent_name=agent_name, intent=intent,
        permission_mode="acceptEdits",
    )
    ChatPipeline.run_in_background(pipeline, ctx)
```

### 4.5 测试方案

```
T-A2-1: ChatPipeline.resolve_mentions("@agent/core.py") → 文件内容注入
T-A2-2: ChatPipeline.resolve_mentions("@../../../.env") → 不展开（DENY_PREFIXES）
T-A2-3: ChatPipeline.apply_model_switch 无 pending → None
T-A2-4: ChatPipeline.apply_model_switch pending → 返回新 backend
T-A2-5: ChatPipeline.inject_session_context 第一次 → True + 消息注入
T-A2-6: ChatPipeline.inject_session_context 第二次 → False（幂等）
T-A2-7: ChatPipeline.execute → RunResult.SUCCESS
T-A2-8: run_in_background daemon thread → result 推送 WS
T-A2-9: AgentService.run_chat_async 并发 —— 第二个调用抛出 409
```

---

## 5. A3: core.py 魔数清理 — 配置化方案

### 5.1 魔数清单

| 行号 | 当前值 | 语义 | 配置化名称 |
|------|--------|------|-----------|
| 708 | `3000` | Git diff 摘要截断长度 | `DIFF_PREVIEW_MAX_CHARS` |
| 948 | `200_000` | 预算 total fallback | `DEFAULT_REQUEST_BUDGET_TOKENS` |
| 950 | `80` | 预算 warning 百分比 | `BUDGET_WARNING_PCT` |
| 966 | `100` | 预算 auto-compact 百分比 | `BUDGET_COMPACT_PCT` |
| 1008 | `110_000` | history budget fallback | `DEFAULT_HISTORY_BUDGET_TOKENS` |
| 1203,1210,1213 | `32000` | 默认 max_tokens | `DEFAULT_MAX_OUTPUT_TOKENS` |
| 1203 | `100` | 截断缓冲 | `TRUNCATION_BUFFER_TOKENS` |
| 1310 | `20` | 最近文件窗口数 | `RECENT_FILES_WINDOW` |
| 1477 | `3` | 完成阻塞阀值 | `COMPLETION_BLOCK_THRESHOLD` |
| 1874 | `"(no thought)"` | 哨兵字符串 | `NO_THOUGHT_SENTINEL` |
| 1949 | `3` | 反射 test_failed limit | `TEST_FAILURE_REFLECTION_LIMIT` |
| 1999 | `20` | Session memory 消息窗口 | `SESSION_MEMORY_MSG_WINDOW` |
| 2003,2147,2161 | `2000` | 摘要截断字符 | `SUMMARY_TRUNCATION_CHARS` |
| 2155 | `500` | Tool content 截断 | `TOOL_EXTRACT_CHARS` |
| 2156 | `5` | 最大 tool results 提取数 | `MAX_TOOL_RESULTS_EXTRACT` |
| 2256 | `200` | Finding 描述截断 | `FINDING_DESC_CHARS` |
| 2257 | `10` | 恢复后最多 N 个 findings | `RECOVERY_MAX_FINDINGS` |
| 2456 | `8000` | 默认截断输出 chars | `DEFAULT_TRUNCATE_OUTPUT_CHARS` |

### 5.2 配置化方案

```python
# agent/constants.py (新文件)

# ── Budget thresholds ─────────────────────────────────────────────
DEFAULT_REQUEST_BUDGET_TOKENS: int = 200_000
DEFAULT_HISTORY_BUDGET_TOKENS: int = 110_000
DEFAULT_MAX_OUTPUT_TOKENS: int = 32_000
TRUNCATION_BUFFER_TOKENS: int = 100

# ── Budget monitoring ─────────────────────────────────────────────
BUDGET_WARNING_PCT: int = 80
BUDGET_COMPACT_PCT: int = 100

# ── Display truncation ────────────────────────────────────────────
DIFF_PREVIEW_MAX_CHARS: int = 3_000
SUMMARY_TRUNCATION_CHARS: int = 2_000
TOOL_EXTRACT_CHARS: int = 500
FINDING_DESC_CHARS: int = 200
DEFAULT_TRUNCATE_OUTPUT_CHARS: int = 8_000

# ── Loop control ──────────────────────────────────────────────────
COMPLETION_BLOCK_THRESHOLD: int = 3
TEST_FAILURE_REFLECTION_LIMIT: int = 3
RECENT_FILES_WINDOW: int = 20
SESSION_MEMORY_MSG_WINDOW: int = 20
RECOVERY_MAX_FINDINGS: int = 10
MAX_TOOL_RESULTS_EXTRACT: int = 5

# ── Sentinels ─────────────────────────────────────────────────────
NO_THOUGHT_SENTINEL: str = "(no thought)"
```

agent/core.py 中的引用替换为：

```diff
-                        f"\n{_git_state.current_diff[:3000]}"
+                        f"\n{_git_state.current_diff[:DIFF_PREVIEW_MAX_CHARS]}"

-                        _budget_total = self._cfg.request_budget_tokens or 200_000
+                        _budget_total = self._cfg.request_budget_tokens or DEFAULT_REQUEST_BUDGET_TOKENS

-                        max_tokens", 32000) - 100
+                        max_tokens", DEFAULT_MAX_OUTPUT_TOKENS) - TRUNCATION_BUFFER_TOKENS
```

### 5.3 测试方案

```
T-A3-1: 所有魔数替换后 test_e2e_core 28 项全绿
T-A3-2: constants.py 中每个常量都有对应的 import + 使用点（grep 验证原始魔数不再存在于 core.py）
```

---

## 6. Architecture Compliance Check 维度

> **Phase 5 新增验证维度**——每次重构后除功能回归外，必须验证：

| 维度 | 测量方法 | 通过标准 | 验证工具 |
|------|---------|---------|---------|
| **模块边界清晰度** | `grep -c "import" agent/loop/*.py` 检查循环依赖 | 无 circular import；每个模块导入 ≤ 5 个同级模块 | `pytest --import-mode=importlib` |
| **依赖方向正确性** | `agent/loop/` 不可导入 `server/`；`server/services/` 不可导入 `agent/loop/` | 零违反 | grep + 手工审查 |
| **配置外部化程度** | `agent/constants.py` 定义 vs `agent/core.py` 内联数字 | 100% — core.py 中无魔数 | grep `\d+` 扫描 |
| **接口契约稳定性** | 提取的方法签名是否在拆分后仍可独立测试 | 每个方法 ≥ 1 个单元测试 | pytest coverage report |
| **调用链深度降级** | `_run_body` 的嵌套深度 | 拆分后主循环体 ≤ 200 行，最深嵌套 ≤ 3 层 | `flake8 --max-complexity=10` |

---

## 7. VESP Phase 5 升级

### Phase 5 专属 Matrix 列

在原 VESP Matrix 基础上新增 "Architecture Compliance" 列：

| 验证项 | 环境 | 验证类型 | Architecture Compliance |
|--------|------|---------|------------------------|
| A1 `_run_body` 拆分 | unit | 功能回归 | ① import 无循环 ② 每个模块 ≤ 200 行 ③ 主循环嵌套 ≤ 3 |
| A2 ChatPipeline | unit | 功能回归 | ① agent_service 不导入 agent/loop ② ChatPipeline 无 agent/ 依赖 |
| A3 配置化 | unit | 功能回归 | ① core.py 零裸魔数 ② constants.py 文档完整 |

### 升级条款

1. **ACC-1**: 架构重构后 `pytest --import-mode=importlib` 必须通过（禁止隐式相对导入）。
2. **ACC-2**: 每个提取的模块必须有 ≥ 1 个独立单元测试（不通过 ReActAgent 间接调用）。
3. **ACC-3**: 魔数清理后 `grep -nE '\b(3000|8000|2000|32000|20|3|200|10|5)\b' agent/core.py | grep -v '^.*#'` 返回 0 行。

---

## 8. Phase 5 Readiness Checklist

| # | 条件 | 状态 |
|---|------|------|
| ① | Phase 4 关闭检查清单 5/5 ✅ | ✅ |
| ② | 11 项 deferred P1 已映射到 Batch A (A1:7, A2:1, A3:3) | ✅ |
| ③ | Refactoring Risk Matrix 已完成（2 HIGH, 2 LOW, 6 NEGLIGIBLE） | ✅ |
| ④ | VESP 升级条款已编码（ACC-1/2/3） | ✅ |
| **→ Phase 5 Ready** | | ✅ |

---

## 9. 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **输入基线** | CORE_ARCHITECTURE_REPORT.md + Phase 4 deferred P1 ×11 |
| **Phase 5 Batch A 范围** | A1(`_run_body` 拆分 7 项 P1), A2(`run_chat_async` 重构), A3(配置化 3 项) |
| **RISK MATRIX** | 2 HIGH (P1-1/2, P1-10), 7 LOW/NEGLIGIBLE |
| **VESP 升级** | ACC-1 导入合规, ACC-2 模块单元测试, ACC-3 零裸魔数 |
| **下一阶段** | Phase 5 Batch A 执行 → Phase 5 Batch B (剩余 P2 项) |
