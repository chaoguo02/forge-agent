# Grace Code Web 功能专项审计报告

> 审计日期：2026-07-21 | 审计范围：Web 前端 + Server API + Session/Runtime/Event 全链路
> 审计人：Web 功能专项审计负责人（AI）

---

## 1. 总体结论

**当前 Grace Code Web 已具备多视图、多模块的工程雏形，后端 agent 架构扎实（subagent 真实委托、session 隔离正确、权限继承完整），但前端存在关键数据流断裂、两个视图为空白占位、StatsDashboard 因逻辑反转 bug 从未显示数据、plan_ready 事件不具备持久化导致刷新后审批界面丢失。前端的"丰富感"与后端事实源之间存在多条不可靠链路。**

系统的最强部分在后端 agent 层：`SessionRuntime` + `runtime_spawn.py` + `subagent.py` 构成的 subagent 委托是真实发生的（非 prompt 幻术），session 隔离、权限继承、取消令牌级联、worktree 隔离都正确实现。系统的最弱部分在前端数据流一致性：多个视图使用了不同的事实源，刷新后状态无法恢复，统计数据因代码 bug 完全不可用。

---

## 2. 功能映射总表

| 页面/功能 | 前端组件 | Store 状态 | API 调用 | 后端路由 | Service/Runtime 事实源 | WS 依赖 | 接入状态 |
|---|---|---|---|---|---|---|---|
| **Chat** | `ChatView.tsx` | `chatStore.sessionStateById[id]` | `loadMessages`, `loadTraceEvents`, `sendChat` | `GET /messages`, `GET /trace/events`, `POST /messages` | `SessionService.get_messages()` + `EventLog` JSONL + `EventBus` WS | ✅ 是 | **已完整接入** |
| **Tasks** | PlaceholderView | 无 | 无 | 无 | 无 | ❌ 否 | **仅 UI 壳子** 🔴 |
| **Plan** | `PlanView.tsx` | `chatStore.planApproval` + `sessionStore.activeDetail` | `getSessionPlan`, `approvePlan`, `rejectPlan`, `savePlan`, `abortPlan` | `GET /plan`, `POST /approve`, `POST /reject`, `POST /save-plan`, `POST /abort-plan` | `agent_service.py._run_and_notify()` 发射 `plan_ready` + `.grace/plans/{id}.md` 文件 + PlanRevisionService | ✅ WS `plan_ready` | **部分接入** 🟡 |
| **Reviews** | `DiffReviewView.tsx` | 无（本地 state） | `getPendingDiffs`, `updateDiffStatus` | `GET /api/diffs/pending`, `PATCH /api/diffs/{id}` | `StatsService.get_session_diffs()` | ❌ 否 | **已完整接入** |
| **Stats** | `StatsDashboard.tsx` | 无（本地 state） | `getDailyRollups`, `getToolRankings`, `getRecentSessionStats` | `GET /api/stats/daily`, `GET /api/stats/tools`, `GET /api/stats/sessions` | `StatsService` → `StorageBackend` (daily_rollup 表 + session_stats 表) | ❌ 否 | **已损坏** 🔴 |
| **Memory** | `MemoryView.tsx` | 无（本地 state） | `getMemorySnapshot`, `getMemoryDetail`, `createMemory`, `updateMemory`, `deleteMemory` | `GET /api/memory`, `GET /api/memory/{name}`, `POST /api/memory`, `PATCH`, `DELETE` | `MemoryStore` (file+SQLite) | ❌ 否 | **已完整接入** |
| **Events** | PlaceholderView | 使用 `chatStore.events` 但视图是 Placeholder | 无 | 无 | 无 | ❌ 否 | **仅 UI 壳子** 🔴 |
| **Session Sidebar** | `SessionSidebar.tsx` | `sessionStore.sessions`, `activeId` | `listSessions`, `createSession`, `deleteSession`, `deleteSessionsBatch` | `GET /api/sessions`, `POST`, `DELETE`, `POST /batch-delete` | `SessionService.list_sessions()` → `StorageBackend` | ❌ 否 | **已完整接入** |
| **Session Tree** | `SessionTree.tsx` | `sessionStore.sessionTree` | `fetchSessionTree` | `GET /api/sessions/{id}/tree` | `SessionService.get_session_tree()` (递归，最大深度5) | ❌ 否 | **已完整接入** |
| **Subagent Detail** | `SubagentDetail.tsx` | `chatStore.viewingChildSessionId` + `worktreeStates` | `getSession`, `getTraceEvents` | `GET /api/sessions/{id}`, `GET /trace/events` | `SessionService` + EventLog | ❌ 否 | **已完整接入** |
| **Event Sidebar** | `EventSidebar.tsx` | `chatStore.events` (WS 累积) | `fetch("/api/storage/stats")`, `fetch("/api/sessions/{id}/stats")` | `GET /api/storage/stats`, `GET /api/sessions/{id}/stats` | `EventBus` WS 流 + `StatsService` | ✅ 是 | **已完整接入** |

---

## 3. 问题清单

### 🔴 P0 — 核心链路错误、功能不可用、误导用户

#### P0-1. StatsDashboard 数据显示逻辑反转 — 数据永远不渲染

- **用户可见现象**：Stats 页面永远显示 "Loading chart..." / "Loading rankings..." / "Loading sessions..."，实际数据已从 API 成功获取但从未被设置到 state。
- **根因**：[StatsDashboard.tsx:40](web/src/components/StatsDashboard.tsx#L40) — `if (!cancelled) return;` 逻辑反转。`!cancelled` 在组件存活时为 `true`，导致 `.then()` 提前返回，成功获取的数据被丢弃。正确写法应为 `if (cancelled) return;`。
- **涉及文件**：`web/src/components/StatsDashboard.tsx:40`
- **涉及函数**：`StatsDashboard` 组件内的 `useEffect`
- **是否已有部分修复**：否，此 bug 从未被发现。
- **验证方法**：修复后统计页面应显示 token 柱状图、工具排行榜、最近 session 列表。

#### P0-2. "Tasks" 和 "Events" 两个顶层 Tab 是 PlaceholderView

- **用户可见现象**：点击顶部 "Tasks" 或 "Events" Tab 只显示 "Tasks view — coming soon." / "Events view — coming soon."
- **根因**：[App.tsx:135-137](web/src/App.tsx#L135) — 条件渲染链中，"tasks" 和 "events" 未被任何显式条件匹配，落入 `PlaceholderView`。EventSidebar 虽然渲染了（在 Chat 视图下显示为右侧面板），但 Events Tab 本身是空壳。
- **涉及文件**：`web/src/App.tsx:131-137`
- **是否已有部分修复**：否
- **影响**：用户看到 7 个顶级 Tab，但只有 5 个有实际内容。

#### P0-3. `plan_ready` 事件在 WS 重连/页面刷新后无法恢复 — 计划审批界面丢失

- **用户可见现象**：在 plan agent 完成并显示审批界面后，刷新页面 → 审批按钮消失，PlanView 可能显示 "No plan has been generated yet"。
- **根因**：`plan_ready` 事件由 `agent_service.py:_run_and_notify()` 通过 `EventBus.publish_typed()` 直接推送到 WS 队列（[agent_service.py:699](server/services/agent_service.py#L699)），**不经过** EventLog JSONL。`/trace/events` 端点（[sessions.py:294-335](server/routers/sessions.py#L294)）使用 `_translate_event()` 仅翻译 EventLog 事件，而 `_translate_event()` 不处理 `plan_ready` 类型（[event_bus.py:106-186](server/services/event_bus.py#L106) 中无 `plan_ready` 分支）。因此页面刷新后 `loadTraceEvents()` 无法恢复 `plan_ready` 事件。
- **涉及文件**：
  - `server/services/agent_service.py:672-707` — plan_ready 发射点
  - `server/services/event_bus.py:106-186` — _translate_event 缺少 plan_ready
  - `server/routers/sessions.py:294-335` — /trace/events 使用 _translate_event
- **验证方法**：启动 plan session → 等待 plan_ready → 刷新页面 → 检查是否出现审批按钮。

#### P0-4. Session 切换时 ChatView 的 `key={activeId}` remount 策略导致本地 draft/mode/composer 状态全部丢失

- **用户可见现象**：在 Session A 的输入框写了半段话，切换到 Session B 再切回来 → 输入框内容清空、mode 选择重置、composer 菜单关闭。
- **根因**：[App.tsx:129](web/src/App.tsx#L129) — `<ChatView key={activeId ?? "no-session"} />` 使用 React key 强制 unmount/remount。这确保了 session 隔离但也销毁了所有本地 UI 状态。
- **涉及文件**：`web/src/App.tsx:129`
- **设计权衡**：这是 session 隔离的合理代价，但缺少 UI 状态持久化（例如将 draft 存入 `chatStore` 的 per-session state）。
- **严重程度**：P0 是因为用户体验影响大，但架构上 key-remount 是正确的隔离策略。需要在 store 层增加 draft 持久化。

### 🟡 P1 — 功能能跑，但设计走偏、语义不一致

#### P1-1. `plan_ready` 只在 `agent_service.py` 中发射，不在 agent core 中 — 非标准事件路径

- **现象**：`plan_ready` 不是从 agent loop 内部的事件系统产生的，而是在 `_run_and_notify` 的 try/except 块中手动发射。
- **根因**：所有标准事件（thought、tool_call、observation）通过 `event_callback → EventBus.publish → _translate_event` 路径，但 `plan_ready` 绕过了这个路径，直接在 `agent_service.py` 中调用 `publish_typed`。这意味着 `plan_ready` 与 agent 事件系统解耦，无法通过 EventLog 回放，也无法在 CLI 模式中使用。
- **涉及文件**：`server/services/agent_service.py:672-707`
- **正确方向**：将 plan 完成作为 `task_complete` 事件中的一个标记（或独立事件类型），让 `_translate_event` 处理。

#### P1-2. Plan 和 Build 共享同一个 session_id — Claude Code 式的设计偏差

- **现象**：`approve` 端点（[approvals.py:107-112](server/routers/approvals.py#L107)）在**同一** session 上调用 `run_chat_async(agent_name="build")`。这意味着 plan agent 和 build agent 的 messages 混在同一个 conversation 中。
- **根因**：文档 `critical-reflection.md` 也已指出 "Plan and Build sharing session_id is arguably a CC design defect"。
- **影响**：`agent_name` 字段在 plan→build 转换后被更新为 "build"，但 PlanView 判断 `isPlanSession` 依赖 `agent_name === "plan"` — 因此在 build 执行后、刷新前，PlanView 的显示状态会不一致。
- **建议**：长期应分离为父子 session（plan 为父，build 为子），短期至少在 UI 上正确处理 agent_name 变更。

#### P1-3. ChatView 统计展示混用多个不可靠数据源

- **现象**：[ChatView.tsx:697-703](web/src/components/ChatView.tsx#L697) 展示 steps、tokens、runtime。这些值来自：
  - `steps`（chatStore 的 WS 累积值）
  - `tokens`（chatStore 的 WS 累积值）
  - `activeDetail?.total_tokens_estimate`（SessionService 用 `len(content)//2` 估算的值）
  - `activeDetail?.message_count`（对话消息数）
  - `runtimeLabel`（前端 `Date.now() - created_at` 实时计算）
- **根因**：没有统一的事实源。`total_tokens_estimate` 是字符数/2 估算，并非真实 token 计数。`steps` 来自 WS 事件的步骤号，不是 StatsService 的持久化步数。
- **建议**：ChatView 应主要使用 WS 实时数据，但在非活跃 session 应 fallback 到 StatsService 的持久化记录。

#### P1-4. StatsDashboard 的 `tool_summary` 序列化不一致

- **现象**：[stats_service.py:46](server/services/stats_service.py#L46) — `tool_summary` 使用 `json.dumps()` 存储为 JSON 字符串。但在 [stats.py:92](server/routers/stats.py#L92) 读取时又 `json.loads()` 解析。传给前端的字段名是 `tool_summary`（字符串），但前端类型定义期望的是 `Record<string, number>`（[stats.ts:9](web/src/types/stats.ts#L9)）。
- **根因**：序列化边界不清晰。`StatsService` 应负责序列化/反序列化，router 不应再做二次解析。
- **影响**：如果 `get_session_stats` 返回的 `tool_summary` 是 JSON 字符串而前端期望对象，会导致渲染错误。

#### P1-5. Subagent tool_call 事件归属使用"第一个 running agent"回退逻辑

- **现象**：[chatStore.ts:368-378](web/src/stores/chatStore.ts#L368) — 当 `tool_call` 的 `child_session_id` 对应的子 agent 不在 running 状态时，回退到"第一个 running 的 agent"。如果多个子 agent 并发运行，tool_call 可能被错误归属。
- **根因**：`child_session_id` 字段在所有 WS 事件上都存在，但可能存在时序问题（tool_call 在 subagent_start 之前到达）。
- **建议**：不使用回退逻辑，直接依赖 `child_session_id` 精确匹配；如果 child 不存在则忽略该 tool_call 的归属更新。

#### P1-6. EventSidebar 使用 3 秒 debounce 拉取 stats — 数据可能过时

- **现象**：[EventSidebar.tsx:82-96](web/src/components/EventSidebar.tsx#L82) — `steps`、`tokens`、`events.length` 变化后等待 3 秒才请求 stats API。在快速执行的 session 中，stats 可能在 session 完成后才被请求。
- **根因**：用 debounce 替代增量更新。WS 事件流本身已经包含 step/token 信息，无需额外 API 轮询。
- **建议**：EventSidebar 的 execution stats 应直接使用 chatStore 的实时数据（steps、tokens），仅在首次加载时从 API 获取历史数据。

#### P1-7. sendChat 的 planApproval 保护逻辑不够健壮

- **现象**：[chatStore.ts:452-454](web/src/stores/chatStore.ts#L452) — `planApproval: prev.planApproval?.isWaiting ? prev.planApproval : null`。如果用户在 plan 等待期间发送新消息，planApproval 被保留。但如果 `isWaiting` 因为某种原因已经是 `false`（如快速连续点击），planApproval 对象虽在但 `isWaiting: false`，会被清除。
- **根因**：已修复（chatStore.ts:454 条件判断），但临界窗口仍然存在。
- **严重程度**：P1，因为这是之前已知问题 M4+L4 的部分修复。

### 🟢 P2 — 体验/可维护性问题

#### P2-1. memory API 的 `source` 和 `source_session_id` 在 detail 端点中硬编码为空字符串

- **现象**：[memory.py:157-158](server/routers/memory.py#L157) — `"source": ""`, `"source_session_id": ""` — 无论实际数据是什么，API 都返回空字符串。
- **根因**：`Memory.to_dict()` 不暴露 source 字段，router 层直接硬编码为空。
- **建议**：从 `MemoryStore` 或 `FileMemoryBackend` 中读取实际的 source 信息。

#### P2-2. confirm() 原生弹窗用于删除确认 — 不可定制、无无障碍支持

- **现象**：[SessionSidebar.tsx:65](web/src/components/SessionSidebar.tsx#L65) 和 [SessionSidebar.tsx:92](web/src/components/SessionSidebar.tsx#L92) — 使用浏览器原生 `confirm()`。
- **建议**：统一使用 `ConfirmModal` 组件（MemoryView 已使用）。

#### P2-3. `_wsSessionId` 空字符串初始值可能导致竞态

- **现象**：`chatStore._wsSessionId` 初始值为 `""`。在 `connectWs` 和 `handleWsEvent` 中有多处 `if (get()._wsSessionId !== sessionId) return;` 检查，但空字符串作为初始值意味着在任何 session 连接之前，`_wsSessionId` 等于 `""`。
- **影响**：如果一个异步操作在所有 session 连接之前尝试访问 `_wsSessionId`，`resolveSessionId` 会返回 `""`，可能导致状态写入错误的 key。

#### P2-4. Token 估算公式不可靠

- **现象**：[session_service.py:101](server/services/session_service.py#L101) — `len(str(m.content or "")) // 2` 作为 token 估算。对于中文（每个字符可能是 1-3 个 token），这个估算严重偏低。
- **建议**：如果无法接入真实的 tokenizer，至少使用 `len(content) // 3` 或标注为 "字符数/2 估算"。

#### P2-5. 冗余代码/未使用组件

- **现象**：`ObservationBlock.tsx` 和 `SlashMenu.tsx` 已导出但未被任何组件引用。`useSlashCommands` hook 未使用。`api/config.ts` (`getAgents()`) 从未在前端调用。`thought_delta` 事件类型已定义但 `handleWsEvent` 不处理。
- **建议**：清理或接入这些组件。

---

## 4. 专项问题回答

### 4.1 当前 Web 上的 Plan 和真实 plan 模式，是否是一回事？

**不是一回事，但部分连接。**

真实 plan 模式的触发路径：
1. 用户创建 "plan" agent session（`createSession("plan")`）
2. 发送消息 → `run_chat_async(agent_name="plan")` 在后台线程运行
3. Plan agent 调用 `ExitPlanMode` 工具 → `RunResult.contract` 被设置
4. `_run_and_notify` 检测到 `_is_plan or result.contract` → 发射 `plan_ready` WS 事件
5. 同时写入 `.grace/plans/{id}.md` 文件
6. 前端 `ChatView` 显示审批按钮（通过 `planApproval.isWaiting`）
7. `PlanView` 显示计划内容（通过 `planApproval.planText` 或 `getSessionPlan` API）

**连接点**：`plan_ready` WS 事件 + plan file on disk。**断裂点**：
- `plan_ready` 不在 EventLog 中，刷新后无法恢复
- PlanView 的数据源有三个：`planApproval.planText`（WS）、`planFile`（磁盘文件）、`activeDetail.summary`（DB）—— 三者可能不一致
- `savePlan` 调用后将 `agent_name` 改为 "build"，PlanView 的 `isPlanSession` 判断立即失效

### 4.2 当前 session 切换隔离，是否已经真正做好？还有哪些残留风险？

**核心隔离已做好，但存在以下残留风险：**

✅ **已做好的**：
- React `key={activeId}` 强制 remount ChatView（[App.tsx:129](web/src/App.tsx#L129)）
- `chatStore.sessionStateById` 按 session_id 分桶（[chatStore.ts:139-147](web/src/stores/chatStore.ts#L139)）
- WebSocket 连接按 session_id 隔离（[chatStore.ts:574-663](web/src/stores/chatStore.ts#L574)）— 切换 session 时 `disconnectWs()` 再 `connectWs(newId)`
- 后端 `EventBus` 按 session_id 路由事件（[event_bus.py:303-331](server/services/event_bus.py#L303)）
- `SessionRuntime.try_acquire_session()` 防止并发执行（[agent_service.py:563](server/services/agent_service.py#L563)）

⚠️ **残留风险**：
1. **draft/mode/composer 状态不持久化**：切换到另一个 session 再切回来，所有本地 UI 状态丢失（P0-4）
2. **`clear()` 方法保留 `currentMode` 和 `currentModel`**（[chatStore.ts:413-417](web/src/stores/chatStore.ts#L413)）— 这是有意为之，但如果用户期望完全重置则会有困惑
3. **pruneSessions 会关闭当前 WS**：如果 session list 刷新时 active session 不在列表中 → WS 被强制关闭（[chatStore.ts:426-428](web/src/stores/chatStore.ts#L426)）

### 4.3 当前 subagent 在后端是否真实发生？前端是否真实反映？

**后端：真实发生！** `runtime_spawn.py` 创建真实的子 session（独立 SessionRecord、ReActAgent、线程），不是 prompt 幻术。

**前端：部分反映。**
- ✅ `SubagentProgress` 浮动卡片在 `subagent_start`/`subagent_stop` 事件时更新
- ✅ `SessionTree` 显示父子关系（通过 `/tree` API）
- ✅ `SubagentDetail` 可查看子 session 的完整执行日志
- ⚠️ subagent tool_call 归属有回退逻辑风险（P1-5）
- ⚠️ 子 agent 的工具调用实时进度仅在 `tool_call` WS 事件到达时更新，存在时序问题
- ❌ 无 subagent 汇总视图（多个子 agent 完成后无 aggregate report）

### 4.4 当前 Reviews / Stats / Memory 是真的接上了，还是只接了一半？

**Reviews：完整接入。** `DiffReviewView` → `getPendingDiffs` → `GET /api/diffs/pending` → `StatsService` → SQLite `session_diffs` 表 → approve/reject 回写。链路完整。

**Stats：已损坏。** 见 P0-1 — 数据成功从 API 获取但因 JavaScript 逻辑反转 bug 永远不渲染。一旦修复，链路是完整的。

**Memory：完整接入。** CRUD + search + overview + detail 全链路连通，支持 create/edit/delete 操作。小问题：`source`/`source_session_id` 硬编码为空字符串（P2-1）。

### 4.5 当前 websocket 事件流是否可信，是否会串 session 或重复污染？

**基本可信，但有以下风险点：**

✅ **正确的设计**：
- `EventBus.publish()` 按 `event.session_id` 精确路由（[event_bus.py:303-305](server/services/event_bus.py#L303)）
- 前端 `ws.onmessage` 检查 `_wsSessionId === sessionId`（[chatStore.ts:596](web/src/stores/chatStore.ts#L596)）
- 切换 session 时先 `disconnectWs()` 再 `connectWs(newId)`

⚠️ **风险点**：
1. **legacy broadcast fallback**：当 `event.session_id` 未设置时，事件广播到所有 session（[event_bus.py:334-340](server/services/event_bus.py#L334)）— 如果某个代码路径的 Event 未设置 session_id，会导致跨 session 事件泄漏
2. **WS 重连期间的静默丢弃**：重连延迟（指数退避 1s-16s，最多 5 次）期间的所有事件永久丢失（[chatStore.ts:625-649](web/src/stores/chatStore.ts#L625)）
3. **重复事件**：`handleWsEvent` 没有事件去重机制（无 event_id 检查），如果 EventBus 因任何原因重复推送同一事件，前端会重复渲染

### 4.6 当前 stats/step/token 的统计是否可信？

**不可信，存在多重问题：**

1. **StatsDashboard 完全不显示数据**（P0-1）— 统计页面从未工作过
2. **Token 估算公式不准确**：`len(content)//2` 对中文严重偏低（P2-4）
3. **多数据源不一致**：
   - ChatView 的 `steps` 来自 WS 事件的 step 字段（实时，但重连后丢失）
   - ChatView 的 `tokens` 来自 WS 事件（同上）
   - EventSidebar 的 stats 来自 `GET /api/sessions/{id}/stats` API（持久化，但有 3 秒 debounce 延迟）
   - SessionSidebar 的 `total_tokens_estimate` 来自字符数/2 估算
4. **StatsRecorder 的 tool 统计不区分 session**：`record_tool_call` 的参数 `tool_params={}` 永远为空（[stats_recorder.py:53](server/services/stats_recorder.py#L53)），丢掉了所有工具参数信息
5. **daily rollup 按日期聚合有边界问题**：多个 session 在同一天完成时正确累计，但如果 session 跨天运行，只计在完成日期

### 4.7 当前前端是否存在"页面看起来丰富，但背后事实源不统一"的问题？

**是的，这是系统最核心的架构问题。** 具体表现：

| 展示内容 | 实时数据源（WS） | 持久数据源（API） | 刷新后 |
|---|---|---|---|
| Chat 时间线 | `chatStore.timeline` (WS 累积) | `loadTraceEvents` → `/trace/events` | ✅ 可恢复 |
| Plan 审批 UI | `chatStore.planApproval` (plan_ready WS) | `getSessionPlan` → plan file | ❌ 部分丢失 |
| Steps 数字 | `chatStore.steps` | `GET /stats` | ✅ 有 fallback |
| Tokens 数字 | `chatStore.tokens` | `activeDetail.total_tokens_estimate` | ⚠️ 估算值不准 |
| Stats 图表 | 无 WS | `getDailyRollups` | ❌ 因 bug 不渲染 |
| Subagent 状态 | `chatStore.backgroundAgents` (subagent_start/stop WS) | `SessionTree` API | ⚠️ 历史子 agent 状态不可恢复 |
| 工具审批 | `chatStore.toolApprovals` (approval_required WS) | 无 REST 查询 | ❌ 刷新后丢失 |

### 4.8 当前实现中，哪些地方最偏离 AI Native / Claude Code 式设计？

1. **`plan_ready` 事件绕过标准事件系统**：在 Claude Code 的设计思想中，所有 agent 状态变更都应通过统一的事件管道（EventLog → EventBus → WS），确保 CLI 和 Web 复用同一事实源。当前 `plan_ready` 在 `agent_service.py` 中手动发射，是 Web-only 的特殊路径，偏离了事件驱动架构。

2. **Plan 和 Build 共享 session_id**：从 CC 的公开设计思想来看，plan 应是一个独立的"阶段"或"子任务"，而非与 build 混在同一 conversation 中。混用 session_id 导致 agent_name 歧义、状态转换不清晰。

3. **缺少"计划作为一等公民"的持久化**：plan 内容写入 `.md` 文件是好的，但 plan 的审批状态（waiting/approved/rejected/revised）应该持久化到 session metadata（或独立的状态表），而非仅依赖瞬时的 WS 事件。

4. **前端状态管理缺少"事实源分层"**：CC 的设计思想强调"event log 是唯一事实源，UI 是投影"。当前前端混合使用了 WS 实时流、REST API 响应、磁盘文件读取作为数据源，没有明确的主事实源和 fallback 策略。

5. **Stats 是第一方采集（agent loop 回调）而非事件溯源**：当前 `StatsRecorder` 在 agent loop 中被直接调用。更好的设计是：agent loop 只发射事件 → 独立的 StatsCollector 消费事件流 → 写入 stats 表。这样 stats 可以完全从 EventLog 重建。

---

## 5. 改造总计划

### 第一批：立即修复（P0 缺陷）

**目标**：修复导致功能不可用的 bug 和空白视图。

| 序号 | 修改文件 | 具体修改 | 预期行为 | 验证方法 | 风险 |
|---|---|---|---|---|---|
| B1-1 | `web/src/components/StatsDashboard.tsx:40` | `if (!cancelled) return;` → `if (cancelled) return;` | Stats 页面显示 token 柱状图、工具排行、session 列表 | 打开 Stats Tab，验证数据正常渲染 | 无，单字符修复 |
| B1-2 | `web/src/App.tsx:131-137` | 移除 "tasks" 和 "events" Tab，或将其映射到已有功能（tasks→session list 的另一种视图，events→EventSidebar 的全屏版） | Tab 栏干净，不显示占位符 | 点击所有 Tab 验证 | 低，只是 UI 调整 |
| B1-3 | `server/services/event_bus.py:106-186` | 在 `_translate_event` 中增加对 plan contract 的检测：当 `task_complete` 且 payload 包含 contract 时，同时产出 `plan_ready` 消息 | `plan_ready` 可通过 `/trace/events` 恢复 | 运行 plan session → 完成 → 调用 /trace/events → 验证返回包含 plan_ready | 中，需确认 contract 确实在 task_complete 的 payload 中 |
| B1-4 | `web/src/stores/chatStore.ts` | `sendChat` 保留 draft 到 per-session state；`connectWs` 时不清除现有 timeline | 切换 session 后再切回，draft 内容保留 | 在 session A 输入文字 → 切换到 B → 切回 A → 验证文字还在 | 低，加字段即可 |

### 第二批：架构收口（P1 问题）

**目标**：统一数据源，显式化 plan/build 生命周期。

| 序号 | 修改文件 | 具体修改 | 预期行为 | 验证方法 | 风险 |
|---|---|---|---|---|---|
| B2-1 | `server/services/agent_service.py:672-707` | 将 `plan_ready` 的发射从 `_run_and_notify` 移到 agent loop 内（作为 `task_complete` 的特殊处理），让 `_translate_event` 统一处理 | plan_ready 与其他事件走同一管道，CLI 也可用 | 运行 plan session → 验证 CLI 和 Web 都收到 plan_ready | 高，需要修改 agent loop |
| B2-2 | `web/src/components/ChatView.tsx:697-703` | 统计卡片统一使用 StatsService 持久化数据（首次加载），WS 实时数据作为增量覆盖 | Stats 在刷新后保持准确 | 运行 session → 完成 → 刷新 → 验证 stats 数字与之前一致 | 低 |
| B2-3 | `web/src/components/EventSidebar.tsx:82-96` | 移除 debounce，直接使用 chatStore 的实时 steps/tokens；仅首次加载时调用 stats API | Stats 实时更新，无 3 秒延迟 | 运行 session → 观察 EventSidebar 的 steps/tokens 实时变化 | 低 |
| B2-4 | `server/routers/memory.py:157-158` | `source` 和 `source_session_id` 从 Memory 对象中读取实际值 | API 返回真实的 source 信息 | 创建 memory → GET detail → 验证 source/source_session_id 非空 | 低 |
| B2-5 | `web/src/components/SessionSidebar.tsx:65,92` | 用 `ConfirmModal` 替换原生 `confirm()` | 风格统一的确认弹窗 | 点击删除 → 验证弹出 ConfirmModal | 低 |

### 第三批：后续增强（P2 + 体验优化）

**目标**：完善 UI 细节，增强可观测性。

| 序号 | 修改文件 | 具体修改 | 预期行为 |
|---|---|---|---|
| B3-1 | `web/src/stores/chatStore.ts` | 为 WS 事件增加 `event_id` 去重（用 Set 记录最近 500 个 event_id） | 防止事件重复渲染 |
| B3-2 | `web/src/components/SubagentDetail.tsx` | 增加汇总视图：显示子 agent 的 finding 列表、修改文件列表 | 直观了解子 agent 做了什么 |
| B3-3 | `server/services/stats_recorder.py:53` | `tool_params` 传入实际的工具参数（截断到 200 字符） | 步骤日志有实际参数信息 |
| B3-4 | `server/services/session_service.py:101` | token 估算改为 `len(content) // 3` 并标注为估算值 | 更接近真实 token 数 |
| B3-5 | `web/src/components/PlanView.tsx` | 增加 plan revision 历史 diff 查看 | 能看到每次修订的变更 |
| B3-6 | `web/src/App.tsx` | 为 EventSidebar 增加全屏模式（替代空壳 Events Tab） | Events Tab 有实际内容 |

---

## 6. 优先执行建议

**第一优先：B1-1（StatsDashboard bug fix）+ B1-2（移除空壳 Tab）**

原因：
- B1-1 是**单字符修复**，零风险，立即让 Stats 页面从"永远不工作"变为"正常工作"
- B1-2 消除用户看到 "coming soon" 的糟糕体验
- 这两个修复总计不超过 5 分钟，但显著提升产品完整度

**第二优先：B1-3（plan_ready 持久化）+ B1-4（draft 保留）**

原因：
- plan_ready 无法恢复是体验断崖（用户刷新后审批界面消失）
- draft 丢失让多 session 工作流不可用
- 这两项修改量不大，但解决了核心体验问题

**第三优先：B2-1（plan_ready 纳入标准事件管道）**

原因：
- 这是架构级修复，影响面大（CLI + Web）
- 当前实现已能工作，只是不够优雅
- 需要在 agent loop 中做改动，测试要充分

**最后**：第三批的增强项可以在日常迭代中逐步完成，不阻塞核心功能。
