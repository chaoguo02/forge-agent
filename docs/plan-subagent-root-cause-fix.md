# Plan + Subagent 根因分析与系统性修复方案

> 从全局视角梳理所有缺口，理清因果关系后再逐项实施。
> 关联文档：[[plan-subagent-flow-gaps]] [[subagent-plan-mode-design]]

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React)                           │
│                                                                     │
│  PlanView.tsx          ChatView.tsx          SubagentDetail.tsx     │
│       │                     │                       │               │
│       │ planApproval        │ chat + subagent       │ child detail  │
│       ▼                     ▼                       ▼               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  chatStore.ts (Zustand)                                     │   │
│  │  - sessionStateById[sid].planApproval                       │   │
│  │  - sessionStateById[sid].backgroundAgents                   │   │
│  │  - sessionStateById[sid].toolApprovals                     │   │
│  │  - connectWs(sid) → WebSocket                               │   │
│  │  - handleWsEvent(ev) → dispatch by ev.type                   │   │
│  │  - sendChat / approvePlan / rejectPlan                       │   │
│  └────────────────────────┬────────────────────────────────────┘   │
│                           │ WS: /api/ws/sessions/{sid}              │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────┼─────────────────────────────────────────┐
│                          BACKEND (FastAPI)                          │
│                           │                                         │
│  ┌────────────────────────┼────────────────────────────────────┐   │
│  │  server/routers/sessions.py                                  │   │
│  │  - POST /{sid}/messages → run_chat_async                    │   │
│  │  - POST /{sid}/approve /reject                              │   │
│  └────────────────────────┬────────────────────────────────────┘   │
│                           ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  server/services/agent_service.py                           │   │
│  │  - run_chat_async(_is_plan detection)                       │   │
│  │  - _run_and_notify(): emit plan_ready / status              │   │
│  └────────────────────────┬────────────────────────────────────┘   │
│                           ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  agent/session/runtime.py (SessionRuntime)                  │   │
│  │  - run_session(): primary agent execution                   │   │
│  │  - spawn_agent(): MONKEY-PATCHED by runtime_spawn.py ⚠      │   │
│  │  - _execute_child_session(): MONKEY-PATCHED ⚠               │   │
│  └────────────┬──────────────────────┬─────────────────────────┘   │
│               │                      │                              │
│               ▼                      ▼                              │
│  ┌─────────────────────┐  ┌──────────────────────────────────┐    │
│  │ agent/session/       │  │ agent/session/                    │    │
│  │ runtime_spawn.py     │  │ subagent.py                       │    │
│  │ (ACTIVE - monkey     │  │ run_child_agent()                 │    │
│  │  patched version)    │  │ - web_confirm_callback injection  │    │
│  │ ⚠ MISSING features  │  │ - event routing to parent WS      │    │
│  └─────────────────────┘  │ - pipeline state inheritance       │    │
│                           │ - circuit breaker per subagent     │    │
│                           └──────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**关键架构事实：**

1. `runtime.py:2055-2058` 用 monkey-patch 将 `runtime_spawn.py` 的版本覆盖到 `SessionRuntime` 上。
   原版 `runtime.py` 的 `spawn_agent` / `_execute_child_session` 是**死代码**。

2. `runtime_spawn.py` 是原始 `runtime.py` 版本的**不完整提取**，缺失大量逻辑。

3. `subagent.py:run_child_agent()` 已经实现了许多高级功能（web_confirm_callback、父 WS 事件路由、pipeline state 继承），
   但这些功能依赖调用方（`_execute_child_session`）传入正确的参数。

---

## 二、问题域 A：runtime_spawn.py 是不完整的提取

### A.1 为什么有两个版本？

`runtime_spawn.py` 是为"内容内聚"从 `runtime.py` 中拆出来的（见 `docs/content-cohesion-plan.md`）。
拆分方式是：复制代码到新文件 → 在 `runtime.py` 底部 import 并 monkey-patch。
但复制过程**遗漏了大量逻辑**，且后续 `runtime.py` 原版的更新没有同步到 `runtime_spawn.py`。

### A.2 `spawn_agent` 函数差异对比

| # | 差异项 | 原版 runtime.py | 提取版 runtime_spawn.py | 影响 |
|---|--------|:---:|:---:|------|
| 1 | `child_agent_type` 赋值 | ✅ L1084-1088 | ✅ 已修复 L68-72 | — |
| 2 | f-string 前缀 | ✅ `f"...{var}"` | ❌ 缺少 `f` | `parent_session_id` 不插值 |
| 3 | `cancellation_token` 类型校验 | ✅ L1027-1028 | ❌ 缺失 | 类型错误延迟暴露 |
| 4 | `parent_policy` 类型校验 | ✅ L1029-1031 | ❌ 缺失 | 类型错误延迟暴露 |
| 5 | `origin` 类型转换 | ✅ L1034-1035 | ❌ 缺失 | 字符串 origin → `.value` 崩溃 |
| 6 | `spawn_context` 校验 | ✅ L1070-1083 | ❌ 缺失 | fork 时可能用错 parent/repo/model |
| 7 | metadata 完整性 | ✅ 11 个字段 | ❌ 仅 1 个字段 | 子 session 元数据严重缺失 |
| 8 | 权限继承 `_resolve_child_permission_mode` | ✅ L1164-1168 | ❌ 缺失 | 子 agent 权限模式不正确 |
| 9 | MCP agent-scoped 工具 | ✅ L1170-1173 | ❌ 缺失 | 子 agent 缺少 MCP 工具 |
| 10 | background cleanup 传递 | ✅ L1188-1204 | ❌ 缺失 | MCP 连接泄漏 |

### A.3 `_execute_child_session` 函数差异对比

| # | 差异项 | 原版 runtime.py | 提取版 runtime_spawn.py | 影响 |
|---|--------|:---:|:---:|------|
| 11 | Fork 工具契约校验 | ✅ L1237-1270 | ❌ 缺失 | fork resume 时不验证 contract 一致性 |
| 12 | 父 pipeline state 快照 | ✅ L1271-1275 | ❌ 缺失 | 子 agent 无法继承父的 deny/allow 规则 |
| 13 | `parent_pipeline_state` 传参 | ✅ L1296 | ❌ 未传 | subagent.py 的继承逻辑不工作 |
| 14 | `_cancellation_tokens.pop` 清理 | ✅ L1352-1354 | ❌ 缺失 | 内存泄漏 |

### A.4 影响评估

- **#6 (spawn_context 校验缺失)**: Fork 子 agent 可能连接到错误的父 session，工具契约不匹配会导致运行时崩溃。
- **#7 (metadata 缩水)**: 缺少 `parent_policy`、`budget_tokens`、`model_name` 等关键元数据，导致 fork resume 和调试都无法进行。
- **#8 (权限继承缺失)**: 子 agent 使用默认权限模式而非父的继承模式。Plan agent 的子 agent 可能获得写入权限。
- **#11-13 (pipeline 状态)**: `subagent.py:168-177` 的 pipeline 继承代码因为缺少 `parent_pipeline_state` 参数而形同虚设。

---

## 三、问题域 B：Plan ↔ PlanView 连接脆弱

### B.1 数据流追踪

```
用户点击 "Start Plan Analysis"
  │
  ├─ PlanView.tsx:81 → api.chat(activeId, prompt, "analysis")
  │   POST /api/sessions/{id}/messages  body={prompt, intent:"analysis"}
  │
  ├─ sessions.py:387: effective_agent = body.agent_name or rec.agent_name
  │   ⚠ BUG: body.agent_name 为 None → effective_agent == rec.agent_name
  │   下面的 agent_name 更新 if 分支永远不会执行！
  │
  ├─ sessions.py:412: run_chat_async(session_id, prompt, agent_name=effective_agent, intent="analysis")
  │
  ├─ agent_service.py:552: _is_plan = agent_name=="plan" or intent=="analysis" → True ✅
  │   agent_service.py:558: if _is_plan: agent_name = "plan" ✅ (运行时纠正)
  │
  ├─ runtime.py:739: run_session(agent_name="plan", ...) → 执行 plan agent
  │   内部 agent.run() → ExitPlanMode tool → contract 存入 _accumulated_plan_contract
  │
  ├─ agent_service.py:649-680: _is_plan → 发送 WsPlanReady 事件
  │   EventBus.publish_typed(session_id, WsPlanReady(plan_text=..., contract=..., ...))
  │   ⚠ 仅当存在 WS 订阅者时才发送！没有订阅者 → 事件被静默丢弃。
  │
  ├─ chatStore.ts:291: handleWsEvent → ev.type === "plan_ready"
  │   → patchSession(sid, { planApproval: { planText, isWaiting: true } })
  │
  └─ PlanView.tsx:27: planApproval = selectSessionUi(s, activeId).planApproval
      hasPlan = planApproval?.isWaiting → 显示 Approve/Reject UI
```

### B.2 识别到的断裂点

| # | 断裂点 | 位置 | 症状 |
|---|--------|------|------|
| B1 | **session agent_name 不更新到 DB** | [sessions.py:387-396](server/routers/sessions.py#L387) | DB 记录永远是初始值("build")，`isPlanSession` 判断不准 |
| B2 | **plan_ready 无订阅者时静默丢弃** | [event_bus.py:364-366](server/services/event_bus.py#L364) | WS 重连期间完成的 plan → event 丢失 |
| B3 | **planApproval 仅内存状态，无持久化** | [chatStore.ts:291-307](web/src/stores/chatStore.ts#L291) | 刷新页面后 planApproval 消失 |
| B4 | **PlanView 仅展示纯文本** | [PlanView.tsx:108](web/src/components/PlanView.tsx#L108) | contract JSON 已下发但未渲染结构化卡片 |
| B5 | **审批后 session agent_name 残留** | [approvals.py:95](server/routers/approvals.py#L95) | approve 后启动 build agent 但 session DB 中 agent_name 仍为旧值 |
| B6 | **Reject 使用 rec.agent_name** | [approvals.py:174](server/routers/approvals.py#L174) | DB 中 agent_name="build" → re-plan 用 build agent 运行 |
| B7 | **planApproval 清除时机不一致** | [chatStore.ts:209-214](web/src/stores/chatStore.ts#L209) | `status:completed` 清除 planApproval 但 plan 会话不发该事件 |

### B.3 影响评估

**B1-B2-B3 组合效应最严重：**
1. 用户在 PlanView 点 "Start Plan Analysis"
2. WS 连接正常 → plan_ready 收到 → PlanView 显示审批界面 ✅
3. 但如果用户在 plan 运行期间刷新了页面：
   - WS 重连期间 plan 完成 → plan_ready 丢失 → PlanView 永远看不到结果
   - 即使用户重新连接 WS → 没有 replay 机制 → planApproval 为 null
   - PlanView 显示 "No plan has been generated yet"

**B4**: contract JSON 有结构化数据（goal/steps/verification）但前端只显示 `planText` 纯文本，浪费了结构化信息。

**B5-B6**: 审批后如果 DB 中 agent_name 不正确，后续操作（reject re-plan）会用错 agent 定义。

---

## 四、问题域 C：Subagent 执行断路

### C.1 web_confirm_callback 分析

`subagent.py:180-223` 已有正确的实现：
```python
if session_runtime is not None and getattr(session_runtime, '_is_web_mode', False):
    _child_broker = session_runtime._ensure_approval_broker(agent_id)
    # ... 创建 _child_confirm 回调 ...
    _child_pipeline._web_confirm_callback = _child_confirm
```

但这段代码依赖一个**未定义的变量** `parent_session_id`（第 187 行）：
```python
_parent_session = parent_session_id  # ← 未定义！函数签名中无此参数
```

这是一个和 `child_agent_type` 同类的 bug——提取或重构时遗漏了。

### C.2 事件路由分析

`subagent.py:354-374` 已实现子 agent 事件路由到父 WS：
```python
def _append_and_emit(event):
    event.child_session_id = agent_id
    event.session_id = _captured_session_id  # = parent_session_id or agent_id
    ...
```

这是正确的：子 agent 的事件会以父 session_id 发布，前端订阅了父 session 的 WS 就能收到。

但 `runtime_spawn.py:_execute_child_session` 没有设置 `event_callback` 将子 agent 事件桥接到 EventBus。
原版 `runtime.py:_execute_child_session` 也没有——这个功能完全在 `subagent.py` 内部实现，
通过 `session_runtime._event_callback` 参数。`_execute_child_session` 传入的 `event_callback=self._event_callback`
是 SessionRuntime 级别的回调，但它需要与 EventBus 集成。

### C.3 影响评估

- **parent_session_id 未定义**: subagent.py 第 187 行会在 Web 模式下崩溃，导致子 agent 无法获得 web_confirm_callback。
  子 agent 的工具调用在 Layer 6 会走 fallback 路径（TTY 或 DENY），在纯 Web 模式下被拒绝。
- 这可以解释 "Subagent 'explore' failed" 的另一个可能原因——不只是 `child_agent_type` 问题，
  工具调用被拒也会导致子 agent 失败。

---

## 五、根因分析

### 根因 1：代码拆分缺少完整性验证

`runtime.py` → `runtime_spawn.py` 的拆分是手动复制粘贴，没有 diff 校验工具。
后续对 `runtime.py` 原版的功能增强也没有同步到提取版。

**教训：** 拆分后应立即删除原版的类方法定义（而非保留死代码），或使用自动化工具保证两边一致。

### 根因 2：Plan 状态无持久化，纯依赖 WS 推送

当前 plan 流程是 fire-and-forget：
- 发起 plan → 异步执行 → WS 推送结果
- 没有 REST API 可以查询 "这个 session 是否有待审批的 plan"
- 前端 `planApproval` 纯内存状态，不持久化

**教训：** 关键状态变更应同时持久化。`plan_ready` 事件应同时写入 session metadata，
前端应同时支持 "WS 实时推送" 和 "REST 轮询/查询" 两种获取方式。

### 根因 3：agent_name 在多层不一致

agent_name 在系统中以多种形式存在：
- Session 记录的 `agent_name` (DB)
- `run_chat_async` 的参数 `agent_name`
- `run_session` 内部的 `_effective_agent`
- 前端 `activeDetail.agent_name`

这些值可能在运行时被临时覆盖（如 intent=analysis → agent_name="plan"），但 DB 不更新。
导致前端和后续操作看到的是过时值。

**教训：** agent_name 应该是**单一权威来源**。运行时覆盖应在覆盖后写回 DB。

### 根因 4：subagent.py 的 parent_session_id 未定义 (🔴 运行时崩溃)

**文件：** [subagent.py:187](agent/session/subagent.py#L187)

```python
_parent_session = parent_session_id  # ← NameError! 函数签名中无此参数
```

`run_child_agent` 函数签名（第 61-82 行）中没有 `parent_session_id` 参数。正确的来源是 `session_record.parent_id`（当 session_record 不为 None 时）。

这个 bug 意味着：**在 Web 模式下，所有子 agent 的 web_confirm_callback 创建都会崩溃**。
子 agent 的工具调用在 Layer 6 会走 fallback 路径（DENY），导致工具调用被静默拒绝。

与 `runtime_spawn.py` 的 `child_agent_type` 问题同源——代码拆分/重构时参数传递链断裂，且没有类型检查器捕获。

### 根因 5：EventBus 无订阅者时静默丢弃事件

**文件：** [event_bus.py:364-366](server/services/event_bus.py#L364)

```python
def publish_typed(self, session_id: str, event: Any) -> None:
    sub = self._sessions.get(session_id)
    if sub is not None and sub.has_subscribers:  # ← 无订阅者 → 静默丢弃!
        sub.publish(event.to_dict())
```

`plan_ready`、`subagent_start/stop` 等关键状态变更事件，在前端未连接 WS 时会被静默丢弃。
没有持久化或重放机制。刷新页面前未收到的 plan_ready → 永远收不到。

### 根因 6：sendChat 从不发送 agent_name，导致 DB 不更新

**文件：** [chatStore.ts:464](web/src/stores/chatStore.ts#L464) → [sessions.ts:62](web/src/api/sessions.ts#L62)

```typescript
// chatStore sendChat:
await api.chat(sessionId, prompt, intent, currentMode);
//                                        ^^^^^^^^^^^ 这个参数是 currentMode，不是 agent_name!

// api.chat 函数签名:
export function chat(sessionId, prompt, intent?, agentName?) {
  if (agentName) body.agent_name = agentName;  // ← 永远不设置
}
```

前端在模式切换时只传 `intent`，从不传 `agent_name`。而服务端 `sessions.py:387` 的
`effective_agent = body.agent_name or rec.agent_name` 永远走到 `rec.agent_name` 分支。
DB 中的 agent_name 从创建后保持不变。

**结果：** 无论用户切换多少次 plan/build 模式，DB 中始终是初始值 "build"。

---

## 六、修复方案

### 策略

**合并而非修补**：将 `runtime_spawn.py` 缺失的逻辑补充完整（而非给每个 gap 打补丁）。
`runtime.py` 原版的方法定义应标记为 DEPRECATED 或直接删除以消除混淆。

### Phase 1：修复运行时崩溃 (P0)

#### Fix 1.1: subagent.py — 修复 parent_session_id 未定义 (🔴 运行时崩溃)

**文件：** `agent/session/subagent.py`，第 187 行

**问题：** `parent_session_id` 在 `run_child_agent` 函数签名中不存在。在 Web 模式下创建子 agent 时，第 187 行会抛出 `NameError`，导致子 agent 无法获得 web_confirm_callback，工具调用被静默拒绝。

**修改：**
```python
# 第 187 行，替换：
_parent_session = parent_session_id

# 改为：
_parent_session = (
    session_record.parent_id
    if session_record is not None and session_record.parent_id is not None
    else agent_id
)
```

**验证：**
1. Web 模式下通过 AgentTool 创建子 agent → 子 agent 的工具调用应触发前端审批弹窗
2. 检查日志中不再出现 `name 'parent_session_id' is not defined`

---

#### Fix 1.2: runtime_spawn.py — 补充 spawn_agent 缺失逻辑

**文件：** `agent/session/runtime_spawn.py`，`spawn_agent` 函数

逐项补充（与原版 runtime.py:1020-1205 对齐）：

**(a) f-string 修复（第 50 行）**
```python
# 原代码：
raise ValueError("Unknown v2 session: {parent_session_id}")

# 改为：
raise ValueError(f"Unknown v2 session: {parent_session_id}")
```

**(b) 补充类型校验（在第 47 行后插入）**
```python
if not isinstance(cancellation_token, CancellationToken):
    raise TypeError("child cancellation_token must be a CancellationToken")
if not isinstance(parent_policy, PhasePolicy):
    raise TypeError("child parent_policy must be a PhasePolicy")
```

**(c) 补充 origin 类型转换（在第 47 行后插入）**
```python
if not isinstance(origin, DelegationOrigin):
    origin = DelegationOrigin(origin)
```

**(d) 补充 spawn_context 校验（在第 77 行 `_repo = ...` 之后插入）**
```python
if spawn_context is not None:
    if not isinstance(spawn_context, AgentSpawnContext):
        raise TypeError("spawn_context must be an AgentSpawnContext")
    if spawn_context.parent_session_id != parent.id:
        raise ValueError("spawn context parent does not match the session")
    if spawn_context.parent_agent_name != parent.agent_name:
        raise ValueError("spawn context agent does not match the session")
    if self._require_project_scope(spawn_context.repo_path) != _repo:
        raise ValueError("spawn context repo does not match the session")
    if (
        is_fork
        and spawn_context.model_name != self._backend.model_name
    ):
        raise ValueError("Fork model must match the parent model")
```

**(e) 补充完整 metadata（替换第 85 行 `metadata={"entrypoint": origin.value}`）**
```python
metadata={
    "entrypoint": origin.value,
    "agent_kind": request.agent_kind.value,
    "context_origin": request.context_origin.value,
    "workspace_mode": request.workspace_mode.value,
    "intent": definition.intent.value,
    "requested_budget_tokens": budget_tokens,
    "budget_tokens": child_contract.budget_tokens,
    "max_steps": child_contract.max_steps,
    "parent_policy": parent_policy.to_dict(),
    "parent_snapshot_fingerprint": (
        spawn_context.conversation.fingerprint
        if spawn_context is not None else None
    ),
    "parent_snapshot_message_count": (
        len(spawn_context.conversation.messages)
        if spawn_context is not None else 0
    ),
    "model_name": (
        spawn_context.model_name
        if spawn_context is not None else self._backend.model_name
    ),
    "parent_tool_schemas": (
        [
            {
                "name": schema.name,
                "description": schema.description,
                "parameters_json": schema.parameters_json,
            }
            for schema in spawn_context.tool_schemas
        ]
        if is_fork and spawn_context is not None
        else []
    ),
},
```

**(f) 补充权限继承（在第 103 行 `_fire_hook` 之后插入）**
```python
_child_permission_mode = self._resolve_child_permission_mode(
    parent_definition,
    definition if request.agent_kind is AgentKind.NAMED_SUBAGENT else None,
)
if _child_permission_mode:
    child.metadata["permission_mode_override"] = _child_permission_mode
```

**(g) 补充 MCP 工具连接（在第 103 行 _fire_hook 之后插入）**
```python
_agent_mcp_tools = []
if self._mcp_integration is not None and not is_fork:
    _agent_mcp_tools = self._mcp_integration.connect_agent_servers(definition)
```

**(h) 补充 background cleanup（修改 `_start_background_execution` 调用）**
```python
# 在第 106-115 行之间插入 cleanup 构建
_need_mcp_cleanup = bool(_agent_mcp_tools) and self._mcp_integration is not None
cleanup = None
if _need_mcp_cleanup:
    cleanup = lambda: self._mcp_integration.disconnect_agent_servers(definition)

if request.execution_placement is ExecutionPlacement.FOREGROUND:
    try:
        return execute()
    finally:
        if cleanup is not None:
            cleanup()
return self._start_background_execution(
    parent=parent, child=child, agent_name=definition.name,
    execute=execute, cleanup=cleanup,
)
```

---

#### Fix 1.3: runtime_spawn.py — 补充 _execute_child_session 缺失逻辑

**文件：** `agent/session/runtime_spawn.py`，`_execute_child_session` 函数

**(a) Fork 工具契约校验（在 `try:` 块内，`inherited_registry` 赋值之后、`run_child_agent` 调用之前插入）**
```python
if request.agent_kind is AgentKind.FORK:
    inherited_registry = self._build_registry_for_session(
        parent_definition, child,
    ).with_phase_policy(parent_policy)
    if request.context_origin is ContextOrigin.PARENT_SNAPSHOT:
        if spawn_context is None:
            raise ValueError("Fork spawn requires a live parent snapshot")
        live_schemas = tuple(
            ToolSchemaSnapshot.capture(schema)
            for schema in inherited_registry.get_schemas()
        )
        if live_schemas != spawn_context.tool_schemas:
            raise ValueError("Fork tool contract changed after the parent model call")
    else:
        raw_schemas = child.metadata.get("parent_tool_schemas")
        if not isinstance(raw_schemas, list) or not raw_schemas:
            raise ValueError("Fork resume requires its persisted tool contract")
        expected_schemas = tuple(
            ToolSchemaSnapshot(
                name=str(item["name"]),
                description=str(item["description"]),
                parameters_json=str(item["parameters_json"]),
            )
            for item in raw_schemas if isinstance(item, dict)
        )
        live_schemas = tuple(
            ToolSchemaSnapshot.capture(schema)
            for schema in inherited_registry.get_schemas()
        )
        if live_schemas != expected_schemas:
            raise ValueError("Fork tool contract changed since its prior generation")
```

**(b) 父 pipeline state 快照（在 `inherited_registry` 块之后插入）**
```python
_parent_pipeline = getattr(self._base_registry, '_permission_pipeline', None)
_inherited_state = _parent_pipeline.get_inheritable_state() if _parent_pipeline else {}
```

**(c) `parent_pipeline_state` 传入 `run_child_agent`**

在 `run_child_agent()` 调用中增加参数：
```python
parent_pipeline_state=_inherited_state,
```

**(d) `_cancellation_tokens.pop` 清理（在 `finally:` 块末尾添加）**
```python
self._cancellation_tokens.pop((child.id, child.generation), None)
```

---

### Phase 2：修复 Plan ↔ PlanView 连接 (P1)

#### Fix 2.1: session agent_name 同步到 DB

**文件：** `server/routers/sessions.py`

**问题：** 当 intent=analysis 时，`effective_agent` 不变，DB 不更新。

**修改策略：** 在调用 `run_chat_async` 之前，根据 intent 决定是否更新 session 的 agent_name。

```python
# 在 sessions.py:387-396 区域修改

# --- 修改前 ---
effective_agent = body.agent_name or rec.agent_name
if effective_agent != rec.agent_name:
    try:
        service.session_service.update_agent_name(session_id, effective_agent)
    except Exception:
        pass

# --- 修改后 ---
effective_agent = body.agent_name or rec.agent_name

# When intent=analysis, force agent_name to "plan" so the DB record
# stays consistent with what run_chat_async will actually execute.
from agent.task import TaskIntent
_resolved_intent = TaskIntent(body.intent) if body.intent else None
if (
    _resolved_intent is TaskIntent.ANALYSIS
    and effective_agent != "plan"
):
    effective_agent = "plan"

if effective_agent != rec.agent_name:
    try:
        service.session_service.update_agent_name(session_id, effective_agent)
    except Exception:
        pass
```

#### Fix 2.2: PlanView 支持从 session summary 恢复 plan 显示

**文件：** `web/src/components/PlanView.tsx`

**问题：** 刷新页面后 `planApproval` 丢失（纯内存状态）。即使 session 已有完成
的 plan（`status=completed`, `agent_name=plan`, `summary` 非空），PlanView 也只在 State D
中展示纯 summary，不提供 Approve 按钮。

**当前 PlanView 四种状态的行为：**
| 状态 | 条件 | 行为 |
|------|------|------|
| A | `!activeId` | 空状态提示 |
| B | `activeId && !hasPlan && !isPlanSession` | "Start Plan Analysis" 按钮 |
| C | `hasPlan && planApproval` | Approve/Reject UI（仅 WS plan_ready 事件触发） |
| D | `isPlanSession && !hasPlan` | 只读 plan summary 展示，无 Approve 按钮 |

**问题：** 外部完成（CLI 创建、WS 重连期间完成）的 plan session 落在 State D，
用户看到 plan 文本但无法 approve。

**策略：** State D 在 session 已完成且有 summary 时，增加 Approve 按钮。
这样无论 `planApproval` 是否存在，用户都可以从 summary 恢复审批流程。

```tsx
// 修改 State D (当前约第 137-158 行)
// 当 activeDetail?.status === "completed" && activeDetail?.summary 时
// 额外显示 Approve 按钮

{activeId && isPlanSession && !hasPlan && activeDetail?.status === "completed" && activeDetail?.summary && (
  <div className="plan-card plan-card-prominent">
    <div className="plan-card-header">
      <div>
        <div className="summary-label">Plan Completed</div>
        <h3 className="plan-card-title">Generated Plan</h3>
      </div>
      <span className="trace-pill">completed</span>
    </div>
    <div className="plan-scroll">
      <pre className="plan-pre">{activeDetail.summary}</pre>
    </div>
    <div className="plan-card-footer">
      <div className="summary-subtle">
        This plan was generated previously. Approve to execute it, or send feedback to revise.
      </div>
      <div className="plan-actions">
        <button className="btn-approve" type="button"
          disabled={isRunning}
          onClick={() => approvePlan()}>
          Approve & Build
        </button>
      </div>
    </div>
  </div>
)}
```

#### Fix 2.3: approve/reject 确保使用正确的 agent_name

**文件：** `server/routers/approvals.py`

**(a) approve 后更新 agent_name (第 95 行)**
```python
# 在 run_chat_async 之前
try:
    service.session_service.update_agent_name(session_id, "build")
except Exception:
    pass
```

**(b) reject re-plan 使用 "plan" 而非 rec.agent_name (第 174 行)**
```python
# 原代码：
service.run_chat_async(
    session_id=session_id,
    prompt=feedback,
    agent_name=rec.agent_name,  # ← 可能是 "build"
    intent="analysis",
)

# 改为：
service.run_chat_async(
    session_id=session_id,
    prompt=feedback,
    agent_name="plan",
    intent="analysis",
)
# 同时更新 DB：
try:
    service.session_service.update_agent_name(session_id, "plan")
except Exception:
    pass
```

---

### Phase 3：清理死代码 + 前端 agent_name (P2)

#### Fix 3.1: 删除 runtime.py 中的死代码版本

`runtime.py:1006-1205`（`spawn_agent` 方法定义）和 `runtime.py:1207-1354`（`_execute_child_session` 方法定义）
是死代码——它们在类定义后立即被 monkey-patch 覆盖。

将它们替换为注释和 `raise NotImplementedError` 守卫：

```python
def spawn_agent(self, ...):
    """Deprecated: implementation moved to runtime_spawn.py via monkey-patch."""
    raise NotImplementedError(
        "spawn_agent should be patched by runtime_spawn.py import"
    )

def _execute_child_session(self, ...):
    """Deprecated: implementation moved to runtime_spawn.py via monkey-patch."""
    raise NotImplementedError(
        "_execute_child_session should be patched by runtime_spawn.py import"
    )
```

这防止未来有人在死代码上修改而不知道它不会被执行。

#### Fix 3.2: 前端 sendChat 发送 agent_name

**文件：** `web/src/stores/chatStore.ts` 的 `sendChat` 函数

**问题：** 当用户切换模式（Plan ↔ Build）时，前端只传 `intent` 不传 `agent_name`。
服务器无法将 DB 中的 agent_name 从 "build" 更新为 "plan"。

**修改：**
```typescript
// chatStore.ts sendChat 中，将：
await api.chat(sessionId, prompt, intent, currentMode);

// 改为：
const agentName = currentMode === "plan" ? "plan" : "build";
await api.chat(sessionId, prompt, intent, agentName);
```

这样配合 Fix 2.1（服务端检测 intent=analysis 时也更新 agent_name），DB 中的 agent_name
会在用户首次使用 plan 模式时正确更新。

---

## 七、实施顺序

```
Batch 1 (P0 - 崩溃修复):
  ├─ Fix 1.1: subagent.py parent_session_id 未定义 (🔴 NameError)
  ├─ Fix 1.2a-h: runtime_spawn.py spawn_agent 补完
  └─ Fix 1.3a-d: runtime_spawn.py _execute_child_session 补完

Batch 2 (P1 - Plan 连接修复):
  ├─ Fix 2.1: sessions.py agent_name 同步
  ├─ Fix 2.2: PlanView.tsx 回退状态
  ├─ Fix 2.3: approvals.py agent_name 正确化
  └─ Fix 2.4: chatStore.ts sendChat 传 agent_name

Batch 3 (P2 - 清理):
  ├─ Fix 3.1: 删除 runtime.py 死代码
  └─ Fix 3.2: 前端 sendChat 发送 agent_name
```

---

## 八、验证策略

### Batch 1 验证

1. **spawn_context 校验**：构造无效的 spawn_context（错误的 parent_id），确认抛出 ValueError
2. **f-string**：检查日志中 `Unknown v2 session:` 消息是否正确包含 session_id
3. **metadata 完整性**：创建 fork 子 agent，检查 DB 中 metadata JSON 是否包含所有字段
4. **权限继承**：从 plan agent 创建子 agent，验证子 agent registry 中权限模式为 "plan"
5. **MCP 工具**：验证命名子 agent 可访问 agent-scoped MCP 工具
6. **pipeline state**：验证子 agent 继承了父的 deny/allow 规则
7. **cancellation 清理**：创建并完成子 agent，检查 `_cancellation_tokens` 是否包含子 agent key

### Batch 2 验证

1. **agent_name 同步 (Fix 2.1 + 2.4)**：用 intent=analysis 发消息 → 检查 DB 中 session.agent_name 变为 "plan"
2. **PlanView 回退 (Fix 2.2)**：在 plan 完成后刷新页面 → PlanView 应显示已完成 plan 卡片 + Approve 按钮
3. **approve 后 agent_name (Fix 2.3a)**：approve plan → DB 中 session.agent_name 变为 "build"
4. **reject re-plan (Fix 2.3b)**：reject plan → re-plan 使用 plan agent 而非 build agent

### Batch 3 验证

1. **死代码移除**：确认 runtime.py 的 spawn_agent 方法调用会抛出 NotImplementedError
2. **sendChat agent_name**：在 ChatView 中切换 mode=plan 后发送消息 → 检查 HTTP 请求体中包含 `agent_name: "plan"`
3. **功能不变**：所有现有 subagent 测试通过

---

## 九、受影响文件清单

| 文件 | 批次 | 修改类型 |
|------|------|----------|
| `agent/session/subagent.py` L187 | Batch 1 | 修复 NameError |
| `agent/session/runtime_spawn.py` (spawn_agent) | Batch 1 | 补完 8 项缺失逻辑 |
| `agent/session/runtime_spawn.py` (_execute_child_session) | Batch 1 | 补完 4 项缺失逻辑 |
| `server/routers/sessions.py` L387-396 | Batch 2 | 修复 agent_name DB 同步 |
| `web/src/components/PlanView.tsx` | Batch 2 | 增加回退 Approve 状态 |
| `server/routers/approvals.py` L95, L174 | Batch 2 | 修复 agent_name |
| `web/src/stores/chatStore.ts` (sendChat) | Batch 3 | 发送 agent_name |
| `agent/session/runtime.py` L1006-1354 | Batch 3 | 删除死代码 |
