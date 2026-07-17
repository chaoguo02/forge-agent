# AgentTurnState 不可变化 — 影响范围与修改方针

> 日期: 2026-07-17
> 目标: AgentTurnState 成为 CC State 的完整对等物——单点真相源，每次 continue 创建新实例

---

## 一、影响范围

### 1.1 需要修改的文件

| 文件 | 改动 | 风险 |
|------|------|------|
| `agent/core.py` | 验证 18 个 continue 点都创建新 State | 中 |
| `agent/core.py` | `_finish_run` closure 不依赖 State mutable 字段 | 低（已验证） |
| `executor/query_loop.py` | ⚠️ 并行 QueryLoopState，与 AgentTurnState 独立 | 不在此次范围 |

### 1.2 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `agent/session/runtime.py` | 不触碰 turn-level state，只设置 agent config |
| `entry/chat.py` | ChatSession 管理自己的 _session_state + _shared_history |
| `hooks/` | 只读 history.to_dicts()，不读写 State |
| `agent/session/task_state_machine.py` | 只有注释引用 |
| 所有 test 文件 | Mock backend 不依赖 State 内部结构 |

### 1.3 技术债记录（不改）

- **`executor/query_loop.py::QueryLoopState`**: 并行 State 实现，与 agent/core.py 双轨。后续应统一或删除。

---

## 二、agent/core.py 详细定位

### 2.1 State 字段（当前已正确）

```
AgentTurnState(frozen=True)
├── turn_count: int              ← 快照点设置
├── messages: tuple[LLMMessage]  ← 快照点设置（浅拷贝安全）
├── tool_schemas: tuple[LLMToolSchema] ← 快照点设置
├── total_tokens: int            ← 快照点设置
├── child_turn_phase: _ChildTurnPhase  ← continue 点更新
├── recovery: RecoveryState      ← continue 点更新
├── stop_hook_count: int         ← continue 点更新
├── stop_hook_verify_count: int  ← continue 点更新
└── transition: Transition | None ← continue 点设置
```

### 2.2 快照点（1 处）

**位置**: `_build_messages` 返回后、LLM 调用前（~line 1060）

当前代码：
```python
_state = _state.with_updates(
    turn_count=step,
    messages=tuple(history._messages),
    tool_schemas=tuple(tools),
    total_tokens=total_tokens,
)
```

状态：✅ 已正确

### 2.3 Continue 点（18 处）

每个 continue 必须创建新 State（`_state = _state.with_updates(...)` 或 `with_transition(...)`）。

| # | 位置(~行) | 触发条件 | transition_reason | 当前状态 |
|---|-----------|---------|-------------------|---------|
| 1 | 1068 | control plane 拒绝 tool call | (next_turn) | ⚠️ 需验证 |
| 2 | 1237 | reactive_compact 成功 | reactive_compact | ✅ |
| 3 | 1281 | output truncated → escalation | escalation | ✅ |
| 4 | 1290 | output truncated → recovery inject | recovery | ✅ |
| 5 | 1330 | completion_fact_check blocked | completion_blocked | ✅ |
| 6 | 1396 | stop_hook blocked (first hook) | stop_hook_blocking | ✅ |
| 7 | 1417 | completion_guard blocked | completion_blocked | ✅ |
| 8 | 1441 | stop_hook blocked (verify hook) | stop_hook_blocking | ⚠️ 需验证 |
| 9 | 1464 | reflection inject | reflection | ✅ |
| 10 | 1478 | reflection continue (inner) | reflection | ⚠️ 需验证 |
| 11 | 1499 | token_budget_continuation nudge | nudge | ✅ |
| 12 | 1583 | tool calls disabled (tools=[]) | (next_turn) | ⚠️ 需验证 |
| 13 | 1679 | environment_unavailable block | (terminal, not continue) | N/A |
| 14 | 1694 | block with env message | (terminal) | N/A |
| 15 | 1781 | block with env message 2 | (terminal) | N/A |
| 16 | 1824 | block with env message 3 | (terminal) | N/A |
| 17 | 1884 | stop_hook retry limit | (terminal) | N/A |
| 18 | 1908 | reflection message inject 2 | reflection | ⚠️ 需验证 |
| 19 | 1915 | reflection message inject 3 | reflection | ⚠️ 需验证 |
| 20 | 2106 | post-tool missing_test_target | (next_turn) | ⚠️ 需验证 |
| 21 | 2108 | post-tool reflection | reflection | ⚠️ 需验证 |

标记 ⚠️ 的点需要逐一检查——它们可能直接 `continue` 而没有创建新 State。

### 2.4 _finish_run closure（不依赖 State）

`_finish_run` 闭包访问的变量：
- `_git_state`（局部变量）
- `completion_ctx`（局部变量）
- `task_obs_closed`（nonlocal）
- `_verification_ok`（局部变量，不在 State 中）
- `_test_was_run`（局部变量，不在 State 中）

不访问 `_state.*`。✅ 无需改动。

---

## 三、修改方针

### 原则

1. **每个 `continue` 前必须有 `_state = _state.with_updates(...)`**，明确声明新 State
2. **Transition 必须带类型**：`Transition.escalation(64000)` 而非裸字符串
3. **State 字段只读**：除了 `with_updates()` 调用，不对 `_state` 做属性赋值
4. **快照在 LLM 调用前**：`messages` 和 `tool_schemas` 在 `_build_messages` 后、`_call_with_retry` / `_stream_and_dispatch` 前快照

### 修改顺序

1. 逐一检查标记 ⚠️ 的 continue 点，补上 `_state = _state.with_updates(...)`
2. 运行回归测试确认 158 pass
3. 最终检查：确认没有任何裸 `continue` 遗漏
4. 提交

### 不改

- `executor/query_loop.py::QueryLoopState`：独立实现，不在此次范围
- `ConversationHistory` 存储机制：保持 mutable，State 拿浅拷贝快照
- 外部模块：已验证零依赖

---

## 四、验证

```bash
# 回归测试
pytest tests/test_cc_alignment_features.py tests/test_plan_approval.py \
       tests/test_cli_v2_orchestration.py tests/test_agent_v2_mcp_integration.py \
       tests/test_chat.py -q

# 检查：无裸 continue
grep -n "^\s*continue$" agent/core.py | grep -v "#" | grep -v "with_updates\|with_transition"
```
