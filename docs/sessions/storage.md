# Storage Backend Protocol

## 设计目标

- 当前用 SQLite，后续迁移到 Redis
- 存储选择对业务层透明
- 切换后端只需改配置

## 抽象接口

```python
class SessionStorage(Protocol):
    """Session 存储抽象。SQLite 和 Redis 都实现这个接口。"""

    # ── Session CRUD ──────────────────────────────────────────────────

    def create_session(
        agent_name: str, repo_path: str, title: str = "",
        parent_id: str | None = None,
    ) -> SessionRecord: ...

    def get_session(id: str) -> SessionRecord | None: ...

    def list_sessions(limit: int = 50, offset: int = 0) -> list[SessionRecord]: ...

    def update_status(id: str, status: SessionStatus, error: str = "") -> None: ...

    def set_summary(id: str, summary: str, *, status: SessionStatus) -> None: ...

    def delete_session(id: str) -> bool: ...

    # ── Messages ──────────────────────────────────────────────────────

    def append_message(session_id: str, message: LLMMessage) -> None: ...

    def list_messages(session_id: str) -> list[LLMMessage]: ...

    def count_messages(session_id: str) -> int: ...

    # ── Child sessions ────────────────────────────────────────────────

    def list_child_sessions(parent_id: str) -> list[SessionRecord]: ...

    # ── Agent notifications ───────────────────────────────────────────

    def append_notification(notification: AgentCompletionNotification) -> None: ...

    def claim_pending_notifications(parent_id: str) -> list: ...

    # ── Storage admin ─────────────────────────────────────────────────

    def get_stats() -> StorageStats: ...

    def ping() -> bool: ...
```

## 返回类型

```python
@dataclass
class StorageStats:
    """存储统计，前端可展示。"""
    backend: str                     # "sqlite" | "redis"
    total_sessions: int
    total_messages: int
    db_size_bytes: int | None       # SQLite 文件大小
    uptime: str                     # 存储层运行时间
```

## SQLite 实现

当前路径：`~/.grace/projects/{project_hash}/sessions/sessions.db`

### 表结构

```sql
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,           -- 12 位 hex
    parent_id       TEXT NULL,                  -- 父 session id
    root_id         TEXT NOT NULL,              -- 根 session id
    agent_name      TEXT NOT NULL,              -- agent 定义名
    mode            TEXT NOT NULL,              -- primary | subagent
    title           TEXT NOT NULL,              -- 标题
    status          TEXT NOT NULL,              -- queued|running|completed|failed|cancelled
    repo_path       TEXT NOT NULL,              -- 仓库路径
    summary         TEXT NOT NULL DEFAULT '',
    error           TEXT NOT NULL DEFAULT '',
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    agent_kind      TEXT NOT NULL DEFAULT 'primary',
    context_origin  TEXT NOT NULL DEFAULT 'fresh',
    execution_placement TEXT NOT NULL DEFAULT 'foreground',
    workspace_mode  TEXT NOT NULL DEFAULT 'current',
    agent_depth     INTEGER NOT NULL DEFAULT 0,
    run_generation  INTEGER NOT NULL DEFAULT 0,
    agent_result_json TEXT NULL,
    fork_result_json TEXT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT NULL
);

CREATE TABLE session_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,              -- user|assistant|tool
    content         TEXT NOT NULL,
    tool_call_id    TEXT NULL,
    tool_name       TEXT NULL,
    tool_calls_json TEXT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE agent_notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id TEXT NOT NULL,
    child_session_id  TEXT NOT NULL,
    generation      INTEGER NOT NULL DEFAULT 0,
    payload_json    TEXT NOT NULL,
    delivery_state  TEXT NOT NULL,              -- pending|delivered
    created_at      TEXT NOT NULL,
    delivered_at    TEXT NULL,
    UNIQUE(child_session_id, generation)
);
```

### SQLite 包装

现有 `agent/session/session_store.py:SessionStore` 实现上述所有接口。
构造：`SessionStore(db_path)`，自动建表 + 迁移。

## EventLog 存储

不在 SQLite 中。每条 EventLog 是一个独立 JSONL 文件：

```
~/.grace/projects/{hash}/logs/{task_id}_{timestamp}.jsonl
```

格式：每行一个 JSON 对象，`\n` 分隔，`ensure_ascii=False`。

```python
# 读取
log = EventLog.open_existing(path)
events = log.replay()  # → list[Event]

# 按 session 查找
events_dir = state_paths.logs  # ~/.grace/projects/{hash}/logs/
for f in events_dir.glob("*.jsonl"):
    for line in f.read_text().splitlines():
        event = json.loads(line)
```

## Redis 迁移规划

```python
class RedisStorageBackend:
    """未来实现。key 设计："""

    # Session
    #   session:{id}          → Hash (所有字段)
    #   sessions:all          → SortedSet (updated_at → id)
    #
    # Messages
    #   session:{id}:messages  → List (每个元素是序列化的 Message)
    #
    # Notifications
    #   session:{id}:notifications → List
```

## 配置

```yaml
# config/default.yaml
storage:
  backend: "sqlite"           # "sqlite" | "redis"
  redis_url: ""               # redis://localhost:6379/0
```

## 当前存在的问题

1. **没有通用 list_sessions()** — 之前只有 list_child_sessions()
   已补充，按 updated_at DESC 排序
2. **EventLog 与 SessionStore 分离** — 查询 events 需要扫描文件系统
3. **没有分页查询 messages** — 当前一次性返回全部
