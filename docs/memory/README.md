# Memory — 长期记忆 API

## 概述

Memory 模块管理 agent 的跨会话长期记忆。所有记忆存储在 SQLite `memory_entries` 表中（与 sessions 共用同一数据库文件）。

## 存储架构

```
MemoryStore (门面)
  └── SqliteMemoryBackend (主存储)
        ├── memory_entries 表 (记忆条目)
        └── memory_anchors 表 (文件/符号锚点)

导出 (可选)
  └── FileMemoryBackend → .md 文件 (export_to_files)
```

写路径：MemoryStore.write_memory() → SqliteMemoryBackend → SQLite

## 数据模型

```python
@dataclass
class Memory:
    name: str               # slug
    description: str         # 一行摘要
    content: str             # Markdown 正文
    metadata: MemoryMetadata
    updated_at: str          # ISO-8601
    anchors: list[Anchor]

@dataclass
class MemoryMetadata:
    type: MemoryType        # "user" | "feedback" | "project" | "reference"
    status: MemoryStatus    # "active" | "deprecated"
    scope: MemoryScope      # "session" | "project" | "global"
    confidence: float       # 0.0~1.0
    access_count: int

@dataclass
class Anchor:
    kind: str              # "file" | "symbol" | "task"
    path: str | None
    name: str | None
    value: str | None
    content_hash: str      # 文件 SHA256
```

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/memory` | 列表，返回 `{ items, overview }`，支持 type/status/scope/confidence_min/limit/offset |
| `GET` | `/api/memory/search?q=...` | 语义搜索（需 fastembed） |
| `GET` | `/api/memory/{name}` | 详情，含 content + anchors |
| `POST` | `/api/memory` | 新建，文件 + DB |
| `PATCH` | `/api/memory/{name}` | 更新 |
| `DELETE` | `/api/memory/{name}` | 删除 |

## 验证

```bash
# 列表
curl -s http://127.0.0.1:8765/api/memory | python -m json.tool

# 详情
curl -s http://127.0.0.1:8765/api/memory/{name} | python -m json.tool

# 新建
curl -s -X POST http://127.0.0.1:8765/api/memory \
  -H "Content-Type: application/json" \
  -d '{"name":"test-mem","description":"Test","content":"# Test"}' | python -m json.tool

# 删除
curl -s -X DELETE http://127.0.0.1:8765/api/memory/test-mem | python -m json.tool
```
