# Sessions — REST API

## 资源定义

```
/api/sessions          → Session 集合
/api/sessions/{id}     → 单个 Session
```

Session 是 agent 执行的最小隔离单元。每个 session 包含：
- 元数据（agent_name, status, repo_path, 时间戳）
- 消息列表（user/assistant/tool 消息）
- 子 session 树（subagent fork）
- EventLog（原始执行事件）

## Endpoints

### POST /api/sessions

创建 session。

```json
// Request
{ "agent_name": "build", "repo_path": "/repo", "title": "optional" }

// Response 200
{ "session_id": "a1b2c3d4e5f6", "agent_name": "build",
  "status": "queued", "repo_path": "/repo",
  "created_at": "2026-07-18T09:00:00Z" }
```

### GET /api/sessions

列出 sessions（按 updated_at DESC）。

```
Query: ?limit=50&offset=0

Response 200:
[{ "id": "...", "agent_name": "build", "title": "...",
   "status": "completed", "summary": "...",
   "created_at": "...", "updated_at": "..." }]
```

### GET /api/sessions/{id}

获取 session 详情。

```
Response 200:
{ "id": "...", "parent_id": null, "root_id": "...",
  "agent_name": "build", "status": "completed",
  "mode": "primary", "summary": "...",
  "agent_kind": "primary", "agent_depth": 0,
  "created_at": "...", "updated_at": "...",
  "completed_at": "...", "metadata": {} }
```

### PATCH /api/sessions/{id}

更新 session（预留）。

```json
// Request
{ "status": "cancelled" }

// Response 200
{ "accepted": true }
```

### DELETE /api/sessions/{id}

删除 session（预留）。

```
Response 200: { "deleted": true }
Response 404: session 不存在
```

## 消息子资源

```
/api/sessions/{id}/messages
```

### GET /api/sessions/{id}/messages

获取会话消息。

```
Response 200:
[{ "role": "user", "content": "...", "tool_calls": null },
 { "role": "assistant", "content": "...",
   "tool_calls": [{"name": "Read", "params": {...}}] },
 { "role": "tool", "content": "...", "tool_call_id": "call_xxx" }]
```

### POST /api/sessions/{id}/messages

发送消息，触发 agent 执行（异步）。

```json
// Request
{ "prompt": "fix the bug", "agent_name": null, "intent": null }

// Response 202
{ "accepted": true }
```

执行事件通过 WebSocket 推送。见 `docs/execution/README.md`。

## 事件日志子资源

```
/api/sessions/{id}/events
```

### GET /api/sessions/{id}/events

获取原始 EventLog 事件。

```
Query: ?after=0&limit=1000

Response 200:
{ "events": [{ "event_id": "...", "event_type": "action",
               "task_id": "...", "timestamp": "...",
               "payload": {...}}],
  "total": 1, "has_more": false }
```

## 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | OK |
| 202 | Accepted（异步操作已触发）|
| 404 | Session 不存在 |
| 422 | 请求体校验失败 |
| 500 | 内部错误 |
