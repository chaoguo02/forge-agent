# Grace Code Web 改造 Todo

> 基于 [web-audit-report-2026-07-21.md](web-audit-report-2026-07-21.md) 审计报告
> 更新日期：2026-07-21

---

## ✅ 已完成（三轮 18 项）

### 第一轮：简单修复（7 项）

- [x] **P0-1** StatsDashboard `!cancelled` → `cancelled` — [StatsDashboard.tsx:40](web/src/components/StatsDashboard.tsx#L40)
- [x] **P0-2** 移除空壳 Tasks/Events Tab — [App.tsx](web/src/App.tsx)
- [x] **P0-4** Draft 跨 session 持久化 — [chatStore.ts](web/src/stores/chatStore.ts) + [ChatView.tsx](web/src/components/ChatView.tsx)
- [x] **P2-1** Memory API source 改用 `getattr` — [memory.py:157](server/routers/memory.py#L157)
- [x] **P2-2** confirm() → ConfirmModal — [SessionSidebar.tsx](web/src/components/SessionSidebar.tsx)
- [x] **P2-4** Token 估算 `//2` → `//3` — [session_service.py](server/services/session_service.py)
- [x] **P2** StatsRecorder 传入实际 tool_params — [stats_recorder.py](server/services/stats_recorder.py) + [core.py](agent/core.py)

### 第二轮：架构修复（6 项）

- [x] **B1-3** plan_ready 事件持久化 — `event_log.py` + `agent/core.py` + `event_bus.py` + `chatStore.ts` + `ChatView.tsx`
- [x] **P1-5** Subagent tool_call 移除猜第一个 running agent 的回退逻辑 — [chatStore.ts](web/src/stores/chatStore.ts)
- [x] **P1-6** EventSidebar 移除 3s debounce — [EventSidebar.tsx](web/src/components/EventSidebar.tsx)

### 第三轮：流式渲染 + 数据可信 + 代码清理（5 项）

- [x] **thought_delta** 实时流式渲染 — [chatStore.ts](web/src/stores/chatStore.ts) + [ChatView.tsx](web/src/components/ChatView.tsx)
- [x] **P1-3** ChatView 移除硬编码假数据（Steps `"5/10"`, Tokens `5792`, 进度条假 50%）— [ChatView.tsx](web/src/components/ChatView.tsx)
- [x] **P2-3** `_wsSessionId` `string` → `string | null` — [chatStore.ts](web/src/stores/chatStore.ts)
- [x] **P2-5** 删除未使用组件（`ObservationBlock.tsx`、`SlashMenu.tsx`、`useSlashCommands.ts`、`api/config.ts`）

---

## 📋 待处理（8 项）

### P1 级

- [ ] **P1-1** plan_ready 纳入 agent loop 标准事件管道
  - 当前：`agent_service.py:_run_and_notify()` 手动调用 `publish_typed(WsPlanReady)`
  - 目标：plan_ready 作为 `task_complete` 事件的一部分从 agent loop 内发出
  - 涉及：`agent_service.py`、`agent/core.py`、`event_bus.py`
  - 风险：高，需修改 agent loop 核心逻辑

- [ ] **P1-2** Plan 和 Build 分离 session_id
  - 当前：approve 后在**同一** session 上 run_chat_async(agent_name="build")
  - 目标：plan session 为父，build session 为子（父子关系）
  - 涉及：`approvals.py`、`agent_service.py`、`PlanView.tsx`、`ChatView.tsx`
  - 风险：高，需大重构

- [ ] **P1-4** tool_summary 序列化边界不一致
  - 当前：`StatsService` 存 JSON 字符串，router 又 `json.loads()` 解析
  - 目标：StatsService 负责序列化/反序列化，router 不二次解析
  - 涉及：`stats_service.py`、`routers/stats.py`
  - 风险：中

- [ ] **P1-7** sendChat planApproval 临界窗口加固
  - 当前：快速连续点击 Approve 时 `isWaiting` 已为 false
  - 目标：增加防抖或原子性检查
  - 涉及：`chatStore.ts`
  - 风险：低

### 增强项

- [ ] **Share 按钮** — 顶栏 Share 按钮目前无 onClick handler，接线或移除
  - 涉及：`App.tsx`

- [ ] **B3-5** PlanView revision diff 查看器
  - 目标：可查看每次 plan 修订的 diff
  - 涉及：`PlanView.tsx`、后端 `/api/sessions/{id}/plan-revisions/{from}/diff/{to}`

- [ ] **B3-6** EventSidebar 全屏模式
  - 目标：替代已移除的 Events Tab，提供全屏事件流视图
  - 涉及：`App.tsx`、`EventSidebar.tsx`

- [ ] **B3-1** WS event_id 去重
  - 目标：`handleWsEvent` 用 Set 记录最近 500 个 event_id，防止重复渲染
  - 涉及：`chatStore.ts`
  - 风险：低

---

## 统计

| 严重度 | 已完成 | 待处理 | 总计 |
|--------|--------|--------|------|
| P0 | 4 | 0 | 4 |
| P1 | 3 | 4 | 7 |
| P2 | 5 | 0 | 5 |
| 增强 | 1 | 4 | 5 |
| Bug | 5 | 0 | 5 |
| **合计** | **18** | **8** | **26** |
