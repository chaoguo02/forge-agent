# 内容关联度深度分析

> 本分析识别目录内容与实际职责的错配，按问题严重程度排序。

---

## 问题 1: `executor/` 身份丢失

### 现状

```
executor/
  __init__.py       — 从 agent.mcp 导入 + 废弃的 tool 类型
  process.py        — LocalRuntime（进程执行）
  goal.py           — 目标/Goal 管理
  snapshot.py       — Worktree 管理、git 快照
  workspace_facts.py— 工作区状态捕获
  state_paths.py    — 项目状态路径
  project_environment.py — 环境检测
  tool.py           — 旧的工具类型定义（大部分已废弃）
  process_invoker.py— 进程调用器
  sibling_abort.py  — 兄弟进程中止
```

### 问题

`executor/` 名字的含义是"执行器"，但移动 MCP 后剩下的内容与"执行"关系不大：

| 文件 | 实际职责 | 应属目录 |
|------|---------|---------|
| `snapshot.py` | Worktree 管理 | `agent/session/`（与 worktree_service, worktree_tool 同组） |
| `workspace_facts.py` | 工作区状态 | `core/` 或 `context/` |
| `goal.py` | Goal/目标管理 | `core/`（被 agent/core.py 使用） |
| `state_paths.py` | 路径管理 | `core/` |
| `project_environment.py` | 环境检测 | `core/` |
| `process.py` | 进程执行 | `core/`（与 shell 执行相关） |
| `tool.py` | 废弃 | 删除 |
| `process_invoker.py` | 进程调用 | `core/` |
| `sibling_abort.py` | 中止 | `core/` |

### 建议

**解散 `executor/` 目录**，将其内容分散到正确的目录：

```
executor/process.py       →  core/process.py  (LocalRuntime)
executor/snapshot.py      →  agent/session/worktree.py  (与 worktree_service 合并)
executor/workspace_facts.py → context/workspace_facts.py
executor/goal.py          →  core/goal.py
executor/state_paths.py   →  core/state_paths.py
executor/project_environment.py → core/project_environment.py
executor/sibling_abort.py →  core/sibling_abort.py
executor/tool.py          →  删除（已废弃）
executor/process_invoker.py → core/process_invoker.py
executor/__init__.py      →  删除
```

---

## 问题 2: `agent/prompt.py` vs `prompts/` 目录重复

### 现状

```
agent/prompt.py       (284 行) — build_system_prompt(), render_prompt(),
                                  模板缓存、用量追踪
prompts/assembler.py  (319 行) — PromptAssembler 类
prompts/*.md           (4 个) — Markdown 提示模板
```

### 问题

两个文件都在做同一件事：组装 system prompt。但一个在 `agent/`，一个在 `prompts/`。`agent/prompt.py` 是比 `prompts/assembler.py` 更早的实现，两者功能重叠。

`agent/prompt.py` 中的关键函数：
- `build_system_prompt_core()` — 构建核心 system prompt
- `build_system_prompt_variable()` — 构建可变部分
- `build_system_prompt()` — 完整 prompt
- `_render_prompt()` — 模板渲染
- 用量追踪函数

`prompts/assembler.py` 中的关键功能：
- `PromptAssembler` 类
- `_LangfusePromptProvider` — Langfuse 集成

### 建议

将 `agent/prompt.py` 的工具函数合并到 `prompts/` 目录：

```
agent/prompt.py → 拆分为两个文件移到 prompts/:
  prompts/builder.py     — build_system_prompt_core(), build_system_prompt_variable()
  prompts/usage.py       — 用量追踪 (record/consume/reset)
  prompts/assembler.py   — 保留现有 + 合并模板渲染
```

---

## 问题 3: `agent/core.py` 和 `core/base.py` 膨胀

### `agent/core.py` (2909 行)

包含：
1. **类型定义** (250 行): AgentConfig、_ChildTurnPhase、_TaskNotificationFacts、RecoveryState、Transition
2. **工具函数** (200 行): _task_notification_facts_from_result、_snip_history、_apply_tool_result_budget、_apply_context_collapse、_micro_compact
3. **ReActAgent 类** (2400+ 行): run、_run_body、消息构建、工具执行、状态管理

### `core/base.py` (1074 行)

包含 6 个独立模块：
1. Observation 相关 (50 行)
2. Action 相关 (80 行)
3. RiskLevel/Effect/Concurrency (60 行)
4. ToolMetadata/Role/Dependency (80 行)
5. ToolError 系 (70 行)
6. ToolResult + BaseTool + ToolRegistry (700+ 行)

### 建议

拆分 `core/base.py`：
```
core/base.py           — 仅保留 BaseTool、ToolRegistry（核心基类）
core/types.py          — Observation、Action、ToolCall、LLMToolSchema、ToolResult 等
core/errors.py         — ToolError、ToolRetryDirective
```

拆分 `agent/core.py`：
```
agent/agent_config.py  — AgentConfig 定义
agent/recovery.py      — RecoveryState、Transition
agent/agent_loop.py    — ReActAgent 主循环（从 agent/core.py 抽取）
agent/message_builder.py — _build_messages、build_runtime_messages
```

---

## 问题 4: `memory/store.py` (1145 行)

包含：
1. 文件 CRUD (300 行)
2. MEMORY.md 索引管理 (100 行)
3. 生命周期 (deprecate/archive/prune) (200 行)
4. 合并去重 (consolidate) (200 行)
5. 上下文注入 (get_index_content) (50 行)
6. TwoTierMemoryStore (150 行)

### 建议

拆分：
```
memory/store.py          — 纯 CRUD（read/write/delete）
memory/index.py          — MEMORY.md 索引管理（原来在 store.py 中）
memory/lifecycle.py      — deprecate、archive、prune、validate
memory/consolidation.py  — 合并去重（已有，但 consolidate() 方法仍在 store.py 中）
```

---

## 问题 5: `agent/session/runtime.py` (1715 行)

包含：
1. run_session() 主入口 (150 行)
2. 子消息拉取 (_claim_completion_messages) (100 行)
3. spawn_agent() 子代理 (200 行)
4. _execute_child_session() 子代理执行 (200 行)
5. 会话完成检查 (_check_session_completion) (150 行)
6. 辅助方法 (其他)

### 建议

```
agent/session/runtime.py           — run_session() 核心逻辑（精简）
agent/session/runtime_spawn.py     — spawn_agent() + _execute_child_session()
agent/session/runtime_completion.py — _check_session_completion()
```

---

## 实施顺序

| 优先级 | 改动 | 工作量 | 风险 |
|--------|------|--------|------|
| P0 | `executor/` 解散（5 个文件移到 core/，2 个移到其他） | 大 | 中（大量 import 需更新） |
| P1 | `core/base.py` 拆 `core/types.py` + `core/errors.py` | 中 | 低（纯搬移） |
| P1 | `memory/store.py` 拆 `memory/index.py` | 中 | 低 |
| P2 | `agent/core.py` 拆出 `agent/agent_config.py` | 小 | 低 |
| P2 | `agent/prompt.py` 合并到 `prompts/` | 中 | 低 |
| P3 | `agent/session/runtime.py` 拆 runtime_spawn | 中 | 中 |
| P3 | `agent/core.py` 拆 agent_loop | 大 | 高（核心逻辑，容易引入 bug） |
