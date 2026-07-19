# Plan + Subagent + React 缺陷修复计划

> 基于 Claude Code 模式 + Zustand 最佳实践 + TS  discriminated union 标准

---

## Defect 1 (🔴 P0): PlanView 按钮不传 intent

### 根因

[PlanView.tsx:81](web/src/components/PlanView.tsx#L81) — `api.chat(activeId, prompt)` 不传 `intent` 参数。

CC 的做法: 用户选择 plan mode → UI 设置 intent → 后端根据 intent 切换到 plan agent definition + permission_mode="plan"。

### 治本方案

`api.chat()` 的签名接受 `intent` 参数，但 PlanView 没传。修复: 传 `intent: "analysis"`。

同时: `ChatView.tsx` 的 mode selector 已设置 `intent: "analysis"` 用于 plan mode。但 PlanView 是独立视图，不经过 ChatView 的 mode selector。PlanView 的按钮应使用与 ChatView plan mode 一致的参数。

### 改动

| 文件 | 改动 |
|------|------|
| `web/src/components/PlanView.tsx` | `api.chat()` 加 `intent: "analysis"` |

---

## Defect 2 (🟡 P1): 多子 agent 工具计数错

### 根因

[chatStore.ts](web/src/stores/chatStore.ts) — `handleWsEvent` 中 tool_call/observation 的计数逻辑:

```typescript
for (const key of Object.keys(updated)) {
    if (updated[key].status === "running") {
        updated[key] = { ...updated[key], toolCount: updated[key].toolCount + 1 };
    }
}
```

遍历所有 running 的后台 agent，全部 +1。如果两个子 agent 同时运行，一个做 tool_call，另一个的计数也会增加。

### 治本方案

tool_call/observation 事件携带 `child_session_id`。用 `child_session_id` 精确匹配:

```typescript
const csid = ev.child_session_id;
if (csid && updated[csid]?.status === "running") {
    updated[csid] = { ...updated[csid], toolCount: updated[csid].toolCount + 1, lastAction: ev.name || ev.tool_name || "" };
}
```

### 改动

| 文件 | 改动 |
|------|------|
| `web/src/stores/chatStore.ts` | tool_call/observation 计数用 child_session_id 精确匹配 |

---

## Defect 3 (🟡 P1): SessionTree 不自动刷新

### 根因

`SessionTree` 组件只在 mount 时 `fetchSessionTree(activeId)`。新的子 agent spawn 后不触发重新 fetch。

### 治本方案

监听 `subagent_start` 和 `subagent_stop` WS 事件 → 触发 `fetchSessionTree(activeId)`。

```typescript
// In SessionTree:
useEffect(() => {
    // Re-fetch tree when subagent events arrive
    if (timeline.some(item => 
        item.source === "ws" && 
        (item.ws.type === "subagent_start" || item.ws.type === "subagent_stop")
    )) {
        fetchSessionTree(activeId);
    }
}, [timeline.length]);  // timeline length changes on new events
```

### 改动

| 文件 | 改动 |
|------|------|
| `web/src/components/SessionTree.tsx` | useEffect 监听 timeline 变化 → re-fetch |

---

## Defect 4 (🟢 P2): chatStore 职责过重

### 根因

一个 store 管理 timeline, events, ws, planApproval, toolApprovals, currentMode, currentModel, viewingChildSessionId, backgroundAgents, _worktreeStates。

Zustand 最佳实践: slices within a single store。每个领域一个 slice，组合到一个 store。

来源: [Zustand official docs — slices pattern](https://docs.pmnd.rs/zustand/guides/slices-pattern), [OrchestKit Zustand patterns](https://github.com/yonatangross/orchestkit/blob/main/src/skills/zustand-patterns/SKILL.md)

### 治本方案

拆分为 5 个 slice:

```
chatStore.ts
  ├── timelineSlice     — timeline, events, sendChat, handleWsEvent
  ├── approvalSlice     — toolApprovals, planApproval, resolveToolApproval
  ├── connectionSlice   — ws, wsConnected, connectWs, disconnectWs
  ├── runtimeSlice      — isRunning, steps, tokens, currentMode, currentModel
  └── subagentSlice     — viewingChildSessionId, backgroundAgents, _worktreeStates
```

每个 slice 用 `StateCreator` 定义，`create()` 组合。

### 改动

| 文件 | 改动 |
|------|------|
| `web/src/stores/chatStore.ts` | 拆分为 5 个 slice，保持 API 不变 |

---

## Defect 5 (🟢 P2): WsMessage 无 discriminated union

### 根因

`WsMessage` 接口 20+ 可选字段，类型检查全靠 `ev.type === "xxx"` 手动判断。

TypeScript 最佳实践: discriminated union + `Extract` 工具类型。

来源: [CorvidAgent shared type layer](https://github.com/CorvidLabs/corvid-agent/issues/957), [react-socket typed events](https://www.npmjs.com/package/@luciodale/react-socket)

### 治本方案

```typescript
// 每个事件类型独立 interface
interface WsThoughtEvent { type: "thought"; content: string; step: number; ... }
interface WsToolCallEvent { type: "tool_call"; name: string; params: Record<string, unknown>; ... }
// ... 所有事件类型 ...

// Discriminated union
type WsMessage = WsThoughtEvent | WsToolCallEvent | WsObservationEvent | ...;

// Typed handler
type WsHandler<T extends WsMessage["type"]> = (ev: Extract<WsMessage, {type: T}>) => void;
```

后端 `server/events.py` 的 dataclass 字段名须与前端 interface 字段名一致。

### 改动

| 文件 | 改动 |
|------|------|
| `web/src/types/session.ts` | WsMessage → discriminated union |
| `web/src/stores/chatStore.ts` | handleWsEvent 使用类型守卫 |
| `server/events.py` | 确保字段名与前端一致 (snake_case → camelCase?) |

---

## 实施顺序

```
Batch 1: Defect 1 (PlanView intent)          — 1 file, 5min
Batch 2: Defect 2+3 (subagent计数 + tree刷新) — 2 files, 20min
Batch 3: Defect 5 (discriminated union)       — 2 files, 30min
Batch 4: Defect 4 (store split)               — 1 file, 30min (be careful)
```

每批 commit → 反思 → 继续。
