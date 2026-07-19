# Subagent + Plan Mode — Web 交互设计与实施计划

> 基于 Claude Code 2025-2026 UX 模式 + 项目现有代码审计
> 后端已完整，前端需补全

---

## 一、现状审计

### 后端：✅ 完整

| 模块 | 状态 | 关键文件 |
|------|------|----------|
| 子代理生成 (foreground/background) | ✅ | `runtime.py:840-1039` |
| 权限继承 (5 条 CC 规则) | ✅ | `runtime.py:1703-1739` |
| Worktree 隔离 | ✅ | `subagent.py:117-131` |
| 子代理事件 (subagent_start/stop) | ✅ | `event_bus.py:187-201` |
| 父子 session DB 关系 | ✅ | `session_store.py` |
| 后台异步完成通知 | ✅ | `runtime.py:1516-1542` |
| Plan 审批端点 (approve/reject) | ✅ | `approvals.py:37-152` |
| plan_ready WS 事件 | ✅ | `agent_service.py:596-606` |
| Plan 修订追踪 (cap 5) | ✅ | `approvals.py:120-127` |
| Plan prompt 注入 + 节流 | ✅ | `runtime.py:679-698` |

### 前端：⚠️ 部分完成

| 模块 | 状态 | 缺失 |
|------|------|------|
| PlanView 组件 | ✅ | — |
| ChatView plan 审批栏 | ✅ | — |
| chatStore planApproval 状态 | ✅ | — |
| **子代理 session 树** | ❌ | 无层级视图 |
| **子代理详情面板** | ❌ | 无 click-to-inspect |
| **后台子代理进度** | ❌ | 无实时 WS 进度 |
| **Worktree 状态 UI** | ❌ | 无 apply/discard/retain |
| **Plan 生成进度流** | ❌ | 仅 plan_ready 最终事件 |
| **Plan 修订 diff** | ❌ | 无视觉对比 |

---

## 二、总体架构设计

```
┌─────────────────────────────────────────────────────┐
│                   ChatView                          │
│  ┌───────────────┐  ┌────────────────────────────┐ │
│  │ SessionTree   │  │ Timeline                   │ │
│  │ (左侧面板)     │  │ ┌────────────────────────┐ │ │
│  │               │  │ │ SubagentCard (可折叠)    │ │ │
│  │ root session  │  │ │  ├─ subagent_start      │ │ │
│  │  ├─ child 1   │  │ │  ├─ thought (children)  │ │ │
│  │  │  ├─ grand1 │  │ │  ├─ tool_call (children)│ │ │
│  │  │  └─ grand2 │  │ │  ├─ observation         │ │ │
│  │  └─ child 2   │  │ │  └─ subagent_stop       │ │ │
│  │               │  │ └────────────────────────┘ │ │
│  │               │  │ ┌────────────────────────┐ │ │
│  │               │  │ │ PlanCard (可审批)       │ │ │
│  │               │  │ │  ├─ plan_ready 事件     │ │ │
│  │               │  │ │  ├─ 计划文本            │ │ │
│  │               │  │ │  ├─ [Approve] [Reject] │ │ │
│  │               │  │ │  └─ 修订 diff           │ │ │
│  └───────────────┘  │ └────────────────────────┘ │ │
│                     └────────────────────────────┘ │
│  ┌────────────────────────────────────────────────┐ │
│  │ Composer                                       │ │
│  │ [mode: build|plan|explore] [model] [settings]   │ │
│  └────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 三、模块设计

### 模块 1: 子代理 Session 树 (SessionTree)

**目标:** 在左侧面板显示父子 session 的层级关系，类似 CC 的 `/agents` 命令。

**CC 模式:**
- 以 `main` 为根，显示完整嵌套树
- 每行显示: 后代数量、深度、到 main 的路径
- 最多 5 层深度

> 来源: [Claude Code v2.1.172 nested subagents](https://code.claude.com/docs/en/whats-new/2026-w24), [Issue #6007 navigable transcripts](https://github.com/anthropics/claude-code/issues/6007)

**我们的实现:**

#### 后端 API (缺失)

```
GET /api/sessions/{session_id}/tree
→ {
    "session": { id, agent_name, status, depth, ... },
    "children": [ { id, agent_name, status, depth, children: [...] }, ... ]
  }
```

#### 实现文件

| 文件 | 改动 |
|------|------|
| `server/routers/sessions.py` | 新增 `GET /{id}/tree` 端点 |
| `server/services/session_service.py` | 新增 `get_session_tree()` 递归查询 |
| `web/src/components/SessionTree.tsx` | **NEW** — 树形面板组件 |
| `web/src/stores/sessionStore.ts` | 新增 `sessionTree` 状态 |

#### 树节点状态展示

| 状态 | 图标 | 颜色 |
|------|------|------|
| running | ⠹ 旋转动画 | accent |
| completed | ✓ | green |
| failed | ✗ | red |
| queued | ○ | muted |
| cancelled | ■ | yellow |

每个节点显示:
- Agent 名称 (build/plan/explore/general)
- 工具调用次数 + token 消耗
- 运行时长
- 子代理数量 badge
- 点击 → 切换到该 session 的详情视图

---

### 模块 2: 子代理详情面板

**目标:** 点击 SessionTree 中的子代理节点，在主区域展示该子代理的完整执行日志。

**CC 模式:**
- Clickable links to view full subagent transcripts
- 头部显示: `--- Viewing Sub-agent Log: <name> (task-123) ---`
- 返回父 session 的导航 (Esc / `/back`)

> 来源: [Issue #6007](https://github.com/anthropics/claude-code/issues/6007), [pi-subagents extension](https://www.npmjs.com/package/@yzlin/pi-subagents)

**我们的实现:**

#### 后端 API (已存在)

```
GET /api/sessions/{session_id}/events  → 已有
GET /api/sessions/{session_id}/messages → 已有
```

#### 前端组件

| 文件 | 改动 |
|------|------|
| `web/src/components/SubagentDetail.tsx` | **NEW** — 子代理执行详情面板 |
| `web/src/stores/chatStore.ts` | 新增 `viewingChildSessionId` 状态 |

#### 面板布局

```
┌─────────────────────────────────────────┐
│ ← Back to parent    agent: explore #2   │
│ status: completed    steps: 12  42s     │
├─────────────────────────────────────────┤
│ [timeline of the child session]          │
│  ◎ Thought: ...                         │
│  ⚙ Read: file.py                        │
│  ✓ Observation: ...                     │
│  ↺ Reflection: ...                      │
│  ● finish: Done                         │
├─────────────────────────────────────────┤
│ Worktree: preserved                     │
│ [Apply Changes] [Discard] [Retain]      │
└─────────────────────────────────────────┘
```

---

### 模块 3: 后台子代理进度指示器

**目标:** 当主 agent 派发后台子代理时，在界面显示实时进度。

**CC 模式:**
- `⟳3≤30 · 3 tool uses · 12.4k token / ⎿ searching…` (running)
- `✓ ⟳8 · 5 tool uses · 33.8k token · 12.3s / ⎿ Done` (completed)

> 来源: [pi-subagents widget](https://www.npmjs.com/package/@yzlin/pi-subagents), [Issue #19 UX improvements](https://github.com/srothgan/claude-code-rust/issues/19)

**我们的实现:**

#### 后端 (已存在)

`subagent_start` 和 `subagent_stop` WS 事件已在 `event_bus.py:187-201` 中 emit。
但后台子代理的逐步事件（thought, tool_call）需要路由到**父 session 的 WS** 或单独的前端 polling。

**方案:** 在 `runtime.py` 的子代理 event_callback 中，将子代理事件的 `session_id` 设置为父 session 的 ID，使得父 session 的 WebSocket 能收到子代理的进度事件。

#### 前端组件

| 文件 | 改动 |
|------|------|
| `web/src/components/SubagentProgress.tsx` | **NEW** — 浮动进度卡片 |
| `web/src/stores/chatStore.ts` | 新增 `backgroundAgents: Record<string, AgentProgress>` |

#### 进度卡片

```
┌────────────────────────────┐
│ ⠹ explore · 3 tools · 12.4k│
│ ⎿ searching for patterns…  │
└────────────────────────────┘
```

- 显示在 ChatView 右下角
- 子代理完成时自动消失 (3 秒淡出)
- 点击 → 切换到 SubagentDetail 面板

---

### 模块 4: Worktree 状态 UI

**目标:** 当子代理在隔离 worktree 中完成时，提供 Apply/Discard/Retain 操作。

**现状:** 后端有完整的 worktree 生命周期 (`subagent.py:369-376`, `runtime.py` 的 `_check_session_completion` 会 block 未处理的 worktree)。前端完全缺失。

#### 后端 API (缺失)

```
GET /api/sessions/{session_id}/worktree-status
→ { has_worktree: true, disposition: "preserved", path: "...", changes_summary: "..." }

POST /api/sessions/{session_id}/worktree/apply   → 合并 worktree 变更到父工作区
POST /api/sessions/{session_id}/worktree/discard → 丢弃 worktree
POST /api/sessions/{session_id}/worktree/retain   → 保留 worktree (不合并)
```

#### 前端组件

挂载在 `SubagentDetail` 面板底部。

| 按钮 | 行为 | 颜色 |
|------|------|------|
| Apply Changes | 合并 worktree 到父工作区 | green |
| Discard | 删除 worktree | red |
| Retain | 保留 worktree (手动处理) | muted |

---

### 模块 5: Plan 生成进度流

**目标:** plan 模式下，不等到 plan_ready 才显示结果，而是实时展示 agent 的逐步推理过程。

**现状:** 
- agent 在 plan 模式下运行，事件 (thought/tool_call/observation) 通过 WS 实时推送 ✅
- 但前端将 plan 模式的 timeline 事件视为普通执行事件，没有特别的 "planning in progress" 视觉区分

**改进:** 在 ChatView 中添加 "Planning..." 状态条:

```
┌──────────────────────────────────────────┐
│ ⠹ Planning... Step 5 · 3 files explored │
│ Exploring the auth module structure...    │
└──────────────────────────────────────────┘
```

当前端检测到 `agent_name === "plan"` 或 `currentMode === "plan"` 且 `isRunning === true` 时显示。

#### 实现

仅需前端改动 `ChatView.tsx`:
- 检查 `isRunning && currentMode === "plan"`
- 显示进度条 (非侵入式，悬浮在 timeline 顶部)
- plan_ready 事件到达时自动替换为 PlanCard

---

### 模块 6: Plan 修订 Diff

**目标:** 当用户拒绝 plan 并要求修订时，可视化展示新旧 plan 的差异。

**CC 模式:** 不支持原生 diff。IPE 项目通过 PermissionRequest hook 实现了 side-by-side plan diff。

> 来源: [IPE — GitHub-style Review Interface](https://dev.to/eduardmaghakyan/building-a-local-pr-review-interface-for-claude-code-plans-57o2)

#### 后端 API (缺失)

```
GET /api/sessions/{session_id}/plan-revisions
→ [
    { revision: 1, plan_text: "...", created_at: "..." },
    { revision: 2, plan_text: "...", created_at: "..." },
  ]
```

#### 前端组件

在 `PlanView.tsx` 中添加 "Compare Revisions" 按钮，显示当前修订 vs 上一修订的 inline diff (使用简单的行级 diff 算法)。

#### 实现文件

| 文件 | 改动 |
|------|------|
| `server/routers/approvals.py` | 新增 `GET /{id}/plan-revisions` |
| `web/src/components/PlanView.tsx` | 添加 DiffView 模式 |

---

## 四、接口清单汇总

### 新增后端接口

| 方法 | 路径 | 用途 | 优先级 |
|------|------|------|--------|
| GET | `/api/sessions/{id}/tree` | 获取 session 父子树 | P0 |
| GET | `/api/sessions/{id}/worktree-status` | 获取 worktree 状态 | P0 |
| POST | `/api/sessions/{id}/worktree/apply` | 应用 worktree 变更 | P0 |
| POST | `/api/sessions/{id}/worktree/discard` | 丢弃 worktree | P0 |
| POST | `/api/sessions/{id}/worktree/retain` | 保留 worktree | P1 |
| GET | `/api/sessions/{id}/plan-revisions` | 获取 plan 修订历史 | P1 |

### 已有后端接口 (直接使用)

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/sessions/{id}/events` | 子代理事件日志 |
| GET | `/api/sessions/{id}/messages` | 子代理消息历史 |
| POST | `/api/sessions/{id}/approve` | 审批 plan |
| POST | `/api/sessions/{id}/reject` | 拒绝 plan |

### 新增前端组件

| 组件 | 用途 | 优先级 |
|------|------|--------|
| `SessionTree.tsx` | 父子 session 树形面板 | P0 |
| `SubagentDetail.tsx` | 子代理执行详情 + worktree 操作 | P0 |
| `SubagentProgress.tsx` | 后台子代理浮动进度卡片 | P0 |
| `PlanDiffView.tsx` | Plan 修订 diff 对比 | P1 |

### 前端 Store 扩展

| Store | 新增状态 |
|-------|----------|
| `sessionStore.ts` | `sessionTree`, `fetchSessionTree()` |
| `chatStore.ts` | `viewingChildSessionId`, `backgroundAgents`, `worktreeStatus` |

---

## 五、UI 布局方案

### 主布局 (三栏)

```
┌──────────┬──────────────────────┬───────────┐
│Session   │                      │ Event     │
│Tree      │    Timeline          │ Sidebar   │
│          │                      │           │
│ ● root   │  ┌────────────────┐  │ tool_call │
│  ├● ch1  │  │ SubagentCard   │  │ observ..  │
│  │ ├● gc │  │ (折叠的树)     │  │ thought   │
│  │ └● gc │  └────────────────┘  │ finish    │
│  └● ch2  │  ┌────────────────┐  │           │
│          │  │ PlanCard       │  │           │
│          │  │ (审批卡片)      │  │           │
│          │  └────────────────┘  │           │
│          │  ┌────────────────┐  │           │
│          │  │ Thought        │  │           │
│          │  │ ToolCall       │  │           │
│          │  │ Observation    │  │           │
│          │  └────────────────┘  │           │
└──────────┴──────────────────────┴───────────┘
│              Composer                        │
└──────────────────────────────────────────────┘
```

### 子代理详情视图 (覆盖 Timeline)

当用户点击 SessionTree 中的子代理节点时，Timeline 区域切换为该子代理的完整执行日志。

---

## 六、实施计划

| Batch | 内容 | 文件数 | 预计 |
|-------|------|--------|------|
| **S1** | SessionTree 后端 API | 2 | 30min |
| **S2** | SessionTree 前端组件 | 2 | 1h |
| **S3** | SubagentDetail 面板 | 2 | 1h |
| **S4** | Worktree 状态 API + UI | 3 | 1h |
| **S5** | 后台子代理进度指示器 | 2 | 30min |
| **S6** | Plan 生成进度流 | 1 | 30min |
| **S7** | Plan 修订 Diff (可选) | 2 | 1h |

**建议先做 S1-S5 (子代理完整交互)，再做 S6-S7 (plan 增强)。**

---

## 七、参考来源

- [Claude Code v2.1.172 — Nested subagents](https://code.claude.com/docs/en/whats-new/2026-w24)
- [GitHub Issue #6007 — Navigable subagent transcripts](https://github.com/anthropics/claude-code/issues/6007)
- [GitHub Issue #18924 — Interactive step-into mode](https://github.com/anthropics/claude-code/issues/18924)
- [pi-subagents — Live widget extension](https://www.npmjs.com/package/@yzlin/pi-subagents)
- [sugyan/claude-code-webui — Plan mode web UI](https://github.com/sugyan/claude-code-webui/issues/130)
- [IPE — GitHub-style plan review UI](https://dev.to/eduardmaghakyan/building-a-local-pr-review-interface-for-claude-code-plans-57o2)
- [Claude Code sub-agents docs](https://code.claude.com/docs/en/sub-agents)
- [Claude Code plan mode docs](https://raw.githubusercontent.com/claude-code-best/claude-code/79742411/docs/safety/plan-mode.mdx)
- [Tembo — Subagents practical guide 2026](https://www.tembo.io/blog/claude-code-subagents)
