# Plan + Subagent 完整流程演算与缺口分析

> 逐段追踪代码执行路径，识别每个缺口

---

## 一、Plan Mode 完整流程演算

### 1.1 用户发起 Plan

```
ChatView: mode=plan → intent="analysis"
  → POST /api/sessions/{id}/messages {prompt, intent:"analysis"}
  → agent_service.run_chat_async(session_id, prompt, agent_name="build", intent="analysis")
  → _is_plan = (agent_name=="plan" or intent=="analysis") → True
```

**缺口 1:** `agent_name` 从 session record 读取 (`rec.agent_name`)，而不是从 `run_chat_async` 参数。如果 session 创建时 `agent_name="build"`，即使 intent=analysis，agent_name 仍是 "build"。`_is_plan` 通过 `intent == ANALYSIS` 检测是兜底方案，但 session record 的 agent_name 不会更新为 "plan"。

**文件:** `sessions.py:332` — `effective_agent = body.agent_name or rec.agent_name`

**修复:** 当 intent=analysis 时，应更新 session 的 agent_name 为 "plan"。

---

### 1.2 Plan Agent 运行

```
run_session(agent_name="plan" or "build", intent=ANALYSIS)
  → spec = agent_registry.get("plan" or "build")
  → spec.permission_mode = "plan" (for plan agent definition)
  → prompt injection: get_plan_mode_injection()
  → agent runs in read-only mode
```

**缺口 2:** 如果用户创建的是 build session (`agent_name="build"`)，然后选择 plan mode（intent=analysis），agent definition 仍然是 build 的。build agent 的 `permission_mode` 不是 "plan"。这意味着 plan 模式的只读限制不生效！

**文件:** `runtime.py:597-605` — spec 来自 agent_name，不是 intent

**修复:** 当 intent=ANALYSIS 时，强制使用 plan agent definition。

---

### 1.3 Plan 完成 → plan_ready 事件

```
agent finishes → run_session returns RunResult
  → _run_and_notify checks _is_plan → True
  → emits plan_ready WS event with result.summary
  → frontend: chatStore.handleWsEvent → planApproval = {planText, isWaiting:true}
```

**缺口 3:** `plan_ready` 事件仅包含 `plan_text`（result.summary），不包含结构化的 plan contract（JSON）。前端 PlanView 只能展示纯文本，无法渲染结构化卡片（Goal/Steps/Verification）。

**文件:** `agent_service.py:596-606` — plan_ready payload

**修复:** 如果 result 中有 contract 字段，一并发送。

---

### 1.4 用户 Approve → Build

```
user clicks "Approve & Build"
  → chatStore.approvePlan() → POST /api/sessions/{id}/approve
  → approvals.py: append [PLAN CONTEXT] message
  → run_chat_async(session_id=session_id, agent_name="build", intent="edit")
  → 同一个 session_id!
```

**缺口 4:** Plan 和 Build 共用一个 session_id。Session 的状态在 `run_session()` 中从 completed 更新为 running。但 plan 阶段的 timeline 和 build 阶段的 timeline 混在同一 session 的消息列表中。前端无法区分 "这是 plan 阶段的探索" 和 "这是 build 阶段的执行"。

**缺口 5:** 前端 `planApproval` 在 `sendChat()` 时被清除（chatStore.ts:204）。但 approve 调用的是 `approvePlan()` 而不是 `sendChat()`。approvePlan 设置 `isWaiting: false` 但不清除 planApproval 对象。build 完成后，如果用户再发消息，planApproval 仍然存在。

**文件:** `chatStore.ts:approvePlan()` — 设置 `planApproval: {...planApproval, isWaiting: false}`

**修复:** build 完成后应清除 planApproval。

---

### 1.5 用户 Reject → Re-plan

```
user clicks "Reject" with reason
  → chatStore.rejectPlan() → POST /api/sessions/{id}/reject
  → approvals.py: append [PLAN REVISION REQUEST] message
  → run_chat_async(session_id, agent_name=rec.agent_name, intent="analysis")
  → plan_revision counter: rec.metadata["plan_revision"]
  → max 5 revisions
```

**缺口 6:** `rec.agent_name` 在 reject 时使用。如果原始 session 是 build agent + intent=analysis 创建的，`rec.agent_name` 是 "build"，不是 "plan"。re-plan 会用 build agent 重新运行，build agent 没有 plan mode 限制。

**缺口 7:** 前端不显示当前修订次数 (revision N/5)。用户不知道还剩多少次修订机会。

**缺口 8:** 没有 "plan revision diff" — 用户看不到新的 plan 和旧的 plan 之间的差异。

---

### 1.6 Plan → Build 权限模式切换

```
Plan session: permission_mode = "plan" (read-only)
  → user approves
  → build starts on same session
  → _run_and_notify: inject_permission_mode = "acceptEdits"
```

**验证:** `_run_and_notify` 总是传 `inject_permission_mode="acceptEdits"`。所以 build agent 在同一个 session 上运行时，pipeline 的 mode 被正确设置为 acceptEdits。✅

---

## 二、Subagent 完整流程演算

### 2.1 Agent 工具调用 → spawn_agent

```
LLM calls Agent tool with {subagent_type:"explore", description:"...", prompt:"..."}
  → ToolRegistry.execute_tool("Agent", params)
  → AgentTool.execute()
  → runtime.spawn_agent(parent_session_id=..., request=AgentSpawnRequest(...))
```

**缺口 9:** Agent 工具在前端是否可见？`agent/core.py` 的 tool schema 构建从 registry 获取所有工具的 schema。如果 Agent 工具在 registry 中，LLM 能看到并调用它。需要验证 AgentTool 是否已注册。

---

### 2.2 子 Session 创建 + 权限继承

```
spawn_agent:
  → store.create_session(parent_id=parent.id, root_id=parent.root_id, ...)
  → definition = agent_registry.get(request.agent_name)
  → _resolve_child_permission_mode(parent_mode, child_definition)
  → subagent.run_child_agent(request, session_id=child.id, ...)
```

**缺口 10:** 子 session 的 `web_confirm_callback` 注入在 `subagent.py:183`:
```python
_web_cb = session_runtime._web_confirm_callbacks.pop(agent_id, None)
```
但 `agent_id` 是子 session 的 ID。谁会为子 session 设置 `_web_confirm_callbacks[child_id]`？
父 session 的 `_build_web_confirm_callback(parent_id)` 只为父 session 创建回调。

**结果:** 子 agent 的 `_web_confirm_callback` 永远是 None → Layer 6 走 Path C (TTY) 或 Path D (DENY) → 子 agent 的工具调用在 Web 模式下会被拒绝！

**修复:** 在 `subagent.py` 中为子 session 创建独立的 `ApprovalBroker` 和 `web_confirm_callback`。

---

### 2.3 子 Agent 执行

```
run_child_agent:
  → cfg.stream = False  (line 199)
  → agent.run(task, log)
```

**缺口 11:** `stream = False`。子 agent 的 LLM 调用不使用流式。这意味着子 agent 的 thought 事件不会实时推送到前端。前端只能看到 `subagent_start` 和 `subagent_stop`，中间没有任何进度。

**缺口 12:** 子 agent 的 events 写入 `EventLog`，但 event_callback 推送到的是**子 session 的 WebSocket**。如果前端订阅了父 session 的 WS，它收不到子 session 的事件。

**当前行为:** 子 agent 的事件通过 `event.session_id = child_id` 路由到子 session 的 EventBus 订阅者。但前端只订阅了父 session 的 WS。所以前端的 `backgroundAgents` 追踪（基于 subagent_start/stop 事件）能看到子 agent 的启动和停止，但看不到中间的工具调用。

**修复:** 在子 agent 的 event_callback 中，将 `session_id` 设置为父 session ID，使子 agent 的进度事件路由到父 session 的 WebSocket。

---

### 2.4 子 Agent 完成 → Worktree

```
run_child_agent finally:
  → finalize_worktree()
  → if has_changes: worktree_disposition = PRESERVED
  → child session record: agent_result.worktree_disposition
```

**缺口 13:** Worktree disposition 存储在 `agent_result` 中，但前端没有 API 来查询这个状态。

**缺口 14:** `_check_session_completion` (runtime.py:405) 会 block 父 agent 的 finish，如果存在 PRESERVED worktree。但父 agent 只是收到一个 `[RUNTIME BLOCK]` 消息，没有结构化的 "这里有一个 worktree，请处理" 的提示。

**缺口 15:** 没有 API 来 apply/discard/retain worktree。这些操作只能通过 CLI 进行。

---

### 2.5 后台 vs 前台子 Agent

```
ExecutionPlacement.FOREGROUND:
  → spawn_agent in current thread → parent blocks
  → events stream in real-time

ExecutionPlacement.BACKGROUND:
  → threading.Thread → parent continues
  → completion notification via agent_notifications table
  → parent picks up on next turn via claim_agent_completions()
```

**缺口 16:** 后台子 agent 的 `subagent_start`/`subagent_stop` 事件何时 emit？查看 `runtime.py:980-993`，它们在 `spawn_agent()` 中 emit，而不是在子 agent 线程中。所以后台子 agent 的 start/stop 事件在父 agent 的下一个 action 步骤中 emit。如果父 agent 在子 agent 运行期间没有做任何 tool call，这些事件可能延迟。

---

### 2.6 子 Agent 取消传播

```
cancellation_token.cancel()  →  child thread checks token →  raises CancelledError
```

**缺口 17:** 取消令牌是从父 agent 传播到子 agent 的。但如果子 agent 已经 spawn 了自己的子 agent（孙子），取消令牌是否传播到孙子？查看 `runtime.py` 的 `_execute_child_session`，子 agent 的 `cancellation_token` 是从父 agent 传入的同一个 token。孙子 agent 也应该收到同一个 token。

---

## 三、交叉场景：Plan + Subagent

### 3.1 Plan Agent spawns Subagent

```
Plan agent (read-only) → calls Agent tool → explore subagent
  → subagent inherits "plan" permission mode → read-only
```

**验证:** `_resolve_child_permission_mode` 中，plan mode 强制传给子代理。✅

### 3.2 Build Agent (post-approval) spawns Subagent

```
Build agent (acceptEdits) → calls Agent tool → general subagent
  → subagent inherits "acceptEdits" → can write files
```

**验证:** acceptEdits 允许子代理使用自己的 mode 或继承。✅

---

## 四、缺口汇总

### 🔴 严重 (影响核心功能)

| # | 缺口 | 文件 | 影响 |
|---|------|------|------|
| 2 | Plan mode 用 build agent 运行 | `runtime.py:597` | plan 只读限制不生效 |
| 10 | 子 agent 没有 web_confirm_callback | `subagent.py:183` | 子 agent 工具调用全部被拒 |
| 12 | 子 agent 事件不路由到父 WS | `runtime.py`, `subagent.py` | 前端看不到子 agent 进度 |

### 🟡 中等 (影响体验)

| # | 缺口 | 文件 | 影响 |
|---|------|------|------|
| 1 | session agent_name 不更新 | `sessions.py:332` | 显示不一致 |
| 3 | plan_ready 缺结构化 contract | `agent_service.py:596` | PlanView 只能显示纯文本 |
| 4 | Plan/Build 共用 session_id | `approvals.py:84` | 无法区分 plan 和 build 阶段 |
| 6 | reject 用 rec.agent_name | `approvals.py:148` | re-plan 可能用错 agent |
| 11 | 子 agent stream=False | `subagent.py:199` | 无实时 thought 流 |
| 16 | 后台子 agent 事件延迟 | `runtime.py:980` | 进度卡片更新不及时 |

### 🟢 轻微 (功能增强)

| # | 缺口 | 文件 | 影响 |
|---|------|------|------|
| 5 | planApproval 清除时机 | `chatStore.ts` | build 后残留状态 |
| 7 | 前端不显示修订次数 | `ChatView.tsx` | 用户不知剩余修订次数 |
| 8 | 无 plan revision diff | — | 无法对比新旧 plan |
| 13 | Worktree 状态无 API | — | 前端不可见 |
| 14 | Worktree block 消息不结构化 | `runtime.py:405` | agent 不理解 |
| 15 | Worktree apply/discard 无 API | — | 只能 CLI 操作 |
| 17 | 取消令牌孙子传播 | `runtime.py` | 深层嵌套可能不取消 |

---

## 五、修复计划

```
Batch P1: 修缺口 2 (plan agent 选择)        — runtime.py
Batch P2: 修缺口 10 (子 agent web callback)  — subagent.py + agent_service.py  
Batch P3: 修缺口 12 (子 agent WS 路由)       — runtime.py + subagent.py
Batch P4: 修缺口 1+6 (agent_name 一致性)     — sessions.py + approvals.py
Batch P5: 修缺口 3 (plan contract)           — agent_service.py + PlanView.tsx
Batch P6: 修缺口 7+5 (修订次数 + 状态清除)    — ChatView.tsx + chatStore.ts
```
