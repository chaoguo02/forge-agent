# Execution — 异步执行与 WebSocket 事件

## 核心流程

```
Client                             Server
  │                                  │
  ├─ WS /api/ws/sessions/{id} ──────→  ① 连接 WebSocket
  │                                  │
  ├─ POST .../messages ─────────────→  ② 发送消息
  │    { "prompt": "..." }           │
  │    ← 202 { "accepted": true }    │  立即返回
  │                                  │
  │←─ WS: {type:"status",status:"running"} ③ 开始执行
  │←─ WS: {type:"thought",content:"..."}   ④ ReAct 循环
  │←─ WS: {type:"tool_call",name:"Read",params:{...}}
  │←─ WS: {type:"observation",tool_name:"Read",output:"..."}
  │←─ WS: {type:"status",status:"completed",result:{...}}  ⑤ 完成
  │                                  │
  ├─ GET .../messages ──────────────→  ⑥ 获取完整历史
  │    ← 200 [messages...]           │
```

## WebSocket 事件协议

### 连接

```
WS /api/ws/sessions/{session_id}
```

### 客户端 → 服务端

```json
{"action": "cancel"}     // 取消执行
{"action": "ping"}       // 心跳，服务端回应 {"type": "pong"}
```

### 服务端 → 客户端

所有事件共享字段：

```typescript
{
  type: string;       // 事件类型
  timestamp?: string;  // ISO-8601
  step?: number;       // ReAct 步骤数
}
```

#### status — session 状态变更

```json
{"type": "status", "status": "running"}
{"type": "status", "status": "completed", "result": {"summary":"...","steps_taken":5,"total_tokens":10000}}
{"type": "status", "status": "failed", "error": "..."}
{"type": "status", "status": "finish", "message": "Task complete!"}
{"type": "status", "status": "gave_up", "message": "Cannot proceed"}
```

#### thought — 模型思考

```json
{"type": "thought", "content": "I need to read the file first...", "step": 1}
```

#### tool_call — 工具调用

```json
{"type": "tool_call", "step": 1, "name": "Read",
 "params": {"path": "/repo/src/main.py"}, "id": "call_abc"}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 工具名: Read/Write/Edit/Grep/Glob/Bash/WebFetch/Agent 等 |
| `params` | object | 工具参数 |
| `id` | string | 工具调用 ID，与 observation 的 tool_call_id 关联 |

#### observation — 工具结果

```json
{"type": "observation", "step": 1, "tool_name": "Read",
 "status": "success", "output": "file content..."}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_name` | string | 工具名 |
| `status` | string | `success` / `error` |
| `output` | string | 工具输出（前 200 字符）|
| `error` | string | 错误信息 |

#### reflection — 模型反思

```json
{"type": "reflection", "content": "The approach seems correct..."}
```

#### subagent_start / subagent_stop — 子 agent

```json
{"type": "subagent_start", "child_session_id": "def456", "agent_name": "explore"}
{"type": "subagent_stop", "child_session_id": "def456", "status": "completed"}
```

## 事件翻译（后端）

`agent/task.Event` → WS 消息。位置：`server/services/event_bus.py:_translate_event()`

| EventType | WS 消息 |
|-----------|---------|
| `task_start` | `{type: "status", status: "running"}` |
| `action` (有 thought) | `{type: "thought", content: "..."}` |
| `action` (有 tool_calls) | `{type: "tool_call", name, params}` (每个 tool_call 一条) |
| `action` (finish/give_up) | `{type: "status", status: "finish"/"gave_up", message}` |
| `observation` | `{type: "observation", tool_name, output}` |
| `reflection` | `{type: "reflection", content}` |
| `subagent_start` | `{type: "subagent_start", child_session_id, agent_name}` |
| `subagent_stop` | `{type: "subagent_stop", child_session_id, status}` |
| `task_complete` | `{type: "status", status: "completed", result}` |
| `task_failed` | `{type: "status", status: "failed", error}` |

## 时序保证

1. **必须先连 WS，再 POST messages** — 否则可能丢事件
2. **status:running** 是第一条事件 — 确认执行已开始
3. **status:completed/failed** 是最后一条 — 确认执行已结束
4. 执行结束后调用 `GET .../messages` 获取完整历史

## 前端渲染

| WS 事件 | 前端组件 | 样式 |
|---------|---------|------|
| `thought` | WsEventBlock | 灰色斜体 `🤔 ...` |
| `tool_call` | WsEventBlock | `🔧 工具名 { 参数 }` |
| `observation` | WsEventBlock | `✓/⚠ 等宽结果` |
| `reflection` | WsEventBlock | `💭 反思内容` |
| `subagent_start` | WsEventBlock | `⊞ Subagent explore started` |
| `subagent_stop` | WsEventBlock | `⊟ Subagent completed` |
| `status:running` | ChatView | 按钮 "● Running" + loading dots |
| `status:completed` | ChatView | 按钮恢复，刷新 messages |

## 取消执行

```
POST /api/sessions/{id}/cancel
{"detail": "user cancelled"}

Response 200: {"cancelled": true}
```

或通过 WebSocket：
```json
{"action": "cancel"}
```
