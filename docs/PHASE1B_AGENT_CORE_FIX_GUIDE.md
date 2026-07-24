# Agent Core Loop — 根本原因分析与修复方案

**Date:** 2026-07-24  
**Companion to:** `PHASE1B_AGENT_CORE_AUDIT.md`  
**Principle:** 每个 bug 不仅修症状，更要理解它为什么会出现，以及正确的架构应该是什么

---

## 根本原因分类

19 个 bug 可归为 5 类根因：

| 根因类别 | Bug 数量 | 模式 |
|----------|----------|------|
| **提取函数时的 closure 断裂** | 2 | 将嵌套函数提升为模块级函数时，丢失了闭包变量 |
| **类型边界泄漏** | 3 | `list[dict]` 与 `list[LLMMessage]` 混用；`Optional` 字段未处理 |
| **State residue** | 4 | 状态跨 run 残留（cache、pending history、findings、collapse store） |
| **早期 return 绕过 side-effect** | 4 | 在关键 side-effect（log、cleanup）之前 return |
| **边界条件缺失** | 6 | 空流终止、环境 block、空 parent_id、step 硬编码、批量粒度 |

---

## CRITICAL

### BUG 1: subagent 委托全面崩溃 — `parent_session_id` 未定义

**问题链路：**

```
spawn_agent()                          # 原嵌套函数，parent_session_id 是外层参数
  └─ def execute():                   # 匿名 lambda
       └─ _execute_child_session(...)  # 提取到模块级函数
            └─ line 251: self.get_backend_for_session(parent_session_id)
               ↑ NameError — parent_session_id 不是此函数的参数
```

**根本原因：**

这不是简单的"漏了参数"。深层问题是 **`_execute_child_session` 的函数签名边界与调用方 `spawn_agent` 之间的契约没有被类型系统强制执行**。原代码是嵌套函数（闭包捕获 `parent_session_id`），提取为模块级函数时：

- `parent_session_id` 在 `spawn_agent` 中是参数（第 35 行）
- `parent` Session 记录也是参数（第 57 行：`parent = self._store.get_session(parent_session_id)`）
- 但 `_execute_child_session` 接收了 `parent` 却没有接收 `parent_session_id`
- `parent.id` 就是 `parent_session_id` —— 纯属冗余别名

**正确做法：**

```python
# runtime_spawn.py:251 — 修改前
backend=self.get_backend_for_session(parent_session_id),

# 修改后（一行修复）
backend=self.get_backend_for_session(parent.id),
```

**为什么 `parent.id` 是正确的：** `spawn_agent` 的第 54–57 行保证了 `parent = self._store.get_session(parent_session_id)` —— 所以 `parent.id == parent_session_id` 恒成立。

**架构教训：** 提取函数时，如果新函数已经接收了某个对象（`parent`），就不应该再依赖访问该对象原始 ID 的闭包变量。冗余参数是 bug 的源头。

---

### BUG 2: 流中断时静默丢弃 tool call — 投机执行导致工作区状态漂移

**问题链路：**

```
stream_iter() 产生 TOOL_USE 事件
  → tool_calls_raw.append(tool_call)     # 累积
  → executor.enqueue(tool_call)          # 开始投机执行
  → executor.process_queue()             # 可能已完成

stream_iter() 异常终止（网络断开/超时/后端 bug）
  → 没有 FINISH 事件
  → 回退到 line 3191-3196
  → 返回 ActionType.FINISH  ← 静默丢弃 tool_calls_raw！
```

**根本原因：**

回退路径把"流正常结束且没有 tool call"和"流异常终止且有待执行的 tool call"视为同一情况。正确的语义应该是：

| 流终止方式 | tool_calls_raw 非空 | 应该返回 |
|-----------|-------------------|---------|
| FINISH 正常 | 是 | `TOOL_CALL` + 继续循环 |
| FINISH 正常 | 否 | `FINISH` |
| 异常终止（无 FINISH） | 是 | `TOOL_CALL` + 继续循环 |
| 异常终止（无 FINISH） | 否 | `FINISH` |

**正确做法：**

```python
# core.py:3191-3196 — 修改前
self._stream_usage = None
return Action(
    action_type=ActionType.FINISH,
    thought=accumulated_thought,
    message=accumulated_text or "Stream ended.",
)

# 修改后
if tool_calls_raw:
    return Action(
        action_type=ActionType.TOOL_CALL,
        thought=accumulated_thought,
        tool_calls=tool_calls_raw,
    )
return Action(
    action_type=ActionType.FINISH,
    thought=accumulated_thought,
    message=accumulated_text or "Stream ended before model produced a result.",
)
```

**额外修复（防止投机执行泄漏）：**

回退路径还应该在返回 TOOL_CALL 之前清理 executor 中未完成的任务：

```python
# 在返回 TOOL_CALL 之前
executor.cancel_pending()   # 取消尚未完成的投机执行
```

否则返回的 `tool_calls_raw` 中有一部分 tool call 的 observation 已经偷偷修改了文件，却不在返回列表中。

---

## HIGH

### BUG 3: Compaction 恢复时类型不匹配 — Agent 在 compaction 后立即崩溃

**问题链路：**

```
_build_recovery_messages()                # core.py:2898 → list[LLMMessage]
  └─ recovery.build_recovery_messages([]) # compaction.py:1000 → list[dict]
       └─ 返回一堆 {"role": "user", "content": "..."} dict
  └─ msgs.append(LLMMessage(...))         # core.py:2909 ← 在 list[dict] 上追加 LLMMessage
  └─ return msgs                          # 标注为 list[LLMMessage]，实际是 list[dict|LLMMessage]

_inject_recovery_after_compact()          # core.py:2883
  └─ return list(messages) + recovery_msgs # list[LLMMessage] + list[dict|LLMMessage]
                                            # → 后续代码遍历时 AttributeError
```

**根本原因：**

不是一个简单的"忘写转换代码"。这是 **layer boundary violation**：

- `context/compaction.py` 是底层 context 模块，故意返回 raw dict（不依赖 LLM 类型）
- `agent/core.py` 是上层 agent 模块，操作 `LLMMessage` 对象
- 中间缺少一个 **adapter**：没有人负责把 raw dict 转成 `LLMMessage`

`_build_recovery_messages` 的类型签名说 `-> list[LLMMessage]`，但内部实现不遵守。Python 的 type annotation 不会在运行时校验，所以这个谎言一直没被发现——直到 compaction 真的触发。

**正确做法：**

方案 A（推荐 — 在边界处转换）：

```python
# core.py:_build_recovery_messages — 改成：
def _build_recovery_messages(self) -> list["LLMMessage"]:
    recovery = _build_compaction_recovery(self._full_registry, self._current_repo_path)
    raw_msgs = recovery.build_recovery_messages([])
    # Adapter: raw dict → LLMMessage（这里是边界转换点）
    msgs = [LLMMessage(
        role=m.get("role", "user"),
        content=m.get("content", ""),
    ) for m in raw_msgs]
    # ...
    msgs.append(LLMMessage(role="user", content=f"[MEMORY RESTORED]\n{_ltc}"))
    return msgs
```

方案 B（让底层直接返回 `LLMMessage`——破坏模块边界，不推荐）。

---

### BUG 4: long_term_context 在 compaction 后被注入两次

**问题链路：**

```
_build_messages(token_budget)
  │
  ├─ Step 1: long_term = self._build_long_term_context()  ← 第一次 memory 注入
  │     → 传给 build_request_messages(long_term_context=long_term)
  │     → 作为 user message 注入，后跟 "Understood" assistant
  │
  ├─ Step 2: build_request_messages 内部触发 compaction
  │     → ctx.compact_triggered = True
  │
  ├─ Step 3: _inject_recovery_after_compact(messages)
  │     → _build_recovery_messages()
  │         ├─ self._invalidate_ltc()
  │         └─ self._build_long_term_context()  ← 第二次 memory 注入！
  │             → 作为 [MEMORY RESTORED] user message 追加
  │
  └─ 结果：memory 内容出现两次
```

**根本原因：**

compaction 的"恢复"逻辑假定 compaction **替换**了历史——所以重新注入 memory 是正确的（原本在历史中的 memory 上下文被替换掉了）。但这忽略了**同一个 `_build_messages` 调用内**，memory 也在 `build_request_messages` 的 pre-compaction 阶段被注入了。这两个注入路径互不知道对方的存在。

**正确做法：**

识别到 `build_request_messages` 已经注入了 memory 的情况：

```python
# _build_recovery_messages — 修改后
def _build_recovery_messages(self, *, memory_already_injected: bool = False) -> list["LLMMessage"]:
    recovery = _build_compaction_recovery(self._full_registry, self._current_repo_path)
    raw_msgs = recovery.build_recovery_messages([])
    msgs = [LLMMessage(role=m["role"], content=m["content"]) for m in raw_msgs]
    
    if not memory_already_injected:  # ← 只有没注入过才注入
        self._invalidate_ltc()
        _ltc = self._build_long_term_context()
        if _ltc:
            msgs.append(LLMMessage(role="user", content=f"[MEMORY RESTORED]\n{_ltc}"))
    return msgs
```

并在调用处传入：

```python
# _inject_recovery_after_compact:
recovery_msgs = self._build_recovery_messages(
    memory_already_injected=(long_term is not None and bool(long_term))
)
```

**或更简单：** 不要在 `build_request_messages` 内注入 memory，一律在 recovery 阶段注入。这避免了两个注入路径的协调问题。

---

## MEDIUM

### BUG 5: 响应式 compaction 替换历史后 CollapseStore 索引过期

**根本原因：** `CollapseStore` 基于**位置索引**（`start=3, end=8`）引用消息。`_attempt_reactive_compact` 通过 `history.replace_messages()` 把整个消息列表替换成 compacted 版本后，旧索引不再指向有效消息。这是一个**数据耦合**问题——两个系统通过索引耦合，但只有一个系统知道索引何时失效。

**正确做法：** 在 `_attempt_reactive_compact` 成功后重置 collapse store：

```python
# core.py:3274 之后加：
history.replace_messages(history.from_dicts(compacted, history.max_messages))
# 清理过期的 collapse 索引
self._context_trimming_state.collapse_store = CollapseStore()
```

---

### BUG 6: missing test target 的 follow-up 步骤是死代码

**根本原因：** `_finish_missing_test_target()` 返回 `RunResult` → `_run_body` 见到非 None 的 `result` 就立即退出 → `_finish_tool_turn` 中允许 follow-up 的逻辑永远无法执行。

**正确做法：** `_finish_missing_test_target` 不该返回 `RunResult`，应返回 `_ToolBatchApplication` 并设置一个 marker flag，让主循环继续时检查 follow-up 是否还有配额。

---

### BUG 7: 未处理异常导致 Langfuse span 泄漏

**正确做法：** 把 `task_context.__enter__()` 和 `__exit__()` 包在 `try/finally` 中：

```python
_task_ctx = task_context.__enter__()
try:
    result = self._run_body(...)
finally:
    try:
        task_context.__exit__(None, None, None)
    except Exception:
        pass  # best-effort cleanup
```

---

### BUG 8: Environment block 跳过触发工具调用的日志记录

**正确做法：** 在 environment_block 的 early return 之前加 log_observation：

```python
if analysis.environment_block:
    log.log_observation(
        step=step,
        observation=observation,
        tool_call_id=tool_call.id,
    )
    return _finish_environment_block(...)
```

---

### BUG 9: `_project_instructions` 缓存在不同 repo 之间持续存在

**正确做法：** 模仿 `_repo_map_cache_key` 的模式——增加一个缓存键：

```python
# _initialize_run 中：
if getattr(self, "_project_instructions_repo", "") != task.repo_path:
    if hasattr(self, "_project_instructions"):
        del self._project_instructions
    self._project_instructions_repo = task.repo_path
```

---

### BUG 10: ContextPlanner 中硬编码 step=1

**正确做法：** `build_request_messages` 已接收 `step` 参数，只需传进去：

```python
# manager.py:326 — 修改前
snapshot = ContextSnapshot(step=1, ...)

# 修改后
snapshot = ContextSnapshot(step=step, ...)
```

---

## LOW

### BUG 11–19：单行修复

| Bug | 修复 |
|-----|------|
| 11: `_pending_history` 残留 | `_initialize_run` 结尾加 `self._pending_history = None` |
| 12: Capabilities 重复追加 | 追加前检查 `history` 是否已包含 capabilities message |
| 13: `log.log_action` 无保护 | 加 try/except + 至少调用 `state_machine.fail()` |
| 14: 批量 circuit breaker | 把 `all_failed` 改为 `any_failed`，逐次记录失败 |
| 15: Feedback injected 未 reset | 在 `_build_recovery_messages` 中调用 `self._feedback_injected_files.clear()` |
| 16: Subagent 回退 ID | 把 `or agent_id` 改为 `or ""`，然后让 EventBus.publish_typed 忽略空 session_id |
| 17: 取消延迟 | 在 `_handle_single_tool_call` 循环中每完成一个工具调用后检查 `cancellation.is_cancelled` |
| 18: Findings 未清除 | 在 `_run_body` 的 finally 中调用 `self._accumulated_structured_findings.clear()` |
| 19: tool_call_id=None | 在 `anthropic_backend.py` 的 else 分支加：如果 `role == "tool"` 但 `tool_call_id` 为 None，则合成一个 user message 包装它 |

---

## 架构经验总结

### 为什么要做这次审计而不仅仅是 fix-and-forget

这 19 个 bug 有一个共同模式：**都出在系统边界上**。

| 边界类型 | 示例 |
|----------|------|
| 函数提取（closure → module-level） | Bug 1, 2 |
| 类型边界（raw dict vs typed object） | Bug 3, 10, 19 |
| 生命周期边界（run A vs run B） | Bug 6, 9, 11, 18 |
| 控制流边界（early return vs side-effect） | Bug 4, 7, 8 |
| 并发/异步边界（thread vs event loop） | Bug 5, 17 |

每类边界都需要**明确的契约**。缺失的契约无法被类型系统强制执行（Python 的 type hint 不会在运行时校验），因此审计是唯一的防线。

### 本次不做修改的三类正确保证

审计也确认了以下边界是**正确的**：

1. **Session generation = 原子级 SQL** → `run_generation = run_generation + 1` 在 WHERE 子句中带 status 前置条件，不存在 reuse-after-complete 竞态
2. **Memory context 隔离** → `AgentFactory.create()` 为非 PRIMARY agent 传递 `memory_context=None`，子 agent 不会 access parent 的 memory
3. **EventBus cleanup** → `finally` 块保证 unsubscribe；drain task 的 `CancelledError` → flush 剩余事件 → 退出确保没有事件沉淀

这些都是正确架构的例子：**跨边界传递 null，而非共享可变状态；在 finally 块中清理，而非依赖调用方记得调用**。未来的设计应该效仿这些模式。
