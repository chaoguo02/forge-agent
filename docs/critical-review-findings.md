# 批判性代码审查报告

> 对 plan + subagent + approval 全链路进行系统性审查。
> 审查范围：agent/session/、server/services/、server/routers/、tools/、hitl/、web/src/

---

## 🔴 CRITICAL (运行时 NameError / 崩溃)

### C1. event_bus.py:311 — `_DIFF_TOOLS` 未定义

**文件:** [server/services/event_bus.py:311](server/services/event_bus.py#L311)

```python
if _tool in _DIFF_TOOLS:  # ← NameError! _DIFF_TOOLS 从未定义
```

`EventBus.publish()` 在处理 Edit/Write 工具的 observation 事件时会崩溃。
所有后续事件路由中断。

**修复:** 添加模块级常量：
```python
_DIFF_TOOLS: frozenset[str] = frozenset({"Edit", "Write", "file_edit", "file_write"})
```

### C2. event_bus.py:313 — `payload` 未定义

**文件:** [server/services/event_bus.py:313](server/services/event_bus.py#L313)

```python
_modified = payload.get("observation", {}).get("modified_files", [])  # ← NameError!
```

`payload` 是 `_translate_event()` 内部局部变量，在 `publish()` 中不可见。

**修复:** 从 event 对象获取：
```python
_modified = (getattr(event, "payload", {}) or {}).get("observation", {}).get("modified_files", [])
```

---

## 🔴 HIGH (功能缺陷 / 数据损坏)

### H1. agent_service.py — `_pending_plan_contract` 跨 session 污染

**文件:** [agent_service.py:663-667](server/services/agent_service.py#L663) + [plan_mode_tool.py:189](tools/plan_mode_tool.py#L189)

ExitPlanMode 将 contract 写入**共享单例** `registry._pending_plan_contract`，而非 session-scoped 存储。

**风险场景:**
1. Session A 的 plan agent 调用 ExitPlanMode → `_pending_plan_contract = contract_A`
2. Session B 的 plan agent 调用 ExitPlanMode → `_pending_plan_contract = contract_B` (覆盖!)
3. Session A 的 `_run_and_notify` fallback 读到 contract_B ← 错误!

此外，当 `result.contract` 为真时（主路径），`_pending_plan_contract` 不会被清除。

**修复:** 完全移除 `registry._pending_plan_contract` 回退路径。`agent._accumulated_plan_contract → RunResult.contract` 主路径已经正确且 session-scoped。

### H2. sessions.py — 无 session 运行锁，重复点击导致并发线程

**文件:** [sessions.py:412](server/routers/sessions.py#L412) + [PlanView.tsx:78](web/src/components/PlanView.tsx#L78)

`create_message` 端点不检查 session 是否已在运行。前端 "Start Plan Analysis" 按钮也缺少 `isRunning` 防护。

**后果:**
- 两个 agent 并发执行在同一 session 上 → 对话历史混乱
- 两个 `plan_ready` 事件 → 前端状态覆盖
- `_build_web_confirm_callback` 被覆盖
- 数据库写入竞争

**修复:**
1. 服务端：`run_chat_async` 前检查 session 状态，若 running 则返回 409
2. 前端：PlanView 按钮添加 `disabled={isRunning}` 防护

### H3. sessions.py — 删除 session 不取消正在运行的线程

**文件:** [sessions.py:589-610](server/routers/sessions.py#L589)

`delete_session` 直接删除 DB 记录，不取消后台线程。线程继续运行，尝试读写已删除的数据。

**修复:** 删除前先调用 `cancel_session()` 和 `event_bus.destroy_session()`。

### H4. PlanView.tsx — "Start Plan Analysis" 按钮绕过 sendChat 状态管理

**文件:** [PlanView.tsx:81](web/src/components/PlanView.tsx#L81)

PlanView 直接调用 `api.chat()` 而非 `chatStore.sendChat()`，绕过了：
- `isRunning` 状态设置
- `planApproval` 清除
- `currentMode` 追踪
- 超时看门狗

**修复:** 改为调用 `chatStore.sendChat()` 或至少设置 `isRunning` + 按钮禁用。

### H5. subagent.py — `_resolve_child_permission_mode` 对命名子 agent 传入错误的父定义

**文件:** [subagent.py:171-174](agent/session/subagent.py#L171)

```python
_child_mode = session_runtime._resolve_child_permission_mode(
    source_definition,  # 对命名 agent，这是子 agent 自己的定义，不是父的！
    definition if request.agent_kind is AgentKind.NAMED_SUBAGENT else None
)
```

`source_definition` 在 fork 时是父定义(正确)，在命名子 agent 时是子定义(错误)。
`_resolve_child_permission_mode(parent, child)` 的第一个参数应该是父定义。

**影响:** 命名子 agent 的权限模式基于子定义自身计算，而非从父继承。
例如：父是 "plan" 模式(只读)，但子定义是 "acceptEdits" → 子获得写入权限。

**修复:** 将 `parent_definition` 传入 `run_child_agent`，或从 `session_record.parent_id` 查找父定义。

---

## 🟡 MEDIUM (体验/一致性)

### M1. agent_service.py — plan 异常时前端无感知

**文件:** [agent_service.py:691-698](server/services/agent_service.py#L691)

Plan session 异常时只发 `status: failed`，不发 `plan_ready`。前端 PlanView 无法区分
"plan 执行失败" 和 "从未启动 plan"。用户看到 "No plan has been generated yet"。

**修复:** Plan 异常时也发 `plan_ready`（含错误信息），或发专门的 `plan_failed` 事件。

### M2. event_bus.py — plan_ready 无订阅者时静默丢弃

**文件:** [event_bus.py:364-366](server/services/event_bus.py#L364)

无持久化/重放机制。WS 重连期间完成的 plan → 事件永远丢失。

**修复:** 将 plan 状态持久化到 session metadata，前端增加 REST API 回退加载。

### M3. approvals.py — approve endpoint 不确保 EventBus 订阅者

**文件:** [approvals.py:95-100](server/routers/approvals.py#L95)

`approve` 和 `reject` 端点直接调用 `run_chat_async`，不先创建 EventBus 订阅者。
如果无 WS 连接，所有 build/re-plan 事件静默丢弃。

**修复:** 在 `run_chat_async` 前调用 `event_bus.create_session(session_id)`。

### M4. chatStore.ts — approvePlan 不检查 isWaiting

**文件:** [chatStore.ts:666-667](web/src/stores/chatStore.ts#L666)

```typescript
const { planApproval } = selectCurrentSessionUi(get());
if (!sid || !planApproval) return;  // 应该加上 || !planApproval.isWaiting
```

若用户快速点击两次 Approve，第二次点击 `isWaiting` 已是 false 但 `planApproval` 对象仍存在。

### M5. subagent.py — parent_pipeline_state 为空时跳过权限继承

**文件:** [subagent.py:168](agent/session/subagent.py#L168)

```python
if parent_pipeline_state:  # ← 为 None/falsy 时整个继承块跳过
```

我们修复了 runtime_spawn.py 传入 `parent_pipeline_state`，但若 `_base_registry._permission_pipeline`
为 None 或 `get_inheritable_state()` 返回空，继承仍然跳过。应增加 fallback。

### M6. PlanView.tsx — 无 isRunning 检查导致 plan 执行中可以再次点击

**文件:** [PlanView.tsx:78](web/src/components/PlanView.tsx#L78)

"Start Plan Analysis" 按钮缺少 `disabled={isRunning}`。用户可在 plan 执行期间重复点击。

---

## 🟢 LOW (清理/风格)

### L1. tools/mcp_tool.py:146 — 重复 `import json`

模块级(第16行)已导入，第146行又重复导入。

### L2. subagent.py:53 — `PermissionPipeline` 类型注解未 import

`-> "PermissionPipeline | None"` 用字符串形式安全，但 TYPE_CHECKING 块中缺少实际导入。

### L3. events.ts:15 — `"plan_ready"` 错误地在 `WsStatusEvent.status` 联合类型中

`plan_ready` 是独立的 `WsPlanReadyEvent`，不是 `WsStatusEvent` 的 status 值。

### L4. chatStore.ts — sendChat 无条件清除 planApproval

**文件:** [chatStore.ts:445](web/src/stores/chatStore.ts#L445)

发送任何新消息都会清除 `planApproval`。若用户在 approve/reject 界面发送反馈消息，
plan 状态丢失。

---

## 📊 总计

| 严重度 | 数量 | 需立即修复 |
|--------|------|-----------|
| 🔴 CRITICAL | 2 | ✅ C1, C2 |
| 🔴 HIGH | 5 | ✅ H1-H5 |
| 🟡 MEDIUM | 6 | M1-M6 |
| 🟢 LOW | 4 | L1-L4 |
| **总计** | **17** | |

---

## 修复优先级

```
立即修复 (阻断性):
  C1 + C2: event_bus.py NameError → WebSocket diff 功能崩溃

P0 (功能正确性):
  H1: _pending_plan_contract 跨 session 污染
  H2: session 并发防护
  H5: 命名子 agent 权限继承错误

P1 (体验修复):
  H4: PlanView 按钮改用 sendChat
  H3: 删除 session 时取消线程
  M1-M4: plan_ready 可靠性改进
  M6: PlanView isRunning 防护

P2 (清理):
  M5, L1-L4
```
