# Grace Code Web MVP — API 接口文档

Base URL: `http://127.0.0.1:18770`
OpenAPI: `http://127.0.0.1:18770/docs`

---

## Sessions

### POST /api/sessions — 创建 session

创建新的 root session。

**Request Body:**
```json
{
  "agent_name": "build",        // string, Agent definition 名称
  "repo_path": "/path/to/repo", // string, 仓库绝对路径
  "title": "optional title"     // string, 可选 session 标题
}
```

**Response 200:**
```json
{
  "session_id": "a1b2c3d4e5f6",  // string, 12 位 hex session ID
  "agent_name": "build",
  "status": "queued",
  "repo_path": "D:\\repo",
  "created_at": "2026-07-18T09:05:46+00:00"
}
```

---

### GET /api/sessions — 列出 sessions

**Query Parameters:**
```
limit  (int, default 50)  最大返回数
offset (int, default 0)   分页偏移
```

**Response 200:**
```json
[
  {
    "id": "a1b2c3d4e5f6",
    "agent_name": "build",
    "title": "Web MVP Root Session",
    "status": "queued",
    "mode": "primary",
    "summary": "",
    "error": "",
    "parent_id": null,
    "created_at": "2026-07-18T09:05:46+00:00",
    "updated_at": "2026-07-18T09:05:46+00:00",
    "completed_at": null
  }
]
```

**Error 500:** 内部错误

---

### GET /api/sessions/{session_id} — 获取 session 详情

**Path Parameters:**
```
session_id  string  12 位 hex session ID
```

**Response 200:**
```json
{
  "id": "a1b2c3d4e5f6",
  "parent_id": null,
  "root_id": "a1b2c3d4e5f6",
  "agent_name": "build",
  "title": "Web MVP Root Session",
  "status": "completed",
  "mode": "primary",
  "summary": "Hello! How can I help?",
  "error": "",
  "agent_kind": "primary",
  "context_origin": "fresh",
  "execution_placement": "foreground",
  "workspace_mode": "current",
  "agent_depth": 0,
  "generation": 0,
  "created_at": "2026-07-18T09:05:46+00:00",
  "updated_at": "2026-07-18T09:35:46+00:00",
  "completed_at": "2026-07-18T09:35:46+00:00",
  "metadata": {}
}
```

**Error 404:** Session 不存在

---

### GET /api/sessions/{session_id}/messages — 获取会话消息

**Path Parameters:**
```
session_id  string  12 位 hex session ID
```

**Response 200:**
```json
[
  {
    "role": "user",
    "content": "say hello back",
    "tool_calls": null,
    "tool_call_id": null
  },
  {
    "role": "assistant",
    "content": "Hello! 👋 ...",
    "tool_calls": [
      {
        "name": "Read",
        "params": { "path": "src/file.py" },
        "id": "call_abc"
      }
    ],
    "tool_call_id": null
  },
  {
    "role": "tool",
    "content": "file contents...",
    "tool_calls": null,
    "tool_call_id": "call_abc"
  }
]
```

**Error 404:** Session 不存在

---

### GET /api/sessions/{session_id}/events — 获取 EventLog 事件

从 agent 的 JSONL 日志文件读取原始执行事件。

**Path Parameters:**
```
session_id  string  12 位 hex session ID
```

**Query Parameters:**
```
after  (int, default 0)    跳过前 N 条
limit  (int, default 1000) 最大返回条数
```

**Response 200:**
```json
{
  "events": [
    {
      "event_id": "abc12345",
      "event_type": "action",
      "task_id": "xyz789",
      "timestamp": "2026-07-18T09:35:00+00:00",
      "payload": {
        "step": 1,
        "action": {
          "action_type": "react",
          "thought": "I need to...",
          "tool_calls": []
        }
      }
    }
  ],
  "total": 1,
  "has_more": false
}
```

**Error 404:** Session 不存在

---

### POST /api/sessions/{session_id}/chat — 执行 ReAct agent 循环（异步）

**核心端点。** 立即返回 202，所有执行事件通过 WebSocket 推送。

**Path Parameters:**
```
session_id  string  12 位 hex session ID
```

**Request Body:**
```json
{
  "prompt": "fix the bug in src/main.py",  // string, required, 任务描述
  "agent_name": null,                       // string | null, 覆盖 agent 定义
  "intent": null                            // string | null, "edit" | "analysis"
}
```

**Response 202:**
```json
{
  "session_id": "a1b2c3d4e5f6",
  "status": "running"
}
```

**Error 404:** Session 不存在 | **Error 422:** prompt 为空

> **注意：** 必须在调用此端点**之前**连接 WebSocket `/api/ws/sessions/{session_id}`
> 才能收到实时执行事件。

---

### POST /api/sessions/{session_id}/cancel — 取消运行中的 session

**Path Parameters:**
```
session_id  string  12 位 hex session ID
```

**Request Body:**
```json
{
  "detail": "User cancelled via UI"  // string, 取消原因
}
```

**Response 200:**
```json
{
  "cancelled": true   // bool, true=取消信号已发送
}
```

---

## Approvals

### POST /api/sessions/{session_id}/approve

批准待审批的 plan 或 worktree 结果。

**Path Parameters:**
```
session_id  string
```

**Request Body:**
```json
{
  "comment": "Looks good"  // string, optional
}
```

**Response 200:**
```json
{
  "approved": true,
  "session_id": "a1b2c3d4e5f6",
  "status": "approved"
}
```

---

### POST /api/sessions/{session_id}/reject

拒绝待审批的 plan 或 worktree 结果。

**Path Parameters:**
```
session_id  string
```

**Request Body:**
```json
{
  "reason": "Need more details"  // string, required
}
```

**Response 200:**
```json
{
  "approved": false,
  "session_id": "a1b2c3d4e5f6",
  "status": "rejected"
}
```

**Error 422:** 缺少 rejection reason

---

### GET /api/sessions/{session_id}/pending-approvals

列出 session 的待审批项。

**Path Parameters:**
```
session_id  string
```

**Response 200:**
```json
[]
```
当前返回空数组（MEP 阶段待审批追踪未实现）。

---

## WebSocket

### WS /api/ws/sessions/{session_id} — 实时事件流

**协议：** 客户端连接后，服务端推送 JSON 消息。客户端可以发送 `{"action": "cancel"}` 取消执行。

**标准事件格式（所有事件）：**
```typescript
{
  type: string;      // 事件类型
  timestamp?: string; // ISO-8601
  step?: number;      // ReAct 步骤
}
```

#### status — session 状态变更

```json
{"type": "status", "status": "running"}
{"type": "status", "status": "completed", "result": {"summary": "...", "steps_taken": 5, "total_tokens": 10000}}
{"type": "status", "status": "failed", "error": "error message"}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `running` / `completed` / `failed` / `finish` / `gave_up` |
| `result.summary` | string | agent 最终摘要（仅 completed） |
| `result.steps_taken` | int | 执行步数（仅 completed） |
| `result.total_tokens` | int | 消耗 token 数（仅 completed） |
| `error` | string | 错误信息（仅 failed） |

#### thought — 模型思考内容

```json
{"type": "thought", "content": "I need to read the file first to understand its structure...", "step": 1}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | string | 模型的思考文本 |

#### tool_call — 工具调用

```json
{
  "type": "tool_call",
  "step": 1,
  "name": "Read",
  "params": {"path": "/repo/src/main.py"},
  "id": "toolu_abc123"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 工具名（Read / Edit / Grep / Bash 等） |
| `params` | object | 工具参数 |
| `id` | string | 工具调用 ID |

#### observation — 工具执行结果

```json
{
  "type": "observation",
  "step": 1,
  "tool_name": "Read",
  "status": "success",
  "output": "def hello():\n    print('hello')"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_name` | string | 工具名 |
| `status` | string | `success` / `error` |
| `output` | string | 工具输出（前 200 字符） |
| `error` | string | 错误信息 |

#### reflection — 模型反思

```json
{"type": "reflection", "content": "The approach seems correct, but I should verify..."}
```

#### subagent_start / subagent_stop — 子 agent 生命周期

```json
{"type": "subagent_start", "child_session_id": "def456", "agent_name": "explore"}
{"type": "subagent_stop", "child_session_id": "def456", "status": "completed"}
```

---

## 前端渲染映射

| WS 事件 | 前端渲染 |
|---------|---------|
| `thought` | 灰色斜体思考块 `🤔 ...` |
| `tool_call` | 🔧 工具卡片（名称 + 参数） |
| `observation` | ✓/⚠ 等宽结果行（前 200 字符） |
| `reflection` | 💭 斜体反思 |
| `subagent_start` | ⊞ Subagent xxx started |
| `subagent_stop` | ⊟ Subagent completed |
| `status: running` | 按钮显示 "● Running" |
| `status: completed` | 刷新 messages，按钮恢复 |

## 执行时序

```
Client                     Server
  │                          │
  ├─ WS /api/ws/sessions/X ──→  连接 WebSocket
  │                          │
  ├─ POST .../chat ──────────→  202 Accepted
  │                          │  [后台执行开始]
  │←── WS: {status:running} ──┐
  │←── WS: {thought:...}    ──┤
  │←── WS: {tool_call:...}  ──┤  ReAct 循环
  │←── WS: {observation:...}─┤
  │←── WS: {thought:...}    ──┤
  │←── WS: {status:completed}─┘
  │                          │
  ├─ GET /messages ──────────→  获取完整历史
  │                          │
```
