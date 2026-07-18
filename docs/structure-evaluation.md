# 项目结构评估

> 评分维度：S/A/B/C/D（S=优秀, A=良好, B=合格, C=需改进, D=问题严重）

---

## 一、整体架构评分

### 1. 目录解耦度：A-

**优点**：
- 分层清晰：`entry/`（入口）→ `agent/`（逻辑）→ `core/`（基础）→ `tools/`（工具）
- `tools/` 不依赖 `agent/`，只依赖 `core/` 和 `context/` ✅
- `memory/` 基本独立，通过 `injection_service.py` 一个入口对外暴露 ✅

**问题**：
- `core/base.py` 反向依赖 `agent/task.py`（`core/base.py:8` 导入 `Observation`、`ObservationStatus`、`ToolOutcome`）。核心层不应该知道 agent 层的存在
- `core/policy.py` 也依赖 `agent/task.py`（导入 `Task`, `TaskIntent`）
- `agent/v2/` 仅 1 个 `__init__.py` 做兼容重导出，代码体积 ~50 行，属于过渡残留

### 2. 内容关联度：B+

**分析**：

| 目录 | 文件数 | 核心职责 | 评价 |
|------|--------|---------|------|
| `agent/` | 11 | ReAct 主循环 + 任务模型 | ✅ 聚焦 |
| `agent/session/` | 21 | Runtime + Registry + 子代理 | ⚠️ 过大，含 AgentFactory、Runtime、Registry、TaskContract 等，逻辑关系紧密但文件量偏高 |
| `context/` | 12 | 历史管理 + 压缩 + token 预算 | ✅ 聚焦 |
| `core/` | 8 | 基础类型 + 策略 + 执行器 | ⚠️ `core/base.py` 含工具注册、权限、类型定义，功能杂 |
| `entry/` | 8 + 3子目录 | CLI + Chat + 服务 | ⚠️ 碎片化：`entry/modes/`、`entry/chat_services/`、`entry/bootstrap/` 各 2-5 个文件 |
| `memory/` | 17 | 记忆存储 + 检索 + 提取 | ⚠️ 偏大，`store.py`（1046行）+ `context.py`（435行）占大头 |
| `tools/` | 17 | 工具定义 | ✅ 每个工具一个文件，结构清晰 |
| `executor/` | 10 + 子目录 | 进程 + MCP | ⚠️ `executor/mcp/` 将 MCP 放在 executor 下，MCP 更偏向 agent 通信层 |

### 3. 结构合理度：B+

**存在问题**：

**问题 1: `agent/v2/` 过渡目录**
```python
# agent/v2/__init__.py — 仅做重导出的兼容层
from agent.session.models import AgentDefinition, AgentKind, ...
from agent.session.runtime import SessionRuntime
from agent.session.session_store import SessionStore
```
这个目录的存在是因为重构时留了过渡路径。现在所有代码都走 `agent/session/`，兼容层可以不维护了。

**问题 2: `executor/mcp/` 位置不当**
```
executor/
  process.py       — 进程执行（Runtime）
  mcp/             — MCP 服务器连接管理
```
MCP 是 agent 的工具扩展机制，放在 `executor/` 下语义不对。应放到 `agent/mcp/` 或 `mcp/`。

**问题 3: `entry/` 拆分过细**
```
entry/
  cli.py           — CLI 入口 (600+ 行)
  chat.py          — Chat 模式 (450+ 行)
  renderer.py      — 渲染器
  modes/           — v2_runner.py + interaction.py (各 400+ 500+ 行)
  chat_services/   — 2 个文件
  bootstrap/       — hook_bootstrap.py 等
```
`entry/` 有 3 个子目录但只有 5-8 个源文件。`chat_services/` 只有 2 个文件，可以合并到 `entry/`。

**问题 4: `_test_project/` 地位模糊**
```
_test_project/
  .forge-agent/     — V2 session DB、artifacts
  src/auth/
  src/middleware/
  src/utils/
  .git/             — 独立 git 仓库
```
这看起来是一个测试用的迷你项目（14 个 .py 文件），测试框架会用到它。但文件散落在根目录，容易被误认为生产模块。

**问题 5: `mcp_servers/` 只有 1 个文件**
```
mcp_servers/
  echo_server.py
```
如果只有一个示例 MCP 服务器，可以合并到 `docs/` 示例或 `scripts/` 中。

**问题 6: `.forge-agent/agents/` 只有 2 个文件**
```
.forge-agent/agents/
  code-review.md
  general.md
```
项目级 agent 定义放这里。但内置 agent 定义在 `agent/session/models.py` 中。两份源容易不同步。

### 4. 可维护性：B

| 指标 | 值 | 评价 |
|------|-----|------|
| 总源文件 | ~140 .py | 适中 |
| 最大文件 | `agent/session/runtime.py` | 应该拆分 |
| 最大目录 | `agent/session/` 21 文件 | 接近需要拆分的阈值 |
| 测试文件 | 44 | 偏高，部分可能是无效用例 |
| `__pycache__` 残留 | 多个 | 已部分清理 |
| 根目录松散文件 | ~1 | ✅ 干净 |

### 5. 测试质量：B-

| 方面 | 评价 |
|------|------|
| 测试覆盖率 | 核心功能有覆盖，但分布不均 |
| 测试目录 | `tests/eval/` 已删除，但 `tests/manual/` 有 5 个 .md 描述文件（未转化为自动化测试） |
| `tests/test_v2_runtime.py` | ~4700 行，严重过大，测试函数命名不一致 |
| `tests/test_runtime_mcp*.py` | 6 个测试文件测试 MCP，内容重复度高 |

---

## 二、目录分项评分

| 目录 | 解耦度 | 内聚度 | 结构合理度 | 可维护性 | 总体 |
|------|--------|--------|-----------|---------|------|
| `agent/` (核心) | A | B+ | B+ | B | B+ |
| `agent/session/` | A | A | B | B- | B+ |
| `core/` | C+ | B+ | A | B+ | B |
| `context/` | A | A | A | A | A |
| `tools/` | A | A | A | A | A |
| `memory/` | A | A | B+ | B | A- |
| `entry/` | A | C+ | C | C+ | C+ |
| `executor/` | B+ | B | C+ | B | B |
| `hooks/` | A | A | A | A | A |
| `hitl/` | A | B+ | A | B+ | A- |
| `llm/` | A | A | A | A | A |
| `config/` | A | A | A | A | A |
| `observability/` | A | B+ | A | B | B+ |

---

## 三、关键问题优先级

### P1（影响开发效率）

1. **`agent/session/runtime.py` 过大** — 单一文件包含 run_session、spawn_agent、session checking 等多种职责，超过合理尺寸
2. **`core/` 反向依赖 `agent/task`** — 核心层不应该依赖上层的领域模型，应通过接口或数据类解耦

### P2（架构整洁性）

3. **`agent/v2/` 过渡目录** — 兼容层可以移除，统一走 `agent/session/`
4. **`executor/mcp/` 位置不当** — 移到 `agent/mcp/` 或独立顶级目录
5. **`entry/` 过度拆分** — 合并子目录到 `entry/` 下

### P3（可维护性）

6. **`_test_project/` 标记** — 加 `README` 说明用途，或移到 `tests/fixtures/`
7. **`mcp_servers/` 合并** — 1 个文件不值得独立目录
8. **测试冗余** — MCP 测试 6 个文件重复度高，`test_v2_runtime.py` 4700 行需拆分

---

## 四、结论

**总体评分：B+**

项目结构整体健康，分层清晰。主要问题是过渡期残留（`agent/v2/`）、部分文件过大（`runtime.py`）、以及 `core/` 对 `agent/` 的反向依赖。这些问题影响不大但属于"看一眼就能改"的范畴。
