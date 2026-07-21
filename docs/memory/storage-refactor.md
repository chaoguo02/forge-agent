# Memory 存储架构根治方案

## 审计结论：3 个根因缺陷

### 缺陷 1：Web 路径初始化顺序错误（🔴）

**现状**：
```
line 152: build_registry(...)                    ← 无 memory_store，工具拿不到
line 195: self._memory_store = MemoryStore(...)   ← 太晚了
```

**后果**：所有 `memory_read`/`memory_write`/`memory_list`/`memory_delete` 工具在 web 模式下拿到的 store 是 `None`，调用即报错。

**代码**：`server/services/agent_service.py:152` vs `:195`

### 缺陷 2：CLI 路径永远用文件系统（🔴）

**现状**：`init_memory()` 创建 `TwoTierMemoryStore(repo_path=..., memory_dir=...)`，不传 `db_path`。即使重启也不会切到 SQLite。

**代码**：`entry/bootstrap/memory_bootstrap.py:44-49`

### 缺陷 3：SqliteStorageBackend 残留死方法（🟡）

**现状**：`upsert_memory_entry()`、`query_memories()`、`get_memory_entry()`、`delete_memory_entry()` 等方法在 `SqliteStorageBackend` 中，但唯一的调用方（router）已被删除。唯一还活着的是 `get_memory_overview()`（被 `main.py` 调用）。

**代码**：`app/storage/sqlite.py:483-660`

---

## 目标状态

一个统一的、唯一的写路径：

```
                   ┌──────────────────────────────┐
                   │     MemoryStore (facade)      │
                   │  backend = SqliteMemoryBackend │
                   └──────────┬───────────────────┘
                              │ 唯一写路径
                   ┌──────────▼───────────────────┐
                   │     memory_entries 表         │
                   │     (同一份 DB，所有路径共享)    │
                   └──────────────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
    Web API 路由         LLM 工具              CLI Chat
    (memory router)   (memory_read/write)   (TwoTierMemoryStore)
```

### 对比当前混乱状态

```
 当前（混乱）                         目标（统一）
 ────────────                       ────────────
 Web → SqliteMemoryBackend          Web → SqliteMemoryBackend
 CLI → TwoTierMemoryStore(file)     CLI → SqliteMemoryBackend
 Tools → None (broken)              Tools → SqliteMemoryBackend
 SqliteStorageBackend → dead code   SqliteStorageBackend → 无 memory 方法
 FileMemoryBackend → unused         FileMemoryBackend → 删掉，改为 export 工具
```

---

## 改动方案（3 batch，≤5 文件/batch）

### Batch 1：修复 Web 路径初始化顺序（2 文件）

| 文件 | 行 | 改动 |
|------|----|------|
| `server/services/agent_service.py` | 152 | 把 MemoryStore 初始化移到 build_registry 之前，传 `memory_store=self._memory_store` |
| `entry/bootstrap/registry_factory.py` | 23 | 确认 memory_store 参数正常接收（已有，不需改） |

### Batch 2：CLI 路径接入 SQLite（2 文件）

| 文件 | 行 | 改动 |
|------|----|------|
| `entry/bootstrap/memory_bootstrap.py` | 44 | `TwoTierMemoryStore` 加 `db_path=default_session_db_path(repo_path)` |
| `memory/store.py` | — | TwoTierMemoryStore.__init__ 转发 db_path 到父类（确认已有） |

### Batch 3：清理死代码（3 文件）

| 文件 | 行 | 改动 |
|------|----|------|
| `app/storage/sqlite.py` | 483-660 | 删除 `upsert_memory_entry`、`query_memories`、`get_memory_entry`、`delete_memory_entry`、`get_memory_overview`、`sync_memory_from_files`、`decay_confidences`、`set_memory_anchors`、`get_memory_anchors` |
| `server/main.py` | 181 | `get_memory_overview()` 调用改为从 MemoryStore 读取 |
| `memory/file_backend.py` | 全部 | 文件保留为 export 工具入口，移除 MemoryBackend 协议实现 |

---

## 验证

每批后验证：

### Batch 1
```bash
# 确认 AgentService 初始化顺序
python -c "
from server.services.agent_service import AgentService
# 应能成功创建，不报 memory_store 为 None
print('AgentService OK')
"
```

### Batch 2
```bash
# 确认 CLI path 也写 SQLite
python -c "
from entry.bootstrap.memory_bootstrap import init_memory
# 需 mock config，手动验证
print('init_memory OK')
"
```

### Batch 3
```bash
# 确认 SqliteStorageBackend 不再有 memory 方法
python -c "
from app.storage.sqlite import SqliteStorageBackend
assert not hasattr(SqliteStorageBackend, 'upsert_memory_entry')
print('Dead code removed')
"
```
