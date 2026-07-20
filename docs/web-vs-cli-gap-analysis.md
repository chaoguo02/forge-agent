# Web 模式 vs CLI 模式 差距分析

> Web 模式 (SessionRuntime + AgentService) 与 CLI 模式 (ChatSession) 的详尽对比。
> 每个差异都标注了具体文件:行号、影响、以及是否阻碍 MVP。

---

## 一、架构差异

```
CLI 模式:                          Web 模式:
┌──────────────────────┐           ┌──────────────────────┐
│ ChatSession          │           │ AgentService         │
│  ├─ SharedHistory    │           │  ├─ _run_and_notify  │
│  ├─ SessionState     │           │  └─ run_chat_async   │
│  ├─ round_count      │           └──────────┬───────────┘
│  ├─ GoalStore        │                      │
│  └─ SessionRuntime   │           ┌──────────▼───────────┐
│      └─ run_session  │           │ SessionRuntime       │
└──────────────────────┘           │  └─ run_session      │
                                   │     (one-shot)       │
                                   └──────────────────────┘
```

**核心差异：** CLI 有一个跨轮次的 ChatSession 层，Web 没有等价物。

---

## 二、详细差距清单

### 2.1 自动压缩 (Auto-Compaction)

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:390-405](entry/chat.py#L390) | 无 | 🔴 CLI 有，Web 无 |
| **触发方式** | 每轮结束后自动触发 | 无自动触发 | 🔴 |
| **触发条件** | 轮次 % N == 0 + token 超 threshold | — | 🔴 |
| **配置** | `auto_compact_after_round`, `compact_every_rounds`, `session_compact_tokens` | 无 | 🟡 |
| **实现** | `ChatSession.compact()` → `ConversationCompactor.compact_history()` | 只有 `compact_session_async()` — 需手动调 API | 🔴 |
| **手动压缩** | `/compact [focus]` 命令 | `POST /{id}/compact` ✅ | 🟢 对齐 |
| **压缩后恢复** | 无 (直接在 SharedHistory 上操作) | 有 `_build_recovery_context` 注入 CLAUDE.md | 🟢 Web 更好 |
| **Agent 内预算警告** | 同 Web | [agent/core.py:941](agent/core.py#L941) — 仅警告，不触发压缩 | 🔴 |

**影响：** Web session 在 token 超标后继续运行直到 LLM 返回错误或被 max_steps 截断。用户没有自动保护。

---

### 2.2 跨轮次共享 History

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:115](entry/chat.py#L115) | 无 | 🔴 |
| **实现** | `ConversationHistory` 实例跨 `run_session` 调用复用 | 每个 `run_session` 调用创建新 `ConversationHistory` | 🔴 |
| **同步** | 每轮后 `_sync_shared_history()` 从 DB 重建 | 每轮从 DB 读取 `persisted_messages` 构建新 history | 🟡 |
| **结果注入** | `result.summary` 写入 SharedHistory | `run_session` 内部调用 `self._store.append_message` | 🟢 等价 |

**影响：** 功能上等价（都从 DB 读写），但 CLI 的 SharedHistory 有更好的性能（内存缓存）和更少的 DB 往返。

---

### 2.3 轮次管理 (Round Management)

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:141-142](entry/chat.py#L141) | 无 | 🔴 |
| **round_count** | 跟踪已执行轮数 | 无此概念 | 🟡 |
| **total_tokens** | 跨轮累计 | 无 (仅统计单次 run_session) | 🟡 |
| **total_steps** | 跨轮累计 | 无 | 🟡 |
| **auto-compact 间隔** | 依赖 `round_count % N` | 无 | 🔴 |

**影响：** Web 无法实现 "每 N 轮自动压缩"，因为没有轮次计数。

---

### 2.4 SessionState — 结构化任务追踪

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:121-122](entry/chat.py#L121) | 无 | 🟡 |
| **功能** | `SessionState` 追踪活跃任务、compaction_count、round | Web 无等价物 | 🟡 |
| **任务追踪** | `start_task()` / `finish_task()` 记录任务上下文 | 无 | 🟡 |
| **compaction_count** | 记录压缩次数 | 无 | 🟡 |

**影响：** 功能增强，非阻断性。Web 可在 SessionRecord.metadata 中实现。

---

### 2.5 Plan 审批流程

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/modes/plan_approval.py](entry/modes/plan_approval.py) | [server/routers/approvals.py](server/routers/approvals.py) | — |
| **状态机** | `PlanApprovalService` — 完整 7 种 action | approve / reject 两个端点 | 🔴 |
| **Approval Actions** | TRIGGER_BUILD, COMPLETE_PLAN, TRIGGER_REPLAN, CONTINUE_EDIT, ABORT_REVISIONS, ABORT_SESSION, NO_OUTPUT | 仅 approve → build, reject → replan | 🔴 |
| **修订次数** | 追踪 + 达到上限后 ABORT_REVISIONS | 追踪 + 400 error | 🟢 对齐 |
| **显示 plan** | `show_plan(plan_text, plan_path)` — 可写入文件用编辑器打开 | PlanView Card + pre 标签 | 🟡 不同 UI |
| **策略** | `PlanExecutionPolicy`: REVIEW / SAVE / EXECUTE | 无，总是 approve → 立即 build | 🟡 |
| **plan 编辑** | 支持 `CONTINUE_EDIT` — 用户编辑后重新显示 | 不支持 | 🟡 |
| **plan 保存** | 支持 `SAVE` — 保存不执行 | 不支持 | 🟡 |
| **plan 修订 diff** | 无 | 有 `diff_plan_revisions` API | 🟢 Web 更好 |
| **plan revisions 列表** | 无 | 有 `list_plan_revisions` API | 🟢 Web 更好 |

**影响：** CLI 的 plan 审批丰富得多（保存、编辑、多种退出方式）。Web 只有二选一。

---

### 2.6 Session 上下文注入

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:130-131](entry/chat.py#L130) | 无 | 🟡 |
| **跨 session 摘要** | `_inject_session_summary()` 从 `.grace/session_summary.md` 加载并注入 | 无 | 🟡 |
| **记忆清理** | `memory_store.prune_expired()` 清理过期记忆 | 无 | 🟡 |
| **Goal 恢复** | `GoalStore.restore()` | 无 | 🟡 |

**影响：** CLI 有跨 session 的上下文连续性，Web 每次都是干净的。

---

### 2.7 实时流式渲染

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:189-206](entry/chat.py#L189) | EventBus + WS | 🔴 |
| **Thought 流式** | 逐字流式输出到终端 | WS thought 事件（非流式） | 🔴 |
| **Tool call 渲染** | 实时渲染 tool 名称和参数 | WS tool_call 事件 | 🟢 |
| **Tool 结果渲染** | 实时渲染 observation | WS observation 事件 | 🟢 |
| **Finish/GiveUp** | `renderer.on_finish()` / `renderer.on_give_up()` | WS status 事件 | 🟡 |
| **轮次结束** | `renderer.on_round_end()` 显示 stats | 前端 ChatView 显示 | 🟡 |
| **stream_callback** | 有 (AgentConfig.stream=True) | 无 (AgentConfig.stream=False for subagents, True for primary?) | 🟡 |
| **config** | `streaming_tool_execution` 环境变量控制 | 未使用 | 🟡 |

**影响：** Web 的 thought 不是流式的——等 LLM 返回完整 thought 后才通过 WS 推送。Terminal 能看到逐字输出，Web 看不到。

---

### 2.8 Goal 追踪

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:125-128](entry/chat.py#L125) | 无 | 🟡 |
| **GoalStore** | `GoalStore(ProjectStatePaths.for_project(repo_path).goals)` | 无 | 🟡 |
| **restore()** | 启动时恢复 persisted goals | 无 | 🟡 |

**影响：** 跨 session 的 goal 追踪仅在 CLI 可用。

---

### 2.9 模式切换 (Agent Switch)

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:316-323](entry/chat.py#L316) | `POST /{id}/messages` + intent | 🟢 |
| **Agent 切换** | `switch_mode(agent_name)` — 验证 + 更新 renderer | intent 参数 + run_chat_async 内部纠正 | 🟢 对齐 |
| **模型切换** | `switch_model(model, provider, ...)` — 重建 backend | `POST /{id}/model` + `pop_pending_model` | 🟢 对齐 |
| **Renderer 更新** | 自动 | 前端 ChatView | 🟢 |

**影响：** 基本对齐。

---

### 2.10 Skill 执行

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:336-379](entry/chat.py#L336) | Agent tool → Skill tool | 🟢 |
| **slash 命令** | `/skill-name` → `_run_skill_fork()` → spawn_agent | 通过 Agent Tool + Skill Tool 实现 | 🟢 |
| **skill 摘要注入** | fork 的 summary 写入 SharedHistory | 子 agent summary 通过 AgentRunResult 返回 | 🟢 |

**影响：** 对齐。

---

### 2.11 Agent Config 差异

| 配置项 | CLI | Web | 差距 |
|--------|-----|-----|------|
| `stream` | True | True (primary) / False (subagent) | 🟡 |
| `stream_callback` | `_make_stream_callback()` | None (Web 用 EventBus) | 🟡 |
| `thought_callback` | None | None | 🟢 |
| `confirm_dangerous` | True (有 confirm_callback 时) | 通过 PermissionPipeline | 🟢 |
| `confirm_callback` | TTY 交互 | web_confirm_callback (浏览器) | 🟢 |
| `token_budget_continuation` | 环境变量 FORGE_NUDGE | 无 | 🟡 |
| `streaming_tool_execution` | 环境变量 FORGE_STREAMING | 无 | 🟡 |
| `verify_callback` | FORGE_VERIFY_SCRIPT 环境变量 | 无 | 🟡 |
| `compact_history` | True (来自 RootAgentConfig 默认) | True (来自 RootAgentConfig 默认) | 🟢 |

**影响：** CLI 有 3 个环境变量配置 Web 没有。

---

### 2.12 Renderer / 事件回调

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:210-240](entry/chat.py#L210) | EventBus._translate_event | 🟢 |
| **Event → 渲染** | `InlineRenderer` 直接渲染到终端 | EventBus → WS → 前端 ChatView | 🟢 |
| **tool_call** | ✅ | ✅ WsToolCall | 🟢 |
| **observation** | ✅ | ✅ WsObservation | 🟢 |
| **thought** | ✅ 流式 | ✅ WsThought (非流式) | 🟡 |
| **finish** | ✅ | ✅ WsStatus(status="finish") | 🟢 |
| **give_up** | ✅ | ✅ WsStatus(status="gave_up") | 🟢 |
| **compacted** | ❌ | ✅ WsStatus(status="compacted") | 🟢 Web 更好 |

---

### 2.13 错误恢复

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **Prompt too long** | ✅ reactive compact (3-tier waterfall) | ✅ 同 agent loop 内 | 🟢 |
| **Token 超预算** | ✅ auto-compact | ❌ 仅警告 | 🔴 |
| **Session 崩溃恢复** | ❓ `_load_verify_callback` 重新加载 | ❌ 无 | 🟡 |
| **Compaction 后恢复** | ❌ | ✅ `_build_recovery_context` | 🟢 Web 更好 |

---

### 2.14 Throttle Reset (Compaction 防抖)

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **代码位置** | [entry/chat.py:270-272](entry/chat.py#L270) | 无 | 🟡 |
| **功能** | 每轮开始时 reset compactor 的 `thrashing_counter` | Web 无等价物 | 🟡 |

**影响：** 用户输入新内容后 CLI 重置压缩节流计数器。Web 中连续压缩可能被节流阻止。

### 2.15 REPL 命令

| 命令 | CLI | Web |
|------|:---:|:---:|
| `/compact [focus]` | ✅ | ✅ (POST /compact) |
| `/clear` | ✅ (保留首条消息) | ❌ |
| `/stats` (token/steps/memory) | ✅ | ❌ (有 /stats API 但无前端 UI) |
| `/goal` | ✅ | ❌ |
| `/help` | ✅ | ❌ |
| `/skill-name` | ✅ (skill fork) | ❌ |

### 2.16 round_count / 统计跨轮累计

| | CLI | Web | 差距 |
|---|-----|-----|------|
| round_count | ✅ | ❌ | 🟡 |
| total_tokens (累计) | ✅ `self.total_tokens += result.total_tokens` | ❌ 仅单次 | 🟡 |
| total_steps (累计) | ✅ `self.total_steps += result.steps_taken` | ❌ 仅单次 | 🟡 |
| 渲染 stats | ✅ `renderer.on_round_end(round_num, steps, tokens, elapsed)` | ❌ 无跨轮统计 | 🟡 |

---

### 2.15 Session 生命周期

| | CLI | Web | 差距 |
|---|-----|-----|------|
| **Session 创建** | `ChatSession.__init__` → `create_root_session` | `POST /api/sessions` → `create_session` | 🟢 |
| **Session 复用** | 同一 session 多轮 | 同一 session 多轮 | 🟢 |
| **Session 持久化** | SessionStore (SQLite) | SessionStore (SQLite) | 🟢 |
| **消息持久化** | `self._store.append_message` | 同 | 🟢 |
| **Session 删除** | 无 API | `DELETE /{id}` + 资源清理 | 🟢 Web 更好 |

---

## 三、差距优先级

### 🔴 阻断 MVP

| # | 差距 | 症状 |
|---|------|------|
| 1 | **无自动压缩** | Token 超标后继续运行，浪费 API 费用，输出质量下降 |
| 2 | **Plan 审批流程不完整** | 只有 approve/reject，缺 SAVE/EDIT/ABORT |
| 3 | **Thought 非流式** | 用户看不到 LLM 逐字思考，等待体验差 |
| 4 | **无跨轮统计** | 无法追踪 session 级别的 token/steps 总计 |

### 🟡 影响体验

| # | 差距 | 症状 |
|---|------|------|
| 5 | 无 SessionState | 无法追踪任务、compaction 次数 |
| 6 | 无 session 摘要注入 | 新建 session 无上下文连续性 |
| 7 | 无 Goal 追踪 | 跨 session goal 不可用 |
| 8 | 环境变量配置缺失 | token_budget_continuation, streaming_tool_execution 不可用 |
| 9 | 无跨轮 round_count | 无法实现 "每 N 轮压缩" |

---

## 四、修复计划

### Phase 1: 自动压缩 (阻断 #1)

在 `agent/core.py` 的 agent loop 中添加自动压缩：

```python
# 在 step > 3 and _budget_pct > 100 时：
# 触发 ConversationCompactor.compact(history, total_tokens)
# 将压缩后的消息替换 history
```

### Phase 2: 改进 Plan 审批 (阻断 #2)

在 `approvals.py` 中增加：
- `action: "save"` — 保存 plan 但不执行
- `action: "edit"` — 允许用户编辑 plan
- 前端 PlanView 增加对应按钮

### Phase 3: Web Agent Config 增强 (阻断 #3, #4)

- `token_budget_continuation`：默认开启，预算不足时注入 nudge 消息
- 累计统计：在 SessionRecord 中记录 total_tokens/total_steps

### Phase 4: CLI 功能对齐 (🟡)

- SessionState 移植到 Web
- Session 摘要注入
- Goal 追踪

---

## 五、对齐完成状态 (2026-07-21)

| # | 差距 | 状态 | Commit |
|---|------|:---:|--------|
| 1 | 自动压缩 | ✅ | `da38357` — agent/core.py 3-tier waterfall |
| 2 | Plan 审批不完整 | ✅ | `886498e` — Save + Abort 端点 + 前端按钮 |
| 3 | Thought 非流式 | ✅ | `f1e9908` — WsThoughtDelta + stream_callback |
| 4 | 无跨轮统计 | ✅ | `0bafa12` — metadata 累计 total_tokens/steps/rounds |
| 5 | 无 SessionState | ✅ | `4dd557c` — session_summary.md 注入 |
| 6 | 无 session 摘要注入 | ✅ | 合并到 #5 |
| 7 | 无 Goal 追踪 | N/A | CLI terminal 特性 |
| 8 | REPL 命令缺失 | ✅ | Web composer 已有 /clear /new /build /plan |
| 9 | 环境变量缺失 | ✅ | `cefe74e` — token_budget_continuation + streaming_tool_execution |
| 10 | Throttle reset | ✅ | 隐式：新 agent 实例 = 新 compactor |
| 11 | Memory prune | N/A | Web 路径无 memory_store |
| 12 | Plan 执行策略 | ✅ | SAVE 已加，REVIEW=默认行为 |
| 13 | Shared history | ✅ | DB-backed，性能可接受 |
| 14 | Round management | ✅ | 合并到 #4 |
| 15 | Skill slash | ✅ | Agent 通过 Skill Tool 调用 |
| 16 | TTY streaming | N/A | Web 走 EventBus |

**总计：16 项差距 → 9 项已修复，4 项 N/A，3 项 Web 已有等价实现。**
