# Grace Code Web MVP 参考方案（基于 claw-code-agent 借鉴）

本文的目标不是复刻 `claw-code-agent`，而是从它已经跑通的本地 GUI 方案里，提炼出适合 `grace-code` 的最小可行 Web 工作台思路。

结论先行：

- `claw-code-agent` 值得借鉴的，不是“它的前端长什么样”，而是它把 GUI 视为一层薄适配：
  - FastAPI 负责本地 API
  - GUI state 负责装配 agent
  - 前端只是消费 API 和状态
- 对 `grace-code` 来说，这个思路非常适合：
  - 前端可以先靠 vibecoding 快速做壳
  - 后端必须自己把 `SessionRuntime / SessionStore / EventLog / approval` 的边界设计稳

---

## 1. 对 claw-code-agent 的观察结论

### 1.1 它的 GUI 是“后端先行”的

`claw-code-agent` 的 GUI 不是先做 React 工程，而是先做了本地 FastAPI GUI：

- GUI app 装配入口：  
  [src/gui/app.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/app.py:20)
- GUI 命令入口：  
  [src/gui/__main__.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/__main__.py:1)
- 路由统一注册：  
  [src/gui/api/router_registry.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/api/router_registry.py:32)

它的主思路是：

1. 先用 Python 把 GUI 需要的接口都做出来
2. 再用一个很薄的前端去消费这些接口
3. 页面复杂度来自业务面板，不来自前端框架魔法

这很适合 `grace-code` 当前阶段。

### 1.2 它用一个 GUI state 统一装配 agent

最值得借鉴的是 `AgentState`：

- [src/gui/state/agent_state.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/state/agent_state.py:20)

它把这些运行参数集中在一起：

- cwd
- model / base_url / api_key
- allow_shell / allow_write
- session_directory
- token / turn / budget 参数
- custom system prompt
- response schema

然后由 `AgentState` 统一重建 agent，而不是让每个路由自己拼 agent。

这个思路对 `grace-code` 的启发是：

- 不要让 `server/routers/*.py` 直接拼 `SessionRuntime`
- 应该先有一层 `AgentApplication` / `AgentService`
- 路由只接请求、调服务、回响应

### 1.3 它的路由是按“能力面板”切分的

`claw-code-agent` 的路由注册非常直白：

- [src/gui/api/router_registry.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/api/router_registry.py:32)

它按 Sessions / Chat / Tasks / Plans / Memory / Worktree / MCP / Skills 等拆路由，而不是把所有 GUI 行为塞进一个大文件里。

这点对 `grace-code` 也适合，但要注意：

- `claw-code-agent` 的面板已经很多了
- 我们的 MVP 不要一上来照单全收

### 1.4 它的前端其实是“可工作的静态壳”

当前 GUI 主页面结构在：

- [src/gui/static/index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:17)

能看到它的最小工作台组成：

- 左侧 `Sessions` 列表
- 左侧 `Settings` 面板
- 中上状态条
- 中间主工作区
- 顶部多视图 tab（Chat / Tasks / Plan / Memory / Worktree / MCP 等）

关键点不是“它用了静态 HTML”，而是：

- 它把页面组织成了清晰的工作台布局
- 前端只是对业务状态进行投影

这对 `grace-code` 的前端 MVP 非常有参考价值。

---

## 2. 什么适合直接借鉴到 grace-code

## 2.1 借鉴点 A：先做“本地工作台”，不是先做“重前端工程”

`claw-code-agent` 当前的 GUI 启动方式非常简单：

- [src/gui/__main__.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/__main__.py:1)

它本质上是：

- 启一个本地 FastAPI
- 打开浏览器
- 用本地页面操作 agent

对 `grace-code` 来说，第一阶段也应该这样：

- 优先做本地 Web 工作台
- 暂时不要考虑复杂登录、多用户、云端 session
- 先把本机 repo 下的 agent 运行、事件、审批、历史看通

这是最稳的 MVP。

## 2.2 借鉴点 B：前端页面先围绕“工作台区块”搭，不围绕组件库搭

从 `claw-code-agent` 的页面结构看，它成功的地方是信息架构清楚：

- `+ New chat` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:17)
- `Sessions` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:20)
- `Settings` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:34)
- `Context management` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:73)
- `System prompt & structured output` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:96)
- 状态栏 `Ready` — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:185)
- 多视图 tabs — [index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:186)

所以 `grace-code` 的前端 MVP 也应该先按工作区块设计：

1. Sessions
2. Chat / Timeline
3. Run Config
4. Plan
5. Worktree / Subagent
6. Memory / History

先把区块和数据流理顺，再谈 UI 精修。

## 2.3 借鉴点 C：查询接口尽量“读磁盘事实”，不要缓存假状态

`claw-code-agent` 在 tasks 路由里有一个很好的原则：

- 每个请求都重新从 workspace 读 `TaskRuntime`
- 这样 GUI 总是反映磁盘上的真实状态

对应代码：

- [src/gui/api/routes/hitl/tasks_routes.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/api/routes/hitl/tasks_routes.py:4)
- [src/gui/api/routes/hitl/tasks_routes.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/api/routes/hitl/tasks_routes.py:85)

这和 `grace-code` 的“零信任与事实源”原则高度一致。

对 `grace-code` 的启发是：

- Session 列表优先从 `SessionStore` / state 目录读取
- 历史事件优先从 `EventLog` 读取
- worktree 状态优先从 Git / stored evidence 验证
- 不要在前端或内存里维护一套“猜出来的 session 状态”

---

## 3. 什么不能直接照搬

## 3.1 不能照搬它的“单 AgentState + 单锁”结构

`claw-code-agent` 的 GUI state 里是一个 agent + 一把锁：

- [src/gui/state/agent_state.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/state/agent_state.py:20)

这个方案适合它当前的本地 GUI，但对 `grace-code` 不够。

原因是 `grace-code` 现在已经有：

- `SessionRuntime`
- `SessionStore`
- child sessions / subagent
- worktree result review
- plan approval loop
- event callback

所以 `grace-code` 应该走的是：

- `AgentApplication`
- `AgentService`
- `SessionQueryService`
- `ApprovalService`
- `EventBus`

而不是把整个 Web runtime 收缩成一个 `AgentState` 全局对象。

## 3.2 不能照搬它的“chat route 直接调 agent.run/resume”方式

`claw-code-agent` 的聊天路由很直：

- [src/gui/api/routes/chat_routes.py](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/api/routes/chat_routes.py:19)

它在路由里直接：

- 决定是 run / resume / propose_plan
- 然后 `asyncio.to_thread(...)`

这对它当前结构可以接受，但对 `grace-code` 来说不够清晰。

因为 `grace-code` 现在的核心链更复杂：

- `SessionRuntime.run_session()`
- `spawn_agent()`
- `SessionStore`
- `EventLog`
- approval / plan mode / worktree review

如果我们照搬，就会把业务逻辑重新塞回 router。

`grace-code` 应该坚持：

- router 不决定 runtime 语义
- router 只调用 application/service

## 3.3 不能照搬它的“前端 tabs 很多”的做法

`claw-code-agent` 现在页面 tab 很多：

- Chat
- Tasks
- Plan
- Memory
- History
- Background
- Worktree
- Skills
- Accounts
- Remote
- MCP
- Plugins
- Ask
- Workflows
- Search
- Triggers
- Teams
- Diag

见：

- [src/gui/static/index.html](D:/StudyProjects/ProjectBench/claw-code-agent/src/gui/static/index.html:187)

这对它是功能库存式页面，但对 `grace-code` 的 MVP 会过重。

`grace-code` 第一版不要学“全功能标签页”，而要学“最关键 5 块面板”。

---

## 4. 给 grace-code 的 Web MVP 建议

## 4.1 MVP 页面结构

建议第一版只做下面几个视图：

### 视图 1：Sessions

左侧列表：

- 最近 sessions
- 当前状态
- 修改时间
- 任务摘要

对应你现在已有的基础：

- `SessionStore.list_messages()`
- `SessionStore.get_session()`
- `SessionStore.claim_pending_agent_notifications()`

### 视图 2：Chat / Timeline

中间主视图：

- 用户任务
- assistant 输出
- tool.call
- tool.result
- reflection
- final result

这里应该优先消费你自己的结构化 event，而不是 terminal 文本。

### 视图 3：Run Config

右侧配置：

- repo
- agent
- intent
- provider / model
- max steps
- auto approve

这块可以直接借鉴 `claw-code-agent` 的 Settings 面板思路，但字段要按 `grace-code` 自己的 runtime 来。

### 视图 4：Plan

`grace-code` 比 `claw-code-agent` 更该优先做这个，因为你现在有明显的 plan-mode 体系。

要展示：

- plan contract
- 当前 plan 状态
- approve / reject / replan

### 视图 5：Subagent / Worktree

这是 `grace-code` 的差异化能力，第一版就应该露出来：

- child sessions
- subagent tree
- preserved worktrees
- inspect / apply / discard / retain

---

## 4.2 MVP 后端结构

建议目录：

```text
grace-code/
├─ app/
│  ├─ application/
│  ├─ approvals/
│  ├─ events/
│  └─ queries/
├─ server/
│  ├─ main.py
│  ├─ routers/
│  ├─ schemas/
│  └─ dependencies.py
└─ web/
```

核心原则：

- `SessionRuntime` 继续做唯一 Agent 主链
- `server` 不直接 import CLI 交互逻辑
- `web` 不直接读 SQLite 或 JSONL
- 所有前端展示都经过 query/service 层

---

## 4.3 MVP API 清单

最小够用的一组：

- `POST /api/sessions`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`
- `GET /api/sessions/{session_id}/events`
- `GET /api/sessions/{session_id}/children`
- `POST /api/sessions/{session_id}/approve`
- `POST /api/sessions/{session_id}/reject`
- `POST /api/sessions/{session_id}/cancel`
- `WS /api/ws/sessions/{session_id}`

这套清单足够支撑 MVP 页面，不需要一开始就做 `claw-code-agent` 那么多 API 面。

---

## 5. 给前端 vibecoding 的具体约束

如果前端要靠 vibecoding，这里一定要先把边界钉住，否则很容易越写越散。

## 5.1 只允许前端消费稳定 contract

前端只能依赖：

- OpenAPI / Pydantic schema
- 结构化 event types
- 固定字段名

前端不能依赖：

- CLI 控制台文本
- renderer 的 ANSI 输出
- SQLite 表细节
- `EventLog` 内部原始 payload 结构

## 5.2 先给前端明确 5 个组件，不要让它自由发散

建议固定成：

- `SessionSidebar`
- `RunConfigPanel`
- `TimelinePanel`
- `PlanPanel`
- `SubagentPanel`

vibecoding 可以在这些组件内部提速，但不要让它自由设计信息架构。

## 5.3 事件协议必须先定，再让前端开工

建议事件类型：

- `session.started`
- `agent.message`
- `agent.thought`
- `agent.reflection`
- `tool.call`
- `tool.result`
- `approval.required`
- `approval.resolved`
- `subagent.spawned`
- `subagent.completed`
- `session.completed`
- `session.failed`
- `session.cancelled`

这一步没定，前端就会自己发明结构，后面一定返工。

## 5.4 页面第一版不要追求“框架高级感”

对 `grace-code` 的 MVP，更重要的是：

- 可查看会话
- 可启动任务
- 可看过程
- 可审批
- 可取消
- 可看 subagent/worktree

而不是：

- 炫动效
- 重状态库
- 复杂主题系统
- 组件库全家桶

---

## 6. 对 grace-code 的落地建议

## 6.1 推荐借鉴路线

建议学习 `claw-code-agent` 的这三点：

1. GUI 是本地工作台，不是另一个产品
2. API 和状态装配在后端，前端只是消费者
3. 页面先按工作台面板切，不按炫技框架切

## 6.2 推荐避免的路线

不要走下面这些路：

1. Web 后端通过 subprocess 调 `python -m entry.cli run`
2. 前端直接吃控制台输出
3. 前端直接读 `sessions.db`
4. 一开始就做十几个 tabs 的大而全页面
5. 在 router 里直接写复杂 runtime 逻辑

## 6.3 推荐的第一阶段目标

第一阶段只要做到：

- 能创建 session
- 能查看 session 列表
- 能看实时 timeline
- 能 approve / reject
- 能看 plan
- 能看 child/subagent/worktree

这时就已经是一个真正可用的 `grace-code` Web MVP。

---

## 7. 对当前代码库的下一步建议

如果按本文思路推进，下一步最合理的是：

### Step 1

先在 `grace-code` 里新增：

- `app/application/agent_application.py`
- `app/events/event_models.py`
- `app/events/event_bus.py`
- `app/queries/session_query_service.py`

### Step 2

再新增：

- `server/main.py`
- `server/routers/sessions.py`
- `server/routers/websocket.py`
- `server/schemas/session.py`
- `server/schemas/event.py`

### Step 3

最后再起：

- `web/` React 工程

这样前端就可以在一个稳定 contract 上做 vibecoding，而不是反过来逼后端适配前端草稿。

---

## 8. 一句话总结

`claw-code-agent` 给 `grace-code` 最重要的启发不是“照抄它的 GUI”，而是：

**先把后端的 Agent 工作台边界做清楚，再让前端快速长出来。**

对 `grace-code` 来说，这条路线最稳，也最符合你们现在“后端自己懂设计、前端先快速做 MVP”的现实分工。

