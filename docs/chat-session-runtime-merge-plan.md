# ChatSession ↔ SessionRuntime 合并计划

> 日期: 2026-07-18
> 状态: 调研完成 / 待执行

---

## 一、现状：两套独立的执行链路

### CLI `run` 路径

```
cli.py run()
  → run_v2_mode()
    → SessionRuntime.create_root_session()
    → SessionRuntime.run_session()
      → AgentFactory.create()
      → agent._pending_history = ...
      → agent.run(task, log)
```

### Chat 路径

```
cli.py chat()
  → ChatSession.__init__()
    → AgentFactory.create()
  → ChatSession.run_round()
    → Task(...)
    → EventLog.create()
    → agent._pending_history = ... (shared history)
    → agent.run(task, log)
```

### 功能对比

| 功能 | `SessionRuntime.run_session()` | `ChatSession.run_round()` |
|------|-------------------------------|--------------------------|
| AgentFactory.create() | ✅ | ✅ |
| build_runtime_messages() | ✅（delegation prompt + skills + memory） | ⚠️ 刚补 delegation prompt |
| runtime_message_source | ✅ child completion + live steering | ❌ |
| completion_fact_check | ✅ worktree resolution guard | ❌ |
| Plan mode throttling | ✅ 每 5 步稀疏、25 步全量 | ❌ |
| SESSION_START hook | ✅ | ❌ |
| EventLog + live event callback | ✅ | ✅（_run_with_renderer） |
| Task contract (max_steps/budget) | ✅ TaskContract | ⚠️ 直接传 config |
| Session state persist | ✅ SQLite 持久化 | ❌ |
| try/finally cleanup | ✅ | ❌ |
| History injection | ✅ 新 history + injected messages | ✅ 共享 history |
| Session context injection | ❌ | ✅ rolling_summary + skills |
| Auto-compaction after round | ❌ | ✅ _maybe_auto_compact |
| Stats accumulation | ✅（通过 DB） | ✅ total_tokens/steps |

### 核心差异汇总

**SessionRuntime 有而 Chat 没有的（4 项）**：
1. `runtime_message_source` — child completion notification 注入
2. `completion_fact_check` — worktree 未解决时阻止 FINISH
3. `_plan_throttled_source` — plan mode 系统提示节流
4. `SESSION_START` hook 触发

**ChatSession 有而 SessionRuntime 没有的（3 项）**：
1. 跨轮共享 history + 轮次注入
2. `SessionState` 结构化任务追踪（TaskSummary、rolling_summary）
3. `_maybe_auto_compact_after_round` — 每轮自动压缩检查

---

## 二、合并思路

### 目标

让 ChatSession 内部使用 `SessionRuntime.run_session()` 执行每一轮，而不是直接调 `agent.run()`。保持 ChatSession 独有的功能（共享 history、SessionState、auto-compact）不变。

### 架构

```python
class ChatSession:
    def __init__(self, ...):
        self._runtime = SessionRuntime(...)  # 持有 store + backend + registry
        self._root_session = self._runtime.create_root_session(...)
        # 保留：_shared_history, _session_state, _renderer

    def run_round(self, user_input: str):
        # 保留：SessionState tracking
        # 保留：_shared_history 维护
        # 保留：auto-compact 检查
        
        # 改为：通过 SessionRuntime.run_session() 执行
        result = self._runtime.run_session(
            self._root_session.id,
            agent_name=self._agent_name,
            task_description=user_input,
            messages=[LLMMessage(role="user", content=user_input)],
        )
        
        # 保留：渲染、stats 累积
```

### 保留的 ChatSession 特性

这些必须保留，SessionRuntime 没有：

| 特性 | 文件位置 | 保留方式 |
|------|---------|---------|
| `_shared_history` | `chat.py:148` | ✅ 保留 — 跨轮注入 |
| `_session_state` tasks | `chat.py:154` | ✅ 保留 — start_task/finish_task |
| round stats | `chat.py:308-309` | ✅ 保留 — total_tokens/steps |
| `_maybe_auto_compact_after_round` | `chat.py:326` | ✅ 保留 |
| `_run_with_renderer` event callback | `chat.py:342` | ✅ 保留 — 通过 hook 或 callback |
| Goal stop hook | `chat.py:160` | ✅ 保留 |
| Skill fork | `chat.py:464` | ✅ 保留 |

### 改为由 SessionRuntime 提供的

这些 ChatSession 当前缺失，使用 SessionRuntime 后自动获得：

| 功能 | 由 run_session() 提供 | 当前 Chat 状态 |
|------|---------------------|---------------|
| build_runtime_messages | ✅ | ⚠️ 已补 |
| runtime_message_source | ✅ child completion | ❌ |
| completion_fact_check | ✅ worktree guard | ❌ |
| plan throttling | ✅ | ❌ |
| SESSION_START hook | ✅ | ❌ |
| EventLog | ✅ | ✅（已自建） |
| SQLite 持久化 | ✅ messages 存 DB | ❌ |
| try/finally cleanup | ✅ | ❌ |

---

## 三、实现步骤

### Step 1：ChatSession 持有 SessionRuntime

```python
class ChatSession:
    def __init__(self, ...):
        store = SessionStore(db_path)
        runtime = SessionRuntime(
            store=store,
            backend=backend,
            base_registry=registry,
            agent_registry=agent_registry,
            root_agent_config=agent_cfg,
        )
        root_session = runtime.create_root_session(
            agent_name="build",
            repo_path=repo_path,
            title="chat session",
        )
        self._runtime = runtime
        self._root_session_id = root_session.id
```

**影响**：需要引入 `default_session_db_path()`，在 CLI 中创建 `store` + `runtime` 传给 ChatSession。

**文件**：
- `entry/chat.py` — `__init__` 中创建 runtime
- `entry/cli.py` — 传递 runtime 参数

### Step 2：run_round 改为委托给 run_session

```python
def run_round(self, user_input: str):
    task_ctx = self._session_state.start_task(...)
    
    # 注入到 shared_history
    self._shared_history.add(LLMMessage(role="user", content=user_input))
    
    # 通过 SessionRuntime 执行
    result = self._runtime.run_session(
        self._root_session_id,
        agent_name=self._agent_name,
        task_description=user_input,
        intent=intent,
    )
    
    # 从 runtime 中取回 agent 的消息，追加到 shared_history
    persisted = self._runtime._store.list_messages(self._root_session_id)
    self._shared_history = ConversationHistory.from_dicts(...)
    
    # 保留：stats、session_state、auto-compact、rendering
    ...
```

**注意**：`run_session()` 会创建新 `ConversationHistory` 并注入 runtime messages。Chat 需要把执行后的消息同步回 `_shared_history`。

**文件**：
- `entry/chat.py` — `run_round` 重写

### Step 3：合并 EventLog 和 Renderer 回调

`run_session()` 使用 `agent.run(task, log)` 并支持 `event_callback`。Chat 当前的 `_run_with_renderer` 通过 hook `log._append` 实现实时渲染。`SessionRuntime` 支持 `event_callback` 参数，可以用来做同样的渲染。

```python
runtime = SessionRuntime(
    ...,
    event_callback=lambda event: self._render_event(event),
)
```

**文件**：
- `agent/session/runtime.py` — 确认 event_callback 在 run_session 中使用
- `entry/chat.py` — 移除 `_run_with_renderer`，改用 event_callback

### Step 4：验证

```python
# 回归测试
pytest tests/test_chat.py tests/test_cc_alignment_features.py -q

# 手动测试
python -m entry.cli chat --repo .
# 验证：Agent(subagent_type="explore") 可以派发并收到结果
# 验证：/mode plan 可以工作
# 验证：Plan mode 有节流
# 验证：会话历史跨轮保留
# 验证：记忆写入和回忆
```

---

## 四、风险与注意事项

1. **Shared history 双向同步**：Chat 的 `_shared_history` 和 `SessionRuntime` 的 `store.list_messages()` 是两种不同的持久化机制。需要确保执行后的消息能被 Chat 的 shared_history 访问。

2. **`_pending_history` 注入机制**：当前 Chat 通过 `agent._pending_history = self._shared_history` 注入跨轮历史。`run_session()` 内部也设置 `agent._pending_history`。两者会冲突——需要确保 Chat 的跨轮历史在 `run_session()` 中被正确处理。

3. **Session ID 复用**：Chat 的所有轮次共享一个 root session ID。`run_session()` 对同一个 session ID 的多次调用会 append messages 到 DB。Chat 需要正确处理消息追加和重复检测。

4. **Agent rebuild（switch_model/switch_mode）**：Chat 支持运行时切换模型和 agent。`SessionRuntime` 的 agent 是在 `run_session()` 中每次重新创建的，所以切换模型只需要更新 `root_agent_config`。
