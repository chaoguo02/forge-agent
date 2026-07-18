# Analysis: `entry/` vs `agent/` 目录结构对比

> 日期: 2025-01  |  项目: forge-agent

---

## 1. 总体概览

| 指标               | `entry/`              | `agent/`              | 差异 |
|--------------------|-----------------------|-----------------------|------|
| .py 文件数         | 19                    | 33                    | agent 是 entry 的 1.7 倍 |
| 总代码行数         | ~5,529                | ~13,304               | agent 是 entry 的 2.4 倍 |
| 总大小 (KB)        | ~205.8                | ~531.8                | agent 是 entry 的 2.6 倍 |
| 平均文件大小 (行)  | ~291                  | ~403                  | agent 文件平均更大 |
| 公有符号 (类+函数) | 48 (11 类 + 37 函数)  | ~160 (100+ 类 + 50+ 函数) | agent 更面向对象 |
| 子包数量           | 3 (bootstrap, chat_services, modes) | 2 (session, v2) | 扁平 vs 分层 |
| 根 `__init__.py`   | ❌ 缺失               | ✅ 存在               | **关键差异** |

---

## 2. 文件大小分布对比

### entry/ — 前 5 大文件

| 排名 | 文件                              | 行数   | KB   | 占比   |
|------|-----------------------------------|--------|------|--------|
| 1    | `cli.py`                          | 1,398  | 55.9 | 25.3%  |
| 2    | `renderer.py`                     | 934    | 34.2 | 16.9%  |
| 3    | `chat.py`                         | 861    | 31.6 | 15.6%  |
| 4    | `modes/v2_runner.py`              | 679    | 24.6 | 12.3%  |
| 5    | `github_issue.py`                 | 374    | 11.3 | 5.5%   |
|      | **前 3 合计**                     | 3,193  |      | **57.8%** |

**特点**: 前 3 个文件占整个包近 60% 的代码，呈现 **"top-heavy"** 分布。
`cli.py` 一个文件就超过 1,300 行 —— 混合了 CLI 入口、MCP 命令组、日志管理、历史记录等功能。

### agent/ — 前 5 大文件

| 排名 | 文件                              | 行数   | KB   | 占比   |
|------|-----------------------------------|--------|------|--------|
| 1    | `core.py`                         | 2,841  | 129.1| 21.4%  |
| 2    | `session/runtime.py`              | 1,701  | 70.9 | 12.8%  |
| 3    | `session/models.py`               | 1,063  | 37.8 | 8.0%   |
| 4    | `session/task_tool.py`            | 790    | 30.6 | 5.9%   |
| 5    | `session/subagent.py`             | 563    | 20.7 | 4.2%   |
|      | **前 3 合计**                     | 5,605  |      | **42.2%** |

**特点**: 虽然也有大文件 (`core.py` 2,841 行)，但前 3 占比仅 42%，其余文件分散在
`session/` (21 个文件) 中，呈现 **分层模块化** 结构。

---

## 3. 包结构完整性

### entry/ (隐式命名空间包 ⚠️)

```
entry/
├── ❌ __init__.py        ← 缺失！
├── _terminal.py
├── bootstrap/
│   ├── __init__.py       ← ✅
│   ├── hook_bootstrap.py
│   ├── memory_bootstrap.py
│   └── registry_factory.py
├── chat.py
├── chat_services/
│   ├── __init__.py       ← ✅
│   └── agent_session_factory.py
├── cli.py
├── display.py
├── github_issue.py
├── history_viewer.py
├── modes/
│   ├── __init__.py       ← ✅
│   ├── interaction.py
│   ├── plan_approval.py
│   ├── plan_contract.py
│   └── v2_runner.py
├── renderer.py
└── worktree_admin.py
```

**问题**: 根目录缺少 `__init__.py`，entry/ 是一个隐式命名空间包。
在某些打包工具或特定路径执行时可能导致导入失败。

### agent/ (正规包 ✅)

```
agent/
├── ✅ __init__.py            ← 存在
├── capability_registry.py
├── completion_guard.py
├── core.py
├── event_log.py
├── mode_switching.py
├── observation_rendering.py
├── prompt.py
├── run_finalizer.py
├── runtime_controller.py
├── task.py
├── session/
│   ├── __init__.py           ← ✅
│   ├── agent_control_tool.py
│   ├── agent_definition.py
│   ├── agent_factory.py
│   ├── agent_registry.py
│   ├── execution_budget.py
│   ├── mcp_integration.py
│   ├── models.py
│   ├── registry_builder.py
│   ├── result_contract.py
│   ├── run_context.py
│   ├── runtime.py
│   ├── runtime_prompt_builder.py
│   ├── session_store.py
│   ├── subagent.py
│   ├── subagent_registry_factory.py
│   ├── task_contract.py
│   ├── task_state_machine.py
│   ├── task_tool.py
│   ├── worktree_service.py
│   └── worktree_tool.py
├── v2/
│   ├── __init__.py           ← ✅ (但仅 2 行，似乎是遗留空包)
│   └── (无其他文件)
```

**特点**: 所有子包都有 `__init__.py`，包结构完整。
`session/` 下有 21 个文件，实现了高度模块化。

---

## 4. 导入依赖关系

```
┌─────────────────────────────────────────────────┐
│                    entry/                        │
│  cli.py, chat.py, github_issue.py               │
│  worktree_admin.py, modes/v2_runner.py          │
│       │                                          │
│       │  import agent.prompt                    │
│       │  import agent.task                      │
│       │  import agent.core                      │
│       │  import agent.session.*                 │
│       │  import agent.event_log                 │
│       ▼                                          │
├─────────────────────────────────────────────────┤
│                    agent/                        │
│  core.py, prompt.py, task.py, session/*         │
│       │                                          │
│       │  (只有一处反向导入)                      │
│       ▼                                          │
│  observation_rendering.py → entry.display       │
└─────────────────────────────────────────────────┘
```

### 结论:
- **干净的单向依赖**: `entry/ → agent/` ✅
- **唯一的例外**: `agent/observation_rendering.py → entry.display`（导入 `INLINE_EFFECTS`）
- 这是良好的架构分层 —— `entry/` 是用户界面层，`agent/` 是业务逻辑层

---

## 5. 公有符号风格对比

| 特性          | `entry/`                      | `agent/`                       |
|---------------|-------------------------------|--------------------------------|
| 类/函数比例   | 11 类 / 37 函数 (0.3)        | 100+ 类 / 50+ 函数 (~2)        |
| 编码范式      | **函数式为主**                | **面向对象为主**                |
| 命名约定      | 自由函数 (cli.py 无类)        | 大量使用 dataclass / frozen dataclass |
| 典型导出      | `def run(...)`, `def cli(...)` | `class SessionRuntime`, `class AgentDefinition` |

### entry/ 公有符号分布:
```
cli.py                  19 函数 (无类)
github_issue.py          7 函数
modes/interaction.py     6 类 + 1 函数
renderer.py              2 类 + 4 函数
```

### agent/ 公有符号分布:
```
session/models.py        36 类 (大量 dataclass)
prompt.py                19 函数
task.py                  15 类
session/worktree_service.py 3 类 + 8 函数
session/task_state_machine.py 5 类 + 6 函数
core.py                   7 类
```

---

## 6. 测试覆盖率对比

| 测试文件                           | 测试函数数 | 覆盖对象            |
|------------------------------------|-----------|---------------------|
| `test_v2_runtime.py`               | 159       | agent/session/runtime.py 等 |
| `test_skills_alignment.py`         | 40        | agent/ 技能系统     |
| `test_v2_worktree_isolation.py`    | 13        | agent/session/worktree* |
| `test_cc_alignment_features.py`    | 2 (?)     | agent/ 对齐特性     |
| `test_cli_v2_orchestration.py`     | 9         | entry/cli.py V2 流程 |
| `test_plan_approval.py`            | 17        | entry/modes/plan_*  |

### 关键发现:
- **`agent/` 覆盖率高**: 仅 `test_v2_runtime.py` 就有 159 个测试
- **`entry/` 覆盖率低**: `cli.py` (1,398 行) 仅有 9 个集成测试
- **`renderer.py` (934 行) 和 `chat.py` (861 行)** 几乎没有直接单元测试
- 总共 387 个测试函数，但 `entry/` 相关不到 30 个 (约 7.7%)

---

## 7. 代码质量与维护性问题

### entry/ 的主要问题

| 问题 | 严重度 | 描述 |
|------|--------|------|
| 缺少 `__init__.py` | **P0** | 隐式命名空间包，可能导致打包/导入问题 |
| `cli.py` 过大 | **P0** | 1,398 行，混合 CLI 入口、MCP 命令、日志、历史管理 |
| `renderer.py` 过大 | **P1** | 934 行，混合显示、HITL 回调、权限确认 |
| `chat.py` 过大 | **P1** | 861 行，缺少模块拆分 |
| 测试覆盖率低 | **P1** | 大型 UI 模块缺少直接单元测试 |
| `interaction.py` 重复定义 | **P2** | 内联 `_bold`/`_dim`，未从 `_terminal.py` 导入 |

### agent/ 的主要问题

| 问题 | 严重度 | 描述 |
|------|--------|------|
| `core.py` 过大 | **P1** | 2,841 行 (132 KB)，包含 ReActAgent 核心循环 |
| `session/runtime.py` 过大 | **P1** | 1,701 行，需分离生命周期/守卫/阶段/恢复 |
| `session/models.py` 过大 | **P2** | 1,063 行，可拆分为多个模型文件 |
| 导入风格不统一 | **P2** | 部分用 `from agent.session import ...`，部分用完整路径 |

---

## 8. 总结: 核心差异

| 维度               | `entry/`                          | `agent/`                          |
|--------------------|-----------------------------------|-----------------------------------|
| 角色               | 用户界面/CLI 层                   | 业务逻辑/核心引擎                 |
| 包类型             | 隐式命名空间包 (缺 `__init__.py`) | 正规包                            |
| 架构风格           | 扁平 + 文件累积                   | 模块化 + 单一职责                 |
| 编码范式           | 函数式                            | 面向对象 (dataclass 驱动的领域模型) |
| 文件分布           | 3 个大文件占 60% (top-heavy)      | session/ 下 21 个文件 (分层)      |
| 依赖方向           | 仅导入 agent                      | 不依赖 entry (除一处例外)         |
| 测试覆盖           | 弱 (仅 ~30 个测试)                | 强 (test_v2_runtime.py 159 个测试) |
| 拆包优先级         | P0: 加 __init__.py, 拆分 cli.py  | P1: 拆分 core.py, runtime.py      |

### 建议行动项

1. **P0**: 添加 `entry/__init__.py`
2. **P0**: 拆分 `entry/cli.py` → `entry/mcp_cli.py`, `entry/log_cli.py`, `entry/history_cli.py`
3. **P1**: 拆分 `entry/renderer.py` → 分离 HITL 交互到 `entry/modes/interaction.py`
4. **P1**: 拆分 `agent/core.py` 中的大方法
5. **P1**: 拆分 `agent/session/runtime.py` → 生命周期/守卫/阶段/恢复模块
6. **P1**: 为 `entry/renderer.py` 和 `entry/chat.py` 补充单元测试
7. **P2**: 统一 `agent/session/` 导入风格
