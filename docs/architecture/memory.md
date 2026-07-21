# Memory 系统

## 概述

Grace Code 的记忆系统借鉴了 Claude Code 的 auto-memory 设计，分为**长期记忆**（跨会话持久化）和**短期记忆**（会话内上下文）两层。记忆以 Markdown 文件 + YAML frontmatter 格式存储在磁盘上，通过 `MemoryStore` 统一管理。

---

## 一、记忆类型

记忆分为 4 种类型，决定了注入策略和存储位置：

| 类型 | 标签 | 注入策略 | 存储位置 | 说明 |
|------|------|---------|---------|------|
| **User** | `user` | 始终注入 | ~/.grace/global/memory/ | 用户身份、偏好、专长 |
| **Feedback** | `feedback` | 始终注入 | ~/.grace/global/memory/ | 用户的纠正、已确认的规则 |
| **Project** | `project` | 按需注入 | ~/.grace/projects/\<hash\>/memory/ | 项目架构决策、构建命令 |
| **Reference** | `reference` | 按需注入 | ~/.grace/projects/\<hash\>/memory/ | 外部系统/文档指针 |

**代码位置**: `memory/models.py:20-25`

```python
class MemoryType(str, Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"
```

**注入策略** (`memory/models.py:49-51`):

```python
ALWAYS_INJECT_TYPES = frozenset({MemoryType.USER, MemoryType.FEEDBACK})
ON_DEMAND_TYPES = frozenset({MemoryType.PROJECT, MemoryType.REFERENCE})
```

`user` 和 `feedback` 类型**始终注入**到 LLM 上下文（每次 LLM 调用都携带）。`project` 和 `reference` 按需检索。

---

## 二、数据模型

### Memory（单条记忆）— `memory/models.py:127-157`

```python
@dataclass
class Memory:
    name: str                  # slug，同时也是文件名（如 "build-commands"）
    description: str           # 一行摘要
    content: str               # Markdown 正文
    metadata: MemoryMetadata   # 元数据
    updated_at: str            # ISO-8601
    anchors: list[Anchor]      # 文件/符号锚点
```

### MemoryMetadata — `memory/models.py:79-125`

```python
@dataclass
class MemoryMetadata:
    type: MemoryType       # user / feedback / project / reference
    status: MemoryStatus   # active / deprecated
    scope: MemoryScope     # session / project / global
    confidence: float      # 0.0~1.0，置信度
    ttl_seconds: int | None  # TTL，None = 永久
    expires_at: str        # 计算出的过期时间
    access_count: int      # 被读取次数
    validated_at: str      # 最后确认时间
```

**置信度系统**：
- 1.0：用户显式确认
- 0.7~0.9：LLM 高置信度提取
- 0.3~0.6：LLM 中置信度，待验证
- < 0.3：低置信度，**不注入**上下文

### Anchor（锚点）— `memory/models.py:55-76`

将记忆绑定到文件、符号或任务类型：

```python
@dataclass
class Anchor:
    kind: str           # "file" | "symbol" | "task"
    path: str | None    # 文件路径
    name: str | None    # 符号名
    value: str | None   # 任务类型
    content_hash: str   # 文件 SHA256 —— "代码即真理"
```

当锚点关联的文件内容发生变化（SHA256 不匹配），记忆会在注入时自动废弃。

### MemorySummary（摘要）— `memory/models.py:160-169`

```python
@dataclass
class MemorySummary:
    name: str
    description: str
    type: str
    updated_at: str = ""
```

用于列表展示，不含正文。

---

## 三、存储格式

### 目录结构

```
~/.grace/                              # 状态根目录（可通过 FORGE_AGENT_STATE_DIR 覆盖）
├── global/
│   └── memory/                        # 全局记忆（user + feedback 类型）
│       ├── MEMORY.md                  #   索引文件
│       ├── user-preferences.md        #   主题文件
│       └── review-rules.md
└── projects/
    └── <project-hash>/                # 项目级记忆（project + reference 类型）
        └── memory/
            ├── MEMORY.md              # 索引文件（最多 200 行 / 25KB）
            ├── build-commands.md
            ├── architecture.md
            └── archive/               # 已废弃记忆移入此目录
```

### MEMORY.md 索引格式

每行对应一条记忆，LLM 启动时注入前 200 行：

```markdown
- [build-commands](build-commands.md) — Build, test, and lint commands
- [debugging](debugging.md) — Common debugging patterns
```

### 主题文件格式（YAML frontmatter + Markdown）

```markdown
---
name: build-commands
description: Build, test, and lint commands
metadata:
  type: project
  status: active
  confidence: 0.9
anchors:
  - kind: file
    path: package.json
    content_hash: sha256...
updated_at: "2026-07-18T12:00:00+00:00"
---

## Build
npm run build

## Test
npm test
```

### TwoTierMemoryStore — `memory/store.py:893+`

```python
class TwoTierMemoryStore(MemoryStore):
    """合并项目级 + 全局级两层记忆。"""
```

- `user` 和 `feedback` 类型 → 全局 `~/.grace/global/memory/`
- `project` 和 `reference` 类型 → 项目 `~/.grace/projects/<hash>/memory/`
- 读/列表操作合并两层（同名项目优先）
- 写操作按类型路由到对应层

---

## 四、长期记忆 CRUD

所有操作通过 `MemoryStore` 类暴露。

### 读

```python
store.list_memories()         # → list[MemorySummary]  MetadataCache O(1)
store.read_memory(name)       # → Memory | None        读取完整 .md 文件
store.get_index_content()     # → str                  获取 MEMORY.md 内容
```

`list_memories()` 使用 `MetadataCache`（`memory/metadata_cache.py`），启动时扫描每个 `.md` 文件的前 30 行构建内存索引。1000 个文件 < 5ms。

### 写

```python
store.write_memory(memory, source="web_api")  # → bool  新建或覆盖
```

- 序列化为 YAML frontmatter + Markdown 写入 `{name}.md`
- 更新 `MEMORY.md` 索引
- 更新 `MetadataCache`
- 同时写入 `ExternalMemoryStore`（如果启用了 embedding）

### 删

```python
store.delete_memory(name)           # → bool  彻底删除
store.archive_memory(name)          # → bool  移入 archive/ 目录
store.deprecate_memory(name)        # → bool  标记为 deprecated
```

- `delete_memory`：物理删除文件 + 从索引移除
- `archive_memory`：移到 `archive/` 子目录（grep-able，不自动注入）
- `deprecate_memory`：状态设为 `deprecated`，不注入但不删除

### LLM 工具（从对话中操作）

通过 `tools/memory_tool.py` 暴露给 LLM：

| 工具 | LLM 调用 | 对应 Store 方法 |
|------|---------|----------------|
| `memory_read(name)` | `Read memory "name"` | `read_memory()` |
| `memory_write(name, description, content, type)` | `Save a memory` | `write_memory()` |
| `memory_list(offset, limit, type, query)` | `List memories` | `list_memories()` |
| `memory_delete(name)` | `Delete memory "name"` | `delete_memory()` |
| `memory_search(query, limit)` | `Search memories` | `ExternalMemoryStore.search_chunks()` |

---

## 五、短期记忆（Session Memory）

### SessionMemoryTracker — `memory/session_memory.py`

短期记忆在会话**运行过程中**动态构建。每次 LLM 调用后提取一次（10K token 触发，之后每 5K token 或 3 个 tool call 增量提取）。

**提取的内容结构**（中文，10 个章节）：

```markdown
## 当前状态
## 任务描述
## 涉及的文件
## 工作流程与行为规范
## 常见错误与陷阱
## 系统文档与引用
## 经验教训
## 关键成果
## 工作日志
## 未来工作
```

**触发条件**：
1. 首次触发：累计消费 10K token 后
2. 之后增量触发：每 5K token 增长，或每 3 个 tool call

### 注入时机

短期记忆通过 `_build_session_memory_context()` 在 `agent/core.py:1899` 构建，作为单独的消息注入到 LLM 上下文（不放入 system prompt，以保护 prompt cache）。

**代码位置**:
- `agent/core.py:1899-1920` — 构建 session 记忆上下文
- `agent/core.py:1229-1236` — 每轮 LLM 调用前提取

---

## 六、长期记忆注入（MemoryContext）

### 三个阶段 — `memory/context.py`

```
build_memory_section()
├── 1. Always-inject（user + feedback）→ "## Active Rules & Preferences"
│     全部匹配的记忆，完整内容注入
├── 2. Precision injection（project scope, confidence >= 0.5）
│     按 confidence DESC, access_count DESC 取 top-5
│     内容哈希验证：文件变了则 confidence 减半 + 警告
│     → "## Relevant Project Knowledge"
└── 3. Index listing（MEMORY.md 内容）
     → "## Available Memories" 供 LLM 按需 memory_read
```

### 在 agent 中的集成 — `agent/core.py`

- 构建一次，缓存整个 run（`_build_long_term_context()` line 2210）
- 作为**单独的用户消息**注入（不放入 system prompt）
- 压缩恢复：`CompactionRecovery`（`context/compaction.py:912-981`）在压缩后恢复记忆上下文

### 注入服务 — `memory/injection_service.py`

`build_injection_context()` 是单一入口，组装 4 个组件：

1. **Memory section**（来自 MemoryContext）
2. **Project rules**（`.grace/rules.md`）
3. **Skills prompt**
4. **Session context**（已完成任务的摘要）

---

## 七、跨会话合并（Consolidation）

### DreamAgent — `memory/consolidation.py`, `memory/dream_agent.py`

跨会话合并（将 session memories → 长期 semantic memory）使用一个受限的子 agent（DreamAgent）执行。

**三重门（triple gate）**：
1. **时间门**：距上次 consolidation >= 24 小时
2. **会话门**：至少 5 个新会话
3. **锁文件**：防止并发 consolidation

**流程**：
1. DreamAgent 读取所有待处理的 session memory 文件
2. 用 LLM 提取关键发现，格式化为新的长期记忆
3. 调用 `memory_write` 写入 MemoryStore
4. 清理已合并的 session 文件

---

## 八、语义搜索（Embedding）

### ExternalMemoryStore — `memory/external_store.py`

- SQLite 向量存储：`~/.grace/grace_memory.db`
- 模型：`fastembed` + `BAAI/bge-small-zh-v1.5`（33MB 中英文模型）
- 两张表：`memories`（完整条目 + embedding BLOB）、`memory_chunks`（分块 + embedding）
- 搜索：余弦相似度 × 0.85 + 新鲜度 × 0.1 + 类型权重 × 0.05
- 优雅降级：fastembed 未安装时退化为文件名/描述模糊匹配

---

## 九、记忆生命周期总结

```
                                     ┌─────────────────────────┐
                                     │   ExternalMemoryStore   │
                                     │  (embedding 语义搜索)    │
                                     └───────────┬─────────────┘
                                                 │ 同步写入
                                     ┌───────────▼─────────────┐
  LLM 通过 tool 读写 ──────→         │     MemoryStore         │
  (memory_read/write/list/delete)   │  (TwoTierMemoryStore)   │
                                     │  项目层 + 全局层        │
                                     └──┬───────────┬─────────┘
                                        │           │
                              ┌─────────▼──┐  ┌────▼────────┐
                              │ 文件系统    │  │ MetadataCache│
                              │ .md 文件    │  │ in-memory    │
                              │ MEMORY.md   │  │ O(1) 列表    │
                              └─────────────┘  └─────────────┘
                                        │
                              ┌─────────▼────────────┐
                              │  MemoryContext        │
                              │  (注入到 LLM 上下文)  │
                              │  每次 LLM 调用前构建  │
                              └─────────┬────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │      Agent Prompt Context              │
                    │  System + Always-inject + Precision   │
                    │  + Index + Session Memory + Skills    │
                    └───────────────────────────────────────┘
```

---

## 十、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/memory` | 记忆列表，支持 type/status/scope 过滤 |
| `GET` | `/api/memory/{name}` | 单条详情（含正文） |
| `POST` | `/api/memory` | 新建记忆 |
| `PATCH` | `/api/memory/{name}` | 更新记忆 |
| `DELETE` | `/api/memory/{name}` | 删除记忆 |

**代码位置**: `server/routers/memory.py`
