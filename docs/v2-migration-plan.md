# agent.v2 → agent.session 全局迁移计划

> 目标: 消除 `agent.v2` 双命名空间, `agent.session` 成为唯一 canonical

---

## 现状数据

```
121 个 agent.v2 引用分布在 26 个文件中:
  tests/test_v2_runtime.py: 43 (36%)  ← 最大消费者
  agent/core.py:             8  (7%)
  entry/modes/v2_runner.py:  9  (7%)
  entry/chat.py:             7  (6%)
  tests/test_cc_alignment_features.py: 8 (7%)
  tests/eval/*.py:           9  (7%)
  entry/cli.py:              4  (3%)
  entry/worktree_admin.py:   5  (4%)
  其他 18 个文件:           28 (23%)
```

## 风险矩阵

| 风险 | 等级 | 触发条件 | 缓解 |
|------|------|---------|------|
| 循环导入 | 🔴 | `agent.session` ↔ `agent.core` 互引 | Phase 1 先检查, lazy import 兜底 |
| 私有符号丢失 | 🔴 | `import *` 不转发 `_` 前缀符号 | Phase 1 显式 re-export 所有私有符号 |
| 测试大面积失败 | 🟡 | test_v2_runtime.py 43 引用 | Phase 3 批量 sed 替换 |
| agent/v2 shim 子模块消失 | 🟡 | 直接 `from agent.v2.models import` | Phase 1 保留子模块 shim 文件 |
| entry/cli.py chat.py 模式切换 | 🟡 | V2 run mode vs chat mode 不同路径 | Phase 2 逐个迁移并验证 |

## 私有符号清单（`import *` 不转发的）

```
agent.session.agent_registry:  _TOOL_ALIASES, _TOOL_DECLARATION_ROLES
agent.session.models:          _BUILTIN_AGENTS, _DEFAULT_GENERAL_TOOLS, _DEFAULT_READONLY_TOOLS
agent.session.task_tool:       _format_fork_result, _build_subagent_prompt, _SUBAGENT_PROTOCOL
agent.session.subagent:        _build_system_messages, _build_structured_diagnosis
agent.session.agent_definition:_parse_definition, _load_from_dir
agent.session.runtime_prompt_builder: _load_skills, _load_agent_memory
```

**当前问题**: `agent/v2/models.py` 是 `from agent.session.models import *`，不转发 `_BUILTIN_AGENTS`。  
调用方被迫用 `from agent.v2.models import _BUILTIN_AGENTS` — 但这可以工作因为 `agent/models.py` 是真实文件（shim 的 `import *` 只是不转发 `_` 符号）。

## 4 个 Phase

### Phase 1: 修复 agent.v2 shim（0 风险）

**不改任何调用方**，只修改 `agent/v2/*.py` 的 shim 文件。

当前 shim 文件:
```python
# agent/v2/models.py
from agent.session.models import *  # ← 不转发 _BUILTIN_AGENTS 等私有符号
```

改为:
```python
from agent.session.models import *
from agent.session.models import (
    _BUILTIN_AGENTS, _DEFAULT_GENERAL_TOOLS, _DEFAULT_READONLY_TOOLS,
)
```

同理修复: `task_tool.py`（`_format_fork_result`）, `agent_registry.py`（`_TOOL_ALIASES`）, `subagent.py`（`_build_system_messages`）, `agent_definition.py`（`_parse_definition`）, `runtime_prompt_builder.py`（`_load_skills`）

**文件数**: 6 个 shim 文件
**回归**: 全量测试应全部通过

### Phase 2: 迁移 agent/core.py + entry/ (中等风险)

**不改行为，只改 import 路径。**

`agent/core.py` — 8 处 `from agent.v2.X import Y` → `from agent.session.X import Y`

`entry/` 文件:
- `entry/cli.py`: 4 处
- `entry/chat.py`: 7 处  
- `entry/modes/v2_runner.py`: 9 处
- `entry/worktree_admin.py`: 5 处

**文件数**: 5 个
**回归**: `test_cli_v2_orchestration.py` + `test_plan_approval.py` + `test_plan_prompt_contract.py`

### Phase 3: 迁移 tests/ (低风险)

43 个引用在 `test_v2_runtime.py` 中 — 批量 sed:
```bash
find tests/ -name "*.py" -exec sed -i \
  's/from agent\.v2\./from agent.session./g' {} +
```

**文件数**: ~20 个 test 文件
**回归**: `tests/test_v2_runtime.py` + `tests/test_cc_alignment_features.py`

### Phase 4: 删除 agent/v2/ 目录

确认所有引用已迁移后删除:
```bash
rm -rf agent/v2/
```

**注意**: 这一步不可逆。必须确保没有遗漏引用。

---

## 潜在循环导入检查

当前 `agent.session` 和 `agent.core` 之间的依赖:

```
agent.session.__init__ → agent.session.models → ... (没有 agent.core)
agent.session.runtime → imports agent.core.AgentConfig, ReActAgent
agent.core → imports agent.v2.task_state_machine (会变成 agent.session)
```

Phase 2 迁移 `agent/core.py` 时，如果 `agent.session.runtime` 和 `agent.core` 互引，可能导致循环导入。  
缓解: `agent/core.py` 中的 imports 已经是延迟的（函数内 `from agent.v2.X`），迁移后变为 `from agent.session.X`，不会在模块加载时触发。

---

## 执行顺序

```
Phase 1 → 全量测试 → Phase 2 → 全量测试 → Phase 3 → 全量测试 → Phase 4
```

每 Phase 完成后 commit。Phase 4 前必须确认 0 个 `agent.v2` 残留引用。
