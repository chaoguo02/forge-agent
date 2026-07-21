# Memory 系统评估：对标行业方案

## 对比框架

基于对 Mem0、Letta/MemGPT、LangChain Memory、FluxMem、SAGE 等主流方案的调研，本文从 12 个维度评估我们的系统，打分 1-5，并指出半成品状态和改进方向。

---

## 评分总表

| # | 维度 | 分数 | 行业最佳 | 我们的差距 |
|---|------|------|---------|-----------|
| 1 | 存储后端 | 2/5 | Mem0: 向量+图+KV 三重 | 纯文件系统，无 DB 查询 |
| 2 | 记忆类型 | 4/5 | Mem0: 4 类对等 | 4 类 + 注入策略设计合理 |
| 3 | 置信度追踪 | 4/5 | 业界普遍缺失 | 我们有 0.0-1.0，但未用于前端 |
| 4 | 语义检索 | 2/5 | Mem0: ANN 向量搜索 | fastembed 可选依赖，默认不启用 |
| 5 | 图谱关系 | 1/5 | Mem0ᵍ/FluxMem: 异构图 | 完全没有 |
| 6 | 持久化存储 | 2/5 | Mem0: SQLite/PG/Redis | 纯 `.md` 文件，无 SQL 查询能力 |
| 7 | 前端展示 | 2/5 | 各有 Web UI | 有 Memory tab 但数据不全 |
| 8 | 会话记忆 | 4/5 | Letta: self-editing blocks | 10 节中文模板 + 增量提取 |
| 9 | 跨会话合并 | 3/5 | FluxMem: PEMS 演化 | Triple gate 有但粗糙 |
| 10 | 遗忘机制 | 3/5 | Mem0: 时间+访问衰减 | TTL + 置信度衰减，无访问衰减 |
| 11 | 注入策略 | 4/5 | 各有不同 | 三阶段设计合理（always/precision/index） |
| 12 | 真相保存 | 3/5 | 业界普遍缺失 | 原始 `.md` 文件本身是真相 |

**总分：32/60** — 核心架构设计合理，但存储层、图谱、前端展示是半成品。

---

## 逐项分析

### 1. 存储后端 — 2/5 ⚠️ 半成品

**现状**：纯文件系统 `.md` + YAML frontmatter。`MetadataCache` 是内存索引。没有 SQL 查询能力。

**行业做法**：
- Mem0：三重存储（Vector + Graph + KV）。SQLite/PostgreSQL 作为元数据层
- Letta：文件系统 + SQLite 混合
- Zep：PostgreSQL + 时间知识图谱

**问题**：
- 无法按 `confidence > 0.8 AND type = "project"` 等条件 SQL 查询
- 前端展示需要全量加载再内存过滤
- API 列表端点每个 item 都调 `read_memory()` 读文件——O(n) I/O

**改进方案**：

在 `SqliteStorageBackend` 中已有 `session_stats` 等表。新增 `memory_store` 表：

```sql
CREATE TABLE IF NOT EXISTS memory_entries (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    content TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'project',
    status TEXT NOT NULL DEFAULT 'active',
    scope TEXT NOT NULL DEFAULT 'project',
    confidence REAL NOT NULL DEFAULT 0.7,
    ttl_seconds INTEGER,
    expires_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT,
    symbol_name TEXT,
    task_value TEXT,
    content_hash TEXT,
    FOREIGN KEY (memory_name) REFERENCES memory_entries(name)
);

CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(type);
CREATE INDEX IF NOT EXISTS idx_memory_confidence ON memory_entries(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_entries(scope);
```

**代码位置**：
- `app/storage/sqlite.py`：`_init_stats_tables()` 旁加 `_init_memory_tables()`
- `server/services/agent_service.py`：初始化时同步文件→DB

**同步策略**：
- 首次启动：扫描文件目录 → 写入 DB
- 运行时：MemoryStore write/delete 钩子同时写 DB
- 前端查询：走 DB（SQL 过滤），不回退到文件

---

### 2. 语义检索 — 2/5 ⚠️ 半成品

**现状**：`ExternalMemoryStore` 存在但只在 `ProactiveRetriever` 中可选使用。fastembed 未安装时完全静默降级，无日志提示。

**行业做法**：Mem0 强制向量化每一步写入，LLM 提取→分类→存储三步。

**改进方向**：

```python
# memory/external_store.py 中确保 embedding 索引是必选而非可选
# 当前代码：
try:
    from fastembed import TextEmbedding
except ImportError:
    logger.info("fastembed not installed — semantic search disabled")
```

改为：
```python
try:
    from fastembed import TextEmbedding
except ImportError:
    logger.warning("fastembed not installed. Run: pip install fastembed")
    # 或者自动安装
```

**关键代码**：
- `memory/external_store.py:36-65` — embedding 模型加载
- `memory/store.py:220-250` — `write_memory()` 应调用 `indexer.add_memory()`
- `memory/indexer.py` — 需要确保 `add_memory()` 不是空操作

---

### 3. 图谱关系 — 1/5 ❌ 完全缺失

**现状**：完全没有实体关系模型。Anchor 只能绑定文件路径，不能表达"用户 A 偏好 B 因为 C"这样的三元组。

**行业做法**：
- Mem0ᵍ：提取实体→关系→图存储（Neo4j），支持多跳推理
- FluxMem：三层异构图（语义+情节+技能）
- SAGE：自演化图记忆，Reader-Writer 双组件

**改进方向（远期）**：

1. 实体提取：在 `memory/extractor.py` 中增加 LLM 提取三元组
2. 图存储：使用 SQLite 的递归 CTE 模拟简单图查询，或集成 Neo4j Lite
3. 关系查询：支持"找出所有与 `src/main.py` 相关的 feedback"

```sql
-- 简单图存储（SQLite）
CREATE TABLE IF NOT EXISTS memory_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    relation TEXT NOT NULL,   -- "depends_on", "contradicts", "supports", "references"
    weight REAL DEFAULT 1.0,
    FOREIGN KEY (source_name) REFERENCES memory_entries(name),
    FOREIGN KEY (target_name) REFERENCES memory_entries(name)
);
```

---

### 4. 真相保存 — 3/5 ⚠️ 意外优势

**现状**：文件系统存储 `.md` 文件本身就是原始真相。与 Mem0 等丢弃原始消息的做法不同，我们的原始数据始终可回溯。

**但**：
- API 层没有暴露"原始消息"视图
- 前端看不到记忆的来源（哪个 session、哪次对话产生的）
- 没有审计日志

**改进**：

在 `MemoryMetadata` 中增加 `source` 字段：
```python
@dataclass
class MemoryMetadata:
    source: str = ""          # "web_api" | "llm_extraction" | "consolidation" | "cli"
    source_session_id: str = ""  # 来自哪个 session
    original_message_preview: str = ""  # 截断的原文前 200 字符
```

---

### 5. 前端展示 — 2/5 ⚠️ 半成品

**现状**：`MemoryView.tsx` 存在但：
- 列表从 API 返回的数据缺少 `layer`、`preview` 等字段（前端类型定义里有但后端返回没有）
- 没有详情弹窗展示完整 Markdown 内容
- 没有新建/编辑/删除的 UI（只有后端 API）
- 统计信息（by_type、by_scope）在前端算的，不是后端直接返回

**改进方向**：

后端 `GET /api/memory` 增加 `_expand` 参数：
```
GET /api/memory?_expand=true&type=project&confidence_gt=0.7
```

返回结构：
```json
{
  "items": [...],
  "overview": {
    "total": 12,
    "by_type": {"user": 2, "feedback": 3, "project": 5, "reference": 2},
    "by_status": {"active": 10, "deprecated": 2}
  },
  "expiring_soon": 1
}
```

---

### 6. 会话记忆 — 4/5 ✅ 相对完善

**现状**：`SessionMemoryTracker` 有完整的 10 节中文模板、增量提取（10K token 触发）、后台 LLM 子 agent。

**差距**：
- 提取的内容从未通过 WS 推送给前端（用户看不到"agent 正在记录"）
- 没有跨 session 的会话记忆检索 API

---

### 7. 跨会话合并 — 3/5 ⚠️ 粗糙

**现状**：Triple gate（24h + 5 sessions + 锁）存在，但：
- `DreamAgent` 限制过多（5 turns），实际合并质量难保证
- 没有合并后的 diff 展示（合并了什么？改了哪些记忆？）
- 没有手动触发合并的 API

**改进**：
- 增加 `POST /api/memory/consolidate` 端点
- 合并结果写入 `consolidation_log` 表
- WS 推送合并进度事件

---

### 8. 遗忘机制 — 3/5 ⚠️ 不完整

**现状**：
- TTL 过期（`evict_expired_by_ttl`）✅
- 置信度衰减（文件哈希不匹配减半）✅
- 用户显式废弃（`deprecate_memory`）✅
- 但：**没有基于访问频率的衰减**

**行业做法**：Mem0 使用倒数衰减速算法：`score = 1 / (1 + days_since_last_access)`。

**改进**：

在 `session_stats` 表的每日 rollup 中增加访问计数，定期衰减置信度：
```sql
-- 每月一次：低访问 + 低置信度的记忆自动降级
UPDATE memory_entries
SET confidence = confidence * 0.9
WHERE access_count < 3 AND updated_at < datetime('now', '-90 days');
```

---

## 改进优先级

| 优先级 | 改进项 | 影响 | 工作量 |
|--------|--------|------|--------|
| **P0** | DB 化：新增 `memory_entries` 表 + 同步 | 前端查询性能、SQL 过滤 | 中（2 天） |
| **P0** | API 增强：增加 `_expand`、`overview` | 前端数据完整 | 小（1 天） |
| **P1** | 语义搜索默认启用（fastembed 强制） | 检索质量 | 小（半天） |
| **P1** | 记忆来源追踪（`source_session_id`） | 可追溯性 | 小 |
| **P2** | 前端 CRUD UI（新建/编辑/删除记忆） | 用户体验 | 中 |
| **P2** | 访问频率衰减 + 自动降级 | 记忆质量 | 小 |
| **P3** | 图谱关系（`memory_relations` 表 + LLM 提取） | 高级推理 | 大 |
| **P3** | 合并 API + 合并日志 | 可观测性 | 中 |

---

## DB 化详细规划（P0）

### 当前文件系统流程

```
MemoryStore.write_memory()
  → build_frontmatter() → atomic_write_text() → .md 文件
  → MetadataCache.upsert() → 内存索引
  → (可选) ExternalMemoryStore.add() → SQLite 向量
```

### 需要的 DB 流程

```
MemoryStore.write_memory()
  → .md 文件（保留原始真相）
  → MetadataCache.upsert()（保留内存索引）
  → SqliteStorageBackend.upsert_memory() → memory_entries 表
  → (可选) ExternalMemoryStore.add() → 向量
```

### 改动的文件

| 文件 | 改动 |
|------|------|
| `app/storage/sqlite.py` | 新增 `_init_memory_tables()` + `upsert_memory()` / `query_memories()` / `delete_memory_row()` 方法 |
| `app/storage/protocol.py` | 新增 `query_memories()`、`get_memory_overview()` protocol 方法 |
| `server/routers/memory.py` | 列表端点改用 `query_memories()` 返回增强数据 + `overview` |
| `server/services/agent_service.py` | 初始化时同步文件→DB |
| `server/services/stats_service.py` | 可选：增加记忆统计 |

### 同步逻辑

```python
def sync_memory_files_to_db(self) -> None:
    """启动时：扫描目录，补全新记忆到 DB"""
    from memory.store import MemoryStore
    store = MemoryStore(repo_path=self.repo_path)
    summaries = store.list_memories()
    for s in summaries:
        mem = store.read_memory(s.name)
        if mem:
            self._storage.upsert_memory(
                name=mem.name,
                description=mem.description,
                content=mem.content,
                type=mem.metadata.type,
                status=mem.metadata.status,
                confidence=mem.metadata.confidence,
            )
```

---

## 结论

我们的系统核心设计（4 类型 + 置信度 + 注入策略 + 会话记忆）**比 Mem0 更合理**——Mem0 没有置信度、没有类型区分、丢弃原始消息。但在**存储层、图谱、前端、语义搜索**上是半成品。

**最优先**：把文件系统记忆接入 SQLite，这样前端可以高效查询和展示。DB 表设计已在上方给出，可以直接实现在 `SqliteStorageBackend` 中。
