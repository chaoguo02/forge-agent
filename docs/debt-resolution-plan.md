# 技术债务清偿计划：Worktree / EventBus / PlanRevision

> 基于 Claude Code 模式 + 行业最佳实践。不修补，不妥协，从根上改。

---

## Debt 1: Worktree 异步化

### 现状问题

`SessionRuntime.resolve_worktree()` 在 API 线程中同步调用 `apply_worktree()`。git merge 操作可能耗时数秒，阻塞 HTTP 请求。

### 目标

API 提交命令 → Runtime 后台处理 → WS 推送结果。API 立即返回 202 Accepted。

### CC 的做法

CC 使用 **thread + notification queue** 模式：
- 慢操作（worktree apply）委托给 daemon 线程
- 主循环继续处理其他工作
- 结果注入到对话上下文

**来源:** [Claude Code async subagents](https://deepwiki.com/anthropics/claude-code/3.1-agent-system-and-subagents)

### 设计方案

```
POST /api/sessions/{id}/worktrees/{child_id}/apply
  → 202 Accepted {command_id, status: "queued"}
  → Runtime._worktree_queue.put((parent_id, child_id, "apply"))
  → daemon thread pop queue → apply_worktree()
  → 更新 WorktreeDisposition
  → WS push: {type: "worktree_resolved", command_id, status: "applied"}
```

### 数据模型

```python
@dataclass
class WorktreeCommand:
    command_id: str       # uuid4 hex
    parent_session_id: str
    child_session_id: str
    action: str           # "apply" | "discard" | "retain"
    status: str           # "queued" | "processing" | "applied" | "discarded" | "retained" | "failed"
    error: str
    created_at: float
```

### 状态机

```
queued → processing → applied
       → processing → discarded
       → processing → retained
       → processing → failed
```

### 幂等保证

- 同一个 (child_session_id, action) 组合只处理一次
- `WorktreeDisposition.PRESERVED` 检查防止重复 apply

### 实施步骤

1. `agent/session/runtime.py`: 添加 `_worktree_queue: queue.Queue` + daemon worker
2. `agent/session/runtime.py`: `resolve_worktree()` → `enqueue_worktree_command()` 返回 command_id
3. `server/routers/sessions.py`: POST 返回 202 + command_id
4. WS push: `runtime` worker 完成后 publish 到 EventBus
5. 前端: 轮询 command 状态或响应 WS 事件

### 涉及文件

| 文件 | 改动 |
|------|------|
| `agent/session/runtime.py` | Queue + worker + enqueue 方法 |
| `server/routers/sessions.py` | 202 响应 + command_id |
| `server/services/event_bus.py` | worktree_resolved 事件翻译 |

---

## Debt 2: EventBus 类型化

### 现状问题

- `_translate_event` 手动构建 dict，20+ 可选字段的 `WsMessage` 接口
- `child_session_id` 用 `getattr(event, "child_session_id", None)` 动态属性
- 前后端类型分别维护，容易不一致

### 目标

Python dataclass 定义事件 → 序列化 → TypeScript interface。一个 schema，两端使用。

### 行业最佳实践

- **Schema-first**: Valibot/Zod 运行时验证，TypeScript 类型从 schema 推导
- **Shared type layer**: 服务端和客户端共享类型定义
- **Discriminated union**: `type` 字段作为判别器，每个子类型有独立 interface

**来源:** [Valibot schema validation](https://github.com/ms2sato/agent-console/issues/471), [LangGraph CDDL protocol](https://github.com/langchain-ai/agent-protocol/blob/main/streaming/protocol.cddl)

### 设计方案

**Step 1: 定义事件 dataclass**

```python
# server/events.py
from dataclasses import dataclass, field
from typing import Any, Literal

@dataclass
class WsThought:
    type: Literal["thought"] = "thought"
    content: str = ""
    step: int = 0
    child_session_id: str = ""
    timestamp: str = ""

@dataclass
class WsToolCall:
    type: Literal["tool_call"] = "tool_call"
    name: str = ""
    params: dict = field(default_factory=dict)
    step: int = 0
    id: str = ""
    child_session_id: str = ""
    timestamp: str = ""

# ... 其他事件类型 ...

# Discriminated union
WsEvent = WsThought | WsToolCall | WsObservation | WsStatus | ...
```

**Step 2: 序列化/反序列化**

```python
import json

def event_to_dict(event: WsEvent) -> dict:
    """Serialize with type discriminator."""
    return {k: v for k, v in asdict(event).items() if v}  # skip empty

# TypeScript 端对应 interface（可以从 Python 生成或手动同步）
```

**Step 3: 替换 `_translate_event`**

```python
# 旧: return [{"type": "thought", "content": thought, ...}]
# 新: return [event_to_dict(WsThought(content=thought, step=step, ...))]
```

**Step 4: 前端类型同步**

在 `web/src/types/events.ts` 中定义对应的 TypeScript discriminated union。

### 实施步骤

1. 创建 `server/events.py` — 所有 WS 事件 dataclass
2. 修改 `_translate_event` — 返回 dataclass 而非 dict
3. 修改 `publish_raw` — 接受 dataclass 并序列化
4. 前端 `types/session.ts` 中 `WsMessage` 改为 discriminated union
5. 前端 `chatStore.ts` 的 `handleWsEvent` 使用类型守卫

### 涉及文件

| 文件 | 改动 |
|------|------|
| `server/events.py` | **NEW** — 所有事件 dataclass |
| `server/services/event_bus.py` | `_translate_event` 返回 dataclass |
| `web/src/types/events.ts` | **NEW** — 同步的 TS 类型 |
| `web/src/types/session.ts` | `WsMessage` → discriminated union |
| `web/src/stores/chatStore.ts` | `handleWsEvent` 使用类型守卫 |

---

## Debt 3: PlanRevision SQLite 化

### 现状问题

`PlanRevisionService` 用 JSON 文件存储 plan 修订历史：
- 并发不安全（两个请求同时写会覆盖）
- 无事务保证
- 大文件性能退化

### 目标

迁移到 SQLite 表，使用已有的 `SqliteStorageBackend`。

### 行业最佳实践

- **WAL 模式**: `PRAGMA journal_mode = WAL` — 并发读 + 单写
- **版本化迁移**: schema_version 表，顺序执行迁移
- **双写兼容**: 迁移期间同时写 SQLite 和 JSON，旧数据一次性导入

**来源:** [agent-coworker session storage](https://deepwiki.com/mweinbach/agent-coworker/2.4-session-persistence-and-backup), [cagent database architecture](https://deepwiki.com/docker/cagent/9.2-database-architecture)

### 数据模型

```sql
CREATE TABLE IF NOT EXISTS plan_revisions (
    id TEXT PRIMARY KEY,           -- {session_id}_{revision}
    session_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,    -- SHA256[:16]
    parent_revision INTEGER DEFAULT 0,
    change_request TEXT DEFAULT '',
    status TEXT DEFAULT 'pending', -- pending|approved|rejected|superseded
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_plan_revisions_session
    ON plan_revisions(session_id, revision);
```

### 迁移策略

1. 添加 schema_version 表
2. 在 `SqliteStorageBackend` 中添加 `plan_revisions` 表创建
3. `PlanRevisionService` 从 JSON 文件读取 → 插入 SQLite（一次性导入）
4. 新代码只读 SQLite，不再写 JSON
5. 保留 JSON 文件作为备份（不删除）

### 双写兼容（迁移期间）

```python
def append_revision(self, session_id, content, ...):
    rev = PlanRevision.create(...)
    # 主存储: SQLite
    self._storage.insert_plan_revision(rev)
    # 兼容: 仍写 JSON（可后续移除）
    self._save_json(session_id, rev)
    return rev
```

### 实施步骤

1. `app/storage/sqlite.py`: 添加 `plan_revisions` 表 + 索引 + CRUD 方法
2. `server/services/plan_revision_service.py`: 切换到 SQLite 后端
3. 迁移脚本: 导入现有 JSON 文件到 SQLite
4. 移除 JSON 文件写操作（读保留作为 fallback）

### 涉及文件

| 文件 | 改动 |
|------|------|
| `app/storage/sqlite.py` | plan_revisions 表 + 方法 |
| `server/services/plan_revision_service.py` | SQLite 后端 |
| `server/services/agent_service.py` | 初始化迁移 |

---

## 实施顺序

```
Batch D1: PlanRevision SQLite — 表创建 + 迁移 + 双写
Batch D2: PlanRevision SQLite — 移除 JSON 写
Batch D3: EventBus — 创建 events.py dataclass
Batch D4: EventBus — _translate_event 替换
Batch D5: EventBus — 前端类型同步
Batch D6: Worktree — Queue + daemon worker
Batch D7: Worktree — 202 API + WS push + 前端
```

每批 ≤3 文件。

---

## 参考来源

- [Claude Code async subagents](https://deepwiki.com/anthropics/claude-code/3.1-agent-system-and-subagents)
- [Claude Code worktree docs](https://code.claude.com/docs/en/worktrees)
- [agent-coworker session storage design](https://deepwiki.com/mweinbach/agent-coworker/2.4-session-persistence-and-backup)
- [cagent database architecture](https://deepwiki.com/docker/cagent/9.2-database-architecture)
- [Valibot WebSocket schema validation](https://github.com/ms2sato/agent-console/issues/471)
- [LangGraph CDDL streaming protocol](https://github.com/langchain-ai/agent-protocol/blob/main/streaming/protocol.cddl)
- [CorvidLabs shared type layer](https://github.com/CorvidLabs/corvid-agent/issues/957)
