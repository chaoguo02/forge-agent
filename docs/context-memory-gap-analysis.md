# Context + Memory 双系统差距分析

> 日期: 2026-07-18（第二版，基于代码审计 + CC DeepWiki + 社区生态调研）
> 范围: forge-agent 代码库实际运行状态 vs Claude Code 已知行为

---

## 执行摘要

**总体评估：forge-agent 在架构上已经对齐了大部分 CC 能力，部分领域甚至超过 CC。**

| 领域 | 对齐度 | 说明 |
|------|--------|------|
| 上下文压缩管道 | **~90%** | 5 层管线已实现并接入，仅剩少量冗余和缺失层 |
| 长期记忆系统 | **~95%** | 几乎所有 CC 能力已覆盖，向量检索/content-hash 等为 forge 原创优势 |
| 会话记忆（Session Notes） | **~60%** | 结构和触发逻辑对齐，但子代理受限严重 |
| 跨会话整合（Dream/Consolidation） | **~70%** | 三重门和锁机制完整，但 dream runner 写权限受限 |

---

## Part 1: Context 压缩管道

### 1.1 CC 参考架构

CC 的 5 层压缩管线（按成本从低到高）：

```
Layer 1: Tool Result Budget  ─ 零成本，超大 tool_output 离线化
Layer 2: SnipCompact         ─ 零成本，删除低价值轮次
Layer 3: MicroCompact        ─ 零成本，旧工具输出内容清空
Layer 4: Context Collapse    ─ 低成本/LLM，read-time projection
Layer 5: AutoCompact         ─ 高成本/LLM，全量摘要
        ↕ 50000 tokens POST_COMPACT recovery
```

### 1.2 forge-agent 实际管道（代码审计确认）

```
Agent Loop (agent/core.py:1317-1349):
  ┌─ Budget (ToolResultBudget._apply)
  ├─ Snip (_snip_history → SnipCompactor)
  ├─ MicroCompact (_micro_compact → MicroCompactor)
  ├─ Collapse (_apply_context_collapse → CollapseStore)
  │
  └→ _build_messages (agent/core.py:2459):
       ├─ CollapseStore.project_view() → projected history
       ├─ ContextManager.build_request_messages():
       │    ├─ SnipCompactor.snip()          ← 重复
       │    ├─ trim_sliding_window()         ← 旧路径
       │    ├─ should_compact + compactor_fn → AutoCompact
       │    └─ TokenBudget.trim_history()
       └─ Post-compaction recovery (files + skills + memory)
```

### 1.3 各层状态

| 层 | CC 成本 | forge-agent 状态 | 问题 |
|---|---------|-----------------|------|
| **1. Tool Result Budget** | 零 | ✅ 实现 | `_ToolResultBudgetState` 跟踪单轮 tool output 预算，超大输出被截断 |
| **2. SnipCompact** | 零 | ⚠️ 有但冗余 | 3 处实现：`SnipCompactor` 类、`_snip_history()`、ContextManager 内调用——后两者都委托给 `SnipCompactor`，但双次执行（agent pre-LLM + ContextManager 内）浪费计算 |
| **3. MicroCompact** | 零 | ✅ 实现 | `MicroCompactor(keep_recent=5)` 在 agent pre-LLM 阶段运行。ContextManager 内不重复 |
| **4. Context Collapse** | 低 | ✅ 实现 | `CollapseStore` + `project_view()` + `ContextCollapser`，read-time projection，不修改原始消息 |
| **5. AutoCompact** | 高 | ✅ 实现 | `ConversationCompactor.compact_history()`，增量压缩，thrashing 保护，工具对完整性保护 |
| **Post-Compact Recovery** | 50K预算 | ✅ 实现 | 恢复文件/Skill/CLAUDE.md + 记忆 section（`_build_recovery_messages`，修复 M2） |

### 1.4 已修复的旧问题

以下问题在 `context-memory-gap-analysis.md` v1（2026-07-17）中标记为未解决，代码审计确认**已修复**：

| 问题 | 状态 | 证据 |
|------|------|------|
| C3: MicroCompact 绑定在 compaction 触发中 | ✅ 已修复 | `agent/core.py:1331` 每步 pre-LLM 运行 |
| C5: Tokens_freed 层间协作 | ✅ 已修复 | `agent/core.py:2809` 传入 `_trim_tokens_freed` |
| C6: CompactionRecovery 恢复记忆 | ✅ 已修复 | `agent/core.py:2524-2529` compaction 后 `_invalidate_ltc()` |
| M1: Long-term context 缓存永不刷新 | ✅ 已修复 | `agent/core.py:1974` memory_write 后调用 `_invalidate_ltc()` |
| M2: 压缩后 memory section 不恢复 | ✅ 已修复 | `agent/core.py:2525-2529` 压缩后重建 LTC |

### 1.5 仍存在的问题

#### 问题 C1: 重复 SnipCompactor 执行（P1）

**现象**：SnipCompactor 在 agent pre-LLM 阶段（`_snip_history`）和 ContextManager 内（`build_request_messages:152`）各跑一次。

**影响**：浪费计算，但功能上无害（Snip 是幂等的）。第二次 snip 再过滤已被第一次 snip 处理过的消息，已无低价值内容可删。

**根因**：ContextManager.build_request_messages 的 SnipCompactor.snip() 调用是历史遗留，在 pre-LLM pipeline 加入后未移除。

**修复方案**：从 ContextManager.build_request_messages 移除 SnipCompactor.snip() 调用，或者在 agent pre-LLM 阶段跳过 Snip 而只用 ContextManager 的。

**文件**：
- `agent/core.py:359` — `_snip_history()`
- `context/manager.py:152` — `SnipCompactor.snip()`

#### 问题 C2: trim_sliding_window 仍在运行（P2）

**现象**：ContextManager 第 154 行仍调用 `trim_sliding_window()`，这是旧版滑动窗口裁剪。

**影响**：`trim_sliding_window` 在 MicroCompact 和 Collapse projection 之后运行，可能会删除或修改已经过廉价压缩处理的消息。但因为这个函数是保守的（保留最近的 N 轮完整），实际影响有限。

**根因**：`trim_sliding_window` 是 ContextManager 原有的历史裁剪逻辑，在加入新的 5 层管线后未被移除。

**修复方案**：评估是否仍需要 `trim_sliding_window`——新的 5 层管线（Budget→Snip→MicroCompact→Collapse→AutoCompact）应在大多场景下覆盖其功能。

**文件**：
- `context/manager.py:154` — `trim_sliding_window()`

#### 问题 C3: ContextManagerConfig 默认值仍偏低（P2）

**现象**：
```python
# context/manager.py:46
request_budget_tokens: int = 70_000    # 应为 110_000
history_max_messages: int = 40          # 应为 200
```

**影响**：当 agent/core.py 不提供自定义配置时，ContextManager 的默认值仍使用旧值（70K/40）。但在实际运行中，`agent/core.py` 通过 `self._cfg.request_budget_tokens` 传递值，不会使用 ContextManager 的默认值。所以这个问题的实际影响**极低**。

**修复方案**：更新默认值以保持一致性。

**文件**：
- `context/manager.py:46-47`

#### 问题 C4: 无 Path-Scoped Rules（P3）

**现象**：CC 支持嵌套 CLAUDE.md（项目级 + 子目录级），forge-agent 只有 `.forge-agent/rules.md`（项目级）。

**影响**：无法为不同子目录设置不同规则。低优先级——当前可以单靠 memory_write 实现类似效果。

**修复方案**：在 `build_injection_context` 中增加子目录 rules 扫描。

#### 问题 C5: 无 Archive 层（P3）

**现象**：CC 有 `archives/` 目录（grep-only deprecated memories，不自动注入），forge-agent 没有。

**影响**：标记为 deprecated 的记忆被静默丢弃，无法通过 grep 恢复。

**修复方案**：新增 `.forge-agent/archive/` 目录，deprecate 时将记忆移入而非删除。

---

## Part 2: 长期记忆系统

### 2.1 CC 参考架构

CC 的 5 层记忆体系（按持久性从低到高）：

```
Layer 1: Conversation      ─ 一步之内（LLM message list）
Layer 2: Session Notes     ─ 一步之间（session_notes.md，tengu 模式）
Layer 3: Auto Memory       ─ 会话之间（~/.claude/projects/<name>/memory/）
Layer 4: CLAUDE.md         ─ 跨项目，用户编写（项目根目录）
Layer 5: Archives          ─ 底层归档（grep-only，不自动注入）
```

### 2.2 forge-agent 实际实现

| CC 层 | forge-agent 实现 | 状态 | 差异 |
|-------|-----------------|------|------|
| 1. Conversation | `ConversationHistory` | ✅ | 与 CC 一致 |
| 2. Session Notes | `SessionMemoryTracker` + `ThreadedSessionMemorySubagent` | ⚠️ | 结构对齐但子代理受限 |
| 3. Auto Memory | `MemoryStore` + `MetadataCache` + `ExternalMemoryStore` + `MemoryContext` | ✅ | **超过 CC**（向量检索、content-hash、双层存储均为 forge 原创） |
| 4. CLAUDE.md | `.forge-agent/rules.md` | ✅ | 功能等价，但缺 path-scoped |
| 5. Archives | ❌ 缺失 | ❌ | 无等价功能 |

### 2.3 forge-agent 原创优势

这些能力 CC 没有，是 forge-agent 的竞争优势：

#### 优势 1: 向量语义检索（ExternalMemoryStore）

`memory/external_store.py` 使用 SQLite + fastembed（BAAI/bge-small-zh-v1.5）实现了完整的向量语义搜索：

```python
# 语义搜索，非关键词匹配
results = store.search("login authentication problem")
# → [{"name": "fix-bug-123", "score": 0.87, "content": "..."}]
```

CC 的 Auto Memory 只做关键词/索引查找，没有语义搜索。

#### 优势 2: Content Hash 新鲜度验证（MemoryContext）

forge-agent 为每个 file anchor 存储文件内容的 SHA256 hash。注入前验证 hash：

```python
# memory/context.py:236-276
# 文件变化 → memory 自动贬值（confidence *= 0.5）
# 文件删除 → memory 自动标记 deprecated
```

CC 没有 hash 验证——memory 只通过 mtime 判断新鲜度，更不可靠。

#### 优势 3: 双层存储（TwoTierMemoryStore）

```python
# memory/store.py:901-1046
# user/feedback → 全局目录（跨项目共享）
# project/reference → 项目目录（项目隔离）
```

CC 只有项目级 memory 目录，没有全局层。

#### 优势 4: MetadataCache（零文件 IO 索引）

`memory/metadata_cache.py` 维护内存中的元数据缓存，`list_memories()` 不读磁盘。

CC 每次读取 MEMORY.md 都是文件 IO。

### 2.4 仍存在的问题

#### 问题 M6: SessionMemory 子代理受限（P2）

**现象**：`ThreadedSessionMemorySubagent` 只拿到一个 context_summary 字符串，只能写 notes 文件。CC 的 sessionMemory 子代理可以调用和主代理相同的工具（读文件、浏览对话）。

**影响**：会话笔记的提取质量受限。当前实现只能依赖 context_summary（来自 agent 的压缩），而不能直接读取对话历史、文件内容来写更准确的笔记。

**根因**：`ThreadedSessionMemorySubagent` 是轻量线程实现，没有完整的 agent runtime。

```python
# memory/session_memory.py:116-147
allowed_tools: tuple[str, ...] = ("file_write",)  # 只有一个工具
```

**修复方向**：将 SessionMemory 子代理切换到完整的 fork 机制（`SessionRuntime.spawn_agent()`），赋予其 Read/Grep 等只读工具权限。

**文件**：
- `memory/session_memory.py:116-171` — `ThreadedSessionMemorySubagent`
- `agent/session/runtime.py` — `spawn_agent()` 用于 fork

#### 问题 M7: DreamAgent 被限制在 memory 目录（P3）

**现象**：`DreamAgent` 只能读 memory 目录内的文件。CC 的 consolidation agent 可以访问整个项目 workspace。

**影响**：DreamAgent 无法通过读代码来判断 memory 是否过时，也无法从项目文件中提取新的 memory。

```python
# memory/consolidation.py:62
# allowed_write_root 限制为 memory_dir
def run(self, *, memory_dir: Path, prompt: str, log_dir: str | None = None) -> bool:
    if memory_dir.resolve() != self.allowed_write_root.resolve():
        raise ValueError(...)
```

CC 的 consolidation agent 有完整 workspace 访问，可以检查 git diff、读代码来验证 memory 的时效性。

**修复方向**：扩展 `DreamAgent` 的 workspace 访问权限，允许读项目目录（写权限仍限制在 memory_dir）。

**文件**：
- `memory/dream_agent.py`
- `memory/consolidation.py:40-167` — `DreamRunner` 和 `RuleDreamRunner`

#### 问题 M8: 无 Rollover 通知（P3）

**现象**：当 MEMORY.md 超过 25KB/200行被截断时，只是静默截断。CC 会记录统计并可能触发 consolidation。

**影响**：用户不知道记忆索引被截断，可能丢失记忆引用。

**修复方向**：在 `_truncate_index` 中增加通知回调，或由 `SessionMemoryTracker` 监控索引大小。

**文件**：
- `memory/store.py:131-172` — `_truncate_index()`

#### 问题 M9: 无 Per-Task Resume（P3）

**现象**：`SessionState.rolling_summary` 只保留最后 5 个 task 摘要，注入为扁平文本。

**影响**：跨 session resume 时无法精确恢复到某个 task 的状态。

**修复方向**：为每个 task 持久化结构化结果（修改的文件、运行的命令、关键决策），支持按 task ID 恢复。

**文件**：
- `context/session.py` — `SessionState`

---

## Part 3: 社区生态差距

CC 生态系统有丰富的第三方 memory 工具，forge-agent 的 MCP 生态尚未建立：

| 工具 | 核心能力 | forge-agent 等价物 |
|------|---------|-------------------|
| MemoryForge | Hook-based compaction survival | ✅ `CompactionRecovery` |
| ClaudeContext | DAG 关联图 + 5 层缓存 | ❌ 无 |
| Recall | 夜间 distil → 人工审核 → skill 升级 | ❌ 无 |
| Lossless-Claude | DAG 摘要 + SQLite 持久化 | ✅ CollapseStore（结构相似） |
| CMV (学术) | 三遍无损裁剪 | ❌ 无 |

---

## Part 4: 修复优先级

### P0（无——所有严重影响已修复）

经过本次审计，**所有 P0 问题已被之前的工作修复**。

### P1

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| C1 | 重复 SnipCompactor 执行 | 轻微浪费 | ~2 行删除 |
| | 更新 config 默认值 (70K→110K, 40→200) | 一致性 | ~2 行修改 |

### P2

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| M6 | SessionMemory 子代理受限 | 笔记质量受限 | 中（改 fork 机制） |
| C2 | trim_sliding_window 清理 | 管道整洁 | ~1 行删除 |
| C3 | ContextManagerConfig 默认值更新 | 一致性 | ~2 行修改 |

### P3

| # | 问题 | 影响 | 工作量 |
|---|------|------|--------|
| C4 | Path-scoped rules | 功能缺失 | 中 |
| C5 | Archive 层 | 功能缺失 | 小 |
| M7 | DreamAgent workspace 访问 | 整合质量 | 中 |
| M8 | Rollover 通知 | 用户体验 | 小 |
| M9 | Per-task resume | 功能缺失 | 大 |

---

## 结论

1. **上下文压缩管线已高度对齐 CC**（~90%）。5 层管线全部实现并接入真实执行链路。重复 Snip 和 trim_sliding_window 遗留是唯一的结构性问题。

2. **长期记忆系统在多个维度超过 CC**（~95%）。forge-agent 有而 CC 没有的原创能力：
   - 向量语义检索（fastembed + SQLite）
   - Content hash 新鲜度验证
   - 双层存储（项目级 + 全局级）
   - MetadataCache（零文件 IO）

3. **真正需要投入的领域**：
   - SessionMemory 子代理改用完整 fork 机制（M6，P2）
   - DreamAgent 扩展 workspace 读权限（M7，P3）
   - 社区生态工具引入（MCP memory servers）

4. **无需重复造轮子的领域**：
   - 不需要外部 memory 增强（forge-agent 已经比 CC 的 auto-memory 更强大）
   - 不需要调整 token 预算（当前 110K/200 设置合理）
