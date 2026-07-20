# Plan 显式架构方案

> 基于 Claude Code plan mode 设计，将隐式 intent=analysis 转换升级为显式 plan session。

---

## 一、Claude Code 的 Plan Mode 设计 (参照)

来源: [how-claude-code-works/10-plan-mode.md](https://github.com/Windy3f3f3f3f/how-claude-code-works/blob/main/en/docs/10-plan-mode.md)

**核心原则：**

1. **Plan 是显式状态** — `mode: 'plan'`，和 `default`/`auto`/`bypassPermissions` 并列
2. **对称性** — 进入时保存 `prePlanMode`，退出时恢复。Plan 是"可嵌套插入层"
3. **主动降权** — 模型自愿放弃写入权限以换取用户信任
4. **两个入口** — 用户发起（`/plan`）和模型发起（`EnterPlanMode`），收敛到同一个状态转换函数
5. **Plan 文件** — 写入 `~/.claude/plans/{slug}.md`，人类可读 slug
6. **渐进提示** — Turn 1 全量 → Turn 5/10 稀疏 → Turn 25 全量，省 token
7. **子 agent 不可进入 plan mode** — 子 agent 无用户交互能力
8. **ExitPlanMode 需用户审批** — `behavior: 'ask'`，支持 Approve/Edit/Reject

---

## 二、当前状态（缺陷）

```
用户意图                  当前实现                        问题
─────────                ────────                        ────
创建 plan session        POST /sessions {agent_name="build"}  必须用 build 创建
                         → 再发 intent="analysis" 转换     两步操作，隐式转换

ChatView mode=plan       intent="analysis" → _is_plan=True   intent 不是 agent_name
                         → agent_name 强制改成 "plan"       mapping 藏在 if 里

PlanView "Start Plan"    api.chat(..., "analysis", "plan")   两个参数冗余
                         → _is_plan = True + agent="plan"   但 session.agent_name 可能还是 build

session agent_name       run_chat_async 纠正后 DB 更新       DB 和运行时短暂不一致
                         但 sessions.py 的更新可能延迟       (我们的 Fix 2.1 缓解了,没根治)
```

**根因：** `intent="analysis"` 和 `agent_name="plan"` 是两个独立的概念，被代码里的 if 语句临时绑在一起。没有显式的 plan session 类型，也没有对称的 enter/exit 状态管理。

---

## 三、目标状态

### 3.1 显式 Plan Session

```
创建:
  POST /api/sessions {agent_name: "plan"}  → agent_name="plan" in DB
  PlanView "+ Plan" 按钮                            → 同上
  ChatView mode=plan 发送消息                       → 同上

执行:
  run_chat_async(agent_name="plan")
    → _is_plan = (agent_name == "plan")  ← 不再依赖 intent!
    → AgentFactory.create("plan") → plan spec → permission_mode="plan"
    → 只读 tools，write/edit 不可用

审批:
  ExitPlanMode → contract → plan_ready → PlanView
  用户 Approve → 启动 build agent (同一 session 或新 session)
```

### 3.2 去掉隐式转换

```
删除:
  if _is_plan and agent_name != "plan": agent_name = "plan"     ← agent_service.py:558-559
  _resolved_intent = TaskIntent(body.intent) if body.intent else None
  if _resolved_intent is TaskIntent.ANALYSIS: effective_agent="plan"  ← sessions.py:389-394

改为:
  effective_agent = body.agent_name or rec.agent_name  # 信任调用方传入的值
  # 如果调用方传 intent="analysis" 但 agent_name="build", 那就是 build + analysis intent
  # 不再自动转换
```

### 3.3 Plan 文件（对标 CC）

```
写入:
  .grace/plans/{session_id}.md  ← 简单方案：用 session_id 而非随机 slug
  内容: YAML frontmatter + Markdown body
  ExitPlanMode 时写入

读取:
  GET /api/sessions/{id}/plan → 返回 plan 文件内容
  前端 PlanView 可展示 plan 文件

修订:
  reject → 写入新版本 (.grace/plans/{session_id}_v2.md)
  diff 端点已有 plan revision diff
```

---

## 四、实施计划

### Phase 1: 去掉隐式转换 (P0, 低风险)

**文件:** `server/services/agent_service.py:558-559`, `server/routers/sessions.py:389-394`

删除 intent=analysis → force plan 的逻辑。调用方必须显式传 `agent_name="plan"`。

**前置条件：** 所有调用方已经显式传 agent_name:
- ✅ PlanView "Start Plan Analysis" 按钮 → 传 `agent_name="plan"` (我们的 Fix 2.4)
- ✅ SessionSidebar "+ Plan" 按钮 → `createSession("plan")` (我们的 #3 fix)
- ✅ ChatView mode=plan → sendChat 传 `currentMode` 作为 agentName (已有)
- ✅ approvals.py reject → 使用 `agent_name="plan"` (我们的 Fix 2.3b)
- ✅ approvals.py approve → 使用 `agent_name="build"` (已有)

**风险:** 如果有外部调用方（CLI、脚本）依赖 intent=analysis → plan 的隐式转换，会 break。但 CLI 用 ChatSession，不走 sessions.py。

### Phase 2: _is_plan 简化 (P0)

**文件:** `server/services/agent_service.py:552-554`

```python
# 之前:
_is_plan = agent_name == "plan" or (resolved_intent is not None and resolved_intent == TaskIntent.ANALYSIS)

# 之后:
_is_plan = agent_name == "plan"
```

现在 `agent_name` 已经是调用方显式传入的，不需要 intent 作为 fallback。

### Phase 3: Plan 文件写入 (P1)

**文件:** `tools/plan_mode_tool.py` + `server/routers/approvals.py`

ExitPlanMode 时写入 `.grace/plans/{session_id}.md`:
```python
plan_dir = Path(repo_path) / ".grace" / "plans"
plan_dir.mkdir(parents=True, exist_ok=True)
plan_file = plan_dir / f"{session_id}.md"
plan_file.write_text(f"---\ncontract: {json.dumps(contract)}\n---\n\n{summary}")
```

### Phase 4: PlanView 展示 plan 文件 (P1)

**新增 API:** `GET /api/sessions/{id}/plan` → 返回 plan 文件内容

**前端:** PlanView 加载 plan 文件内容替代当前 pure summary 展示

---

## 五、可行性分析 (批判性)

### 5.1 去隐式转换是否安全？

**检查所有调用方:**

| 调用方 | 传 agent_name | 传 intent | 受影响？ |
|--------|:---:|:---:|:---:|
| PlanView 按钮 | "plan" | "analysis" | ❌ 不受影响 |
| SessionSidebar +Plan | "plan" | — | ❌ 不受影响 |
| ChatView mode=plan | "plan" (via currentMode) | "analysis" | ❌ 不受影响 |
| ChatView mode=build | "build" | — | ❌ 不受影响 |
| approvals.py approve | "build" | "edit" | ❌ 不受影响 |
| approvals.py reject | "plan" | "analysis" | ❌ 不受影响 |
| CLI ChatSession | "build" (default) | — | ❌ 不受影响 |
| 外部 API 调用方 | ??? | ??? | ⚠️ 未知 |

**结论:** 所有已知调用方都已显式传 agent_name。如果存在未知的外部调用方（直接调 REST API 传 intent="analysis" 但不传 agent_name），它们会 break——agent 会以 build+analysis 模式运行而非 plan 模式。但 build agent 有 `EnterPlanMode` 工具，LLM 可以主动切换。所以实际影响是 LLM 需要多一步操作（先 EnterPlanMode），而非功能完全不可用。

### 5.2 _is_plan 简化是否引入回归？

`_is_plan` 现在只看 `agent_name == "plan"`。如果某处代码错误地传了 `agent_name="build"` + `intent="analysis"`，之前会被兜底纠正，现在不会。

但这是**正确的行为**——如果调用方要 plan，就应该显式传 "plan"。隐式纠正掩盖了调用方的 bug。

### 5.3 Plan 文件方案的问题

- **并发**：同一 session 多次 plan → 文件被覆盖。需要版本号后缀。
- **清理**：session 删除时是否删除 plan 文件？是。加到 cleanup 逻辑。
- **跨平台**：`.grace/plans/` 目录权限，Windows 路径问题。
- **Git 污染**：`.grace/` 已经在 `.gitignore` 中，但需要确认。

### 5.4 预知风险

| 风险 | 概率 | 影响 | 缓解 |
|------|:---:|:---:|------|
| 外部调用方依赖隐式转换 | 低 | 中 | 文档说明 + 过渡期保留 intent 但 log warning |
| CLI 路径受影响 | 极低 | 低 | CLI ChatSession 不走 sessions.py，用 chat.py |
| Plan 文件与 plan revision DB 不一致 | 中 | 低 | Plan 文件作为展示用，PlanRevisionService 作为审批用，各司其职 |
| `_is_plan` 简化后 plan_ready 漏发 | 极低 | 高 | 所有入口已显式传 agent_name；即使漏发，`result.contract` 仍可触发 |
| 隐式转换删除后 LLM 在 build 模式不会主动 EnterPlanMode | 低 | 中 | EnterPlanMode 工具在所有 agent 上都可用；LLM 被 prompt 引导使用 |

---

## 六、推荐实施顺序

```
Batch 1 (P0, 低风险):
  ├─ agent_service.py: 删除 intent→plan 隐式转换
  ├─ agent_service.py: 简化 _is_plan = (agent_name == "plan")
  └─ sessions.py: 删除 intent→plan 隐式转换

Batch 2 (P1):
  ├─ plan_mode_tool.py: ExitPlanMode 写入 plan 文件
  ├─ sessions.py: GET /{id}/plan 端点
  └─ PlanView: 加载 plan 文件展示

Batch 3 (P2, cleanup):
  └─ approvals.py: approve 后清理 plan 文件
```
