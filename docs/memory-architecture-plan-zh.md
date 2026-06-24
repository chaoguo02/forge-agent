# 记忆系统架构方案

## 1. 架构原则

### 1.1 两层物理架构

```
┌──────────────────────────────────────────────────────────────┐
│  短期记忆（会话级）                                              │
│  ConversationHistory + Compaction + TokenBudget                │
│  ─────────────────────────────────────                        │
│  当前任务的完整对话上下文。滑动窗口管理，超出窗口的由 compaction   │
│  压缩为摘要。任务结束时清除。不依赖 SQLite、向量库或索引。         │
├──────────────────────────────────────────────────────────────┤
│  长期记忆（持久化，跨会话）                                      │
│  MemoryStore（文件） + ExternalMemoryStore（SQLite + fastembed）│
│  ─────────────────────────────────────                        │
│  三种记忆类型（同一套存储，不同检索策略）：                         │
│                                                                │
│  EPISODIC（情景）│ SEMANTIC（语义） │ PROCEDURAL（程序）          │
│  发生了什么       │ 什么是真的        │ 怎么做                    │
│  时间检索         │ 语义检索          │ 场景精确匹配              │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 "工作记忆"到底是什么

在 LLM agent 中，"工作记忆"（Working Memory）**不是一个独立的记忆模块**。
它就是在推理时刻模型能看到的全部消息数组：

```
[system prompt]        ← 永久规则
[long-term context]    ← 任务开始时注入一次
[conversation history] ← 短期记忆（由 compaction 管理）
[task anchor]          ← 每步注入：当前在做什么？
```

每步注入的 `task anchor + mode + policy` 属于 **prompt engineering**，
不属于记忆子系统。它的作用是：当 compaction 把原始任务消息从 history 中裁剪掉后，
确保模型仍然知道当前任务是什么。

### 1.3 三种记忆类型的理论依据

episodic / semantic / procedural 的三分法，有坚实的学术基础：

| 来源 | 贡献 |
|---|---|
| Tulving (1972) | 人类认知中情景-语义记忆的原始区分 |
| Anderson ACT-R | 数学激活/衰减模型：A_i = B_i + Σ(W_j·S_ji) |
| CoALA (arXiv:2309.02427, 2023) | 将 Tulving 模型正式映射到 LLM agent |
| "Memory in the Age of AI Agents"（2025 年，47 位作者，含 Google DeepMind、Stanford、Yale） | 该领域的权威综述，以 factual/experiential/working 为功能类别 |
| LangMem SDK (2025) | 直接实现：EpisodicMemory、SemanticMemory、ProceduralMemory |
| MongoDB Agent Memory Guide (2025) | 业界参考：episodic、semantic、procedural、associative |

需要强调的是：这不是三个独立的存储后端，而是**同一套持久化层上的三种检索策略**，
区别在于触发方式和检索方法。

---

## 2. 三种记忆类型的详细定义

### 2.1 情景记忆（Episodic）

**认知定义**（Tulving）：带有时间戳的亲身经历。"什么时间、什么场景、发生了什么。"

**在编码 agent 中**：
- 特定工具调用、其输出结果及上下文记录
- 例："`pytest test_plan_mode.py::test_edit_scope_blocks_other_file_reads`
  于 2025-06-23 在第 306 行因 AssertionError 失败"
- 例："读取了 `agent/core.py` 第 1140-1230 行，确认 `_run_planning_phase`
  将 `policy` 传递给了 `_run_execution_phase`"

**存储**：MemoryStore 中的完整内容（含时间戳、文件锚点、工具上下文）+
ExternalMemoryStore 中的向量嵌入。

**检索**：以文件/符号锚点 + 时间远近为主，语义相似度为辅。遵循 ACT-R 激活衰减：
访问越频繁的情景记忆，衰减越慢。

**生命周期**：
- 形成：任务完成时从 EventLog 自动提取（阶段 2）
- 巩固：相似情景合并为语义知识（阶段 3）
- 衰减：艾宾浩斯曲线：R(t) = e^(-t/S)，S 取决于重要性
- 过期：超过 N 天未被访问的情景记忆被清理（阶段 5）

### 2.2 语义记忆（Semantic）

**认知定义**（Tulving）：去除了上下文的常识和概念。"什么是普遍为真的，
与何时学到无关。"

**在编码 agent 中**：
- 项目知识：文件职责、模块关系、配置值
- 例："`agent/core.py` 包含 `ReActAgent`（主循环）和
  `PlanExecuteAgent`（规划-执行编排器）"
- 例："项目使用 `config/default.yaml`，通过
  `config/schema.py::load_config()` 加载"

**存储**：紧凑的事实陈述，含实体链接（文件路径、符号名）。
向量嵌入用于语义搜索。不依赖时间戳。

**检索**：以语义搜索（余弦相似度）为主，叠加关键词增强。
在任务开始时作为长期记忆上下文注入。

**生命周期**：
- 形成：从 EventLog 和用户交互中自动提取。也从情景记忆中巩固而来（阶段 3）
- 更新：出现矛盾证据时，更新而非复制
- 衰减：比情景记忆更慢。访问频率可阻止衰减
- 过期：仅在明确矛盾或关联文件被删除时

### 2.3 程序记忆（Procedural）

**认知定义**（Tulving 扩展，Anderson ACT-R）：技能、惯例和行为模式。
"如何做事情。"

**在编码 agent 中**：
- 从用户纠正中提取的精确行为规则
- 例："处理 YAML 配置文件时，应使用 `yaml.safe_load()` 而非正则解析"
- 例："修改 `agent/core.py` 中 FINISH 路径时，必须同步更新
  `CompletionValidator.validate()`"
- 例："修改 `agent/policy.py` 前，先读 `agent/policy_registry.py` ——
  两者紧密耦合"

**存储**：规则文本 + 强制文件/符号锚点。高重要性标记。
不主动过期，除非显式失效。

**检索**：**不使用语义搜索**。锚点精确匹配 + 任务类型激活。
当 agent 读取 `agent/core.py` 时，所有锚定到该文件的程序记忆自动注入。

**生命周期**：
- 形成：从用户纠正和重复模式中提取（阶段 2）
- 验证：锚定文件改动时，规则标记为待验证（阶段 5）
- 过期：仅在用户显式否定或文件验证证明规则不再适用时

---

## 3. 检索策略矩阵

|  | 情景记忆 | 语义记忆 | 程序记忆 |
|---|---|---|---|
| **触发时机** | 访问文件/符号时 | 任务开始时 | 访问文件/符号时 |
| **检索方式** | 锚点匹配 + 时间排序 | 语义搜索（余弦） | 锚点精确匹配 |
| **注入位置** | 可选（相关时每步注入） | 任务开始时（长期上下文） | 锚点命中时每步注入 |
| **数量限制** | 时间最近的前 3 条 | 相似度最高的前 5 条 | 所有匹配（预计很少） |
| **降级策略** | 无锚点时用语义搜索 | 余弦低时用关键词搜索 | 无 |

---

## 4. 分阶段执行计划

### 阶段 1：记忆类型系统 + 文件锚点

**借鉴对象**：LangGraph Store 的 namespace 设计、Letta Memory Blocks 的类型区分

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `memory/models.py` | `MemoryMetadata.type` 从 `user/feedback/project/reference` 改为 `Literal["episodic", "semantic", "procedural"]`。新增 `Memory.anchors: list[Anchor] \| None` |
| `memory/store.py` | `_build_memory_file()` 适配新字段。向后兼容映射：`user→episodic`、`feedback→procedural`、`project→semantic`、`reference→semantic` |
| `memory/context.py` | `_build_filtered_section()` 按类型分组，程序记忆优先展示 |
| `tools/memory_tool.py` | `memory_write` 的 schema 新增 `type` 枚举 + `anchors` 参数 |
| `test_plan_mode.py` | 类型测试、锚点往返测试、向后兼容测试 |

**新增数据结构**：

```python
@dataclass
class Anchor:
    kind: str           # "file" | "symbol" | "task"
    path: str | None    # 文件路径（用于 file/symbol 类型）
    name: str | None    # 符号名（用于 symbol 类型）
    value: str | None   # 任务类型关键词（用于 task 类型）

@dataclass
class MemoryMetadata:
    type: str = "semantic"  # "episodic" | "semantic" | "procedural"
```

**测试用例**：
- `test_memory_types_episodic_semantic_procedural`
- `test_memory_anchors_roundtrip`
- `test_memory_backward_compat_old_types`

**验证命令**：`python -m pytest test_plan_mode.py -k "memory_type or anchor"`

**反思**：锚点是程序记忆检索的关键前提。缺少锚点，程序规则无法被精确触发。
类型枚举将原本模糊的 `user/feedback/project/reference` 替换为有认知科学依据的分类。

---

### 阶段 2：自动提取管线（形成期）

**借鉴对象**：Mem0 的 Extract 阶段、Generative Agents 的 reflection 机制

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `memory/extractor.py`（新增） | `MemoryExtractor.extract(task, log_events) → list[MemoryCandidate]` |
| `agent/core.py` | `_run_body` 的 FINISH 路径：调用 extractor，写入候选记忆 |
| `test_plan_mode.py` | 提取相关测试 |

**提取流程**：

```
EventLog（最后 N 步）
    ↓
构建上下文摘要：
  - 任务描述
  - 使用的工具（仅名称，不含完整输出）
  - 最终总结
    ↓
LLM 调用（temperature=0，结构化 JSON 输出）：
  [
    {
      "type": "episodic" | "semantic" | "procedural",
      "content": "...",
      "description": "...",
      "anchors": [...],
      "confidence": "high" | "medium" | "low"
    }
  ]
    ↓
过滤：丢弃 confidence="low"
    ↓
逐条调用 MemoryStore.consolidate()（阶段 3）
```

**LLM prompt 设计**（关键）：
- 情景记忆："具体发生了什么工具交互？聚焦于结果。"
- 语义记忆："关于这个项目，确认了什么普遍事实？"
- 程序记忆："应用了什么规则或约束？遵循了什么模式？"
- 不要："总结这段对话。"—— 这会产生无用的文本。

**触发时机**：
- SUCCESS：总是提取
- GAVE_UP：不提取
- FAILED / MAX_STEPS：不提取
- 提取失败（LLM 出错）：记录 warning，不阻塞任务完成

**测试用例**：
- `test_extractor_extracts_episodic_from_success`
- `test_extractor_extracts_procedural_from_correction`
- `test_extractor_no_extraction_on_gave_up`
- `test_extractor_no_block_on_llm_failure`

**验证命令**：`python -m pytest test_plan_mode.py -k "extractor"`

**反思**：提取 prompt 是单一最重要的设计决策 ——
它决定了记忆是有用信息还是噪音。开始时应采用保守的 prompt（更少、更高质量的记忆），
后续迭代优化。

---

### 阶段 3：记忆合并去重（巩固期）

**借鉴对象**：Mem0 的 ADD/UPDATE/MERGE/NOOP 管线、LangGraph Store 的 key 幂等写入

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `memory/store.py` | `consolidate(candidate) → str`（返回动作：ADD/UPDATE/MERGE/NOOP） |
| `memory/extractor.py` | 写入时用 `consolidate()` 替代 `write_memory()` |
| `test_plan_mode.py` | 合并测试 |

**合并管线**：

```
MemoryCandidate
    ↓
ExternalMemoryStore.search(query=candidate.content, top_k=3)
    ↓
    ├─ 最高余弦 < 0.5   → ADD（不存在相似记忆）
    ├─ 0.5 ≤ 最高 < 0.85 → LLM 判断：ADD | UPDATE | MERGE | NOOP
    └─ 最高 ≥ 0.85       → MERGE（高度相似，合并内容）
```

**LLM 判断的 prompt**（用于 0.5-0.85 灰色区间）：

```
已有记忆（id=X）："{content}"
新的候选项："{content}"

请决定：
- ADD：全新信息
- UPDATE：同一主题，新信息取代旧信息
- MERGE：互补信息，合并两者
- NOOP：已被充分覆盖
```

**测试用例**：
- `test_consolidate_add_new` → ADD
- `test_consolidate_update_changed` → UPDATE
- `test_consolidate_merge_complementary` → MERGE
- `test_consolidate_noop_identical` → NOOP

**验证命令**：`python -m pytest test_plan_mode.py -k "consolidate"`

**反思**：阈值（0.5、0.85）参考了 Mem0 的公开值，但需针对我们的 embedding 模型
（`BAAI/bge-small-zh-v1.5`）调优。持续监控误合并率并调整。

---

### 阶段 4：差异化检索

**借鉴对象**：LangGraph Store 的语义搜索、Letta Block 的直接注入、ACT-R 的传播激活

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `memory/context.py` | 重写 `build_memory_section()`，实现按类型区分的检索 |
| `memory/context.py` | 新增 `_build_procedural_section(current_file_paths)` |
| `agent/core.py` | 每步跟踪 `_accessed_files: set[str]`，用于触发程序记忆 |
| `test_plan_mode.py` | 检索策略测试 |

**按类型的检索方式**：

```
任务开始时（一次）：
  semantic:  ExternalMemoryStore.search(query=task_description, top_k=5)
  episodic:  ExternalMemoryStore.search(query=task_description, top_k=3,
              filter=type="episodic", sort=recency)
  → 注入到长期上下文消息中

每一步（当文件锚点命中时）：
  procedural: MemoryStore.list(type="procedural", anchor_path in current_files)
  → 注入到任务锚点消息中
```

**程序记忆的触发机制**：

```python
# 在 _run_body 中，工具执行之后：
if tool_name in ("file_read", "file_view"):
    self._accessed_files.add(normalize_repo_path(path, repo_path))

# 在 _build_task_anchor() 中：
procedural = self._build_procedural_section(self._accessed_files)
```

**测试用例**：
- `test_procedural_triggered_when_file_read`
- `test_procedural_not_triggered_for_unrelated_file`
- `test_semantic_injected_at_task_start`
- `test_episodic_injected_at_task_start`

**验证命令**：`python -m pytest test_plan_mode.py -k "procedural_trigger or semantic_inject or episodic_inject"`

**反思**：文件访问跟踪器（`_accessed_files`）必须与 `normalize_repo_path` 保持一致的路径归一化。
这是连接 agent 运行时行为和记忆检索之间的桥梁。

---

### 阶段 5：记忆验证与过期

**借鉴对象**：ACT-R 的激活衰减、艾宾浩斯遗忘曲线、Letta 的基于文件的记忆验证

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `memory/models.py` | `Memory` 新增 `validated_at`、`stale`、`access_count` 字段 |
| `memory/store.py` | `mark_stale_for_file(path)` — 标记锚定到该路径的记忆为 stale |
| `memory/store.py` | `prune_expired()` — 清理超过 N 天未访问的情景记忆 |
| `agent/core.py` | 在 `file_write`/`file_edit` 之后调用 `mark_stale_for_file` |
| `test_plan_mode.py` | 失效和过期测试 |

**失效流程**：

```
file_write("agent/core.py")
    ↓
MemoryStore.mark_stale_for_file("agent/core.py")
    ↓
所有 anchor.path="agent/core.py" 的记忆 → stale=True
    ↓
下次 agent 读取 agent/core.py 时：
  程序记忆区附带提示："⚠ 此规则可能已过时，请验证。"
    ↓
agent 可以确认或更新规则
    ↓
重置 stale=False，validated_at=now
```

**过期机制**（艾宾浩斯曲线）：

```
情景记忆留存率：R(t) = e^(-t / S)
  S = base_S × importance_factor
  base_S = 30 天
  importance_factor = 0.5（低）| 1.0（普通）| 2.0（高）
  → 低重要性：约 15 天后留存率降至 50%
  → 普通：约 30 天后留存率降至 50%
  → 高：约 60 天后留存率降至 50%
```

当 R(t) < 0.1 时，该记忆可被清理。

**测试用例**：
- `test_file_memory_stale_on_file_write`
- `test_procedural_no_stale_on_file_read`
- `test_episodic_decay_prunes_old_memories`

**验证命令**：`python -m pytest test_plan_mode.py -k "stale or decay or prune"`

**反思**：失效检测本质上是启发式的——文件改动可能影响规则，也可能不影响。
`stale` 标记是信号而非保证。Agent 应将 stale 规则视为"核实后再用"，而非"立即丢弃"。

---

### 阶段 6：集成与清理

**涉及文件**：

| 文件 | 改动内容 |
|---|---|
| `agent/core.py` | 删除 `_build_working_context` 命名，重命名为 `_build_task_anchor`。注释修正：删除 "Layer 3" 表述 |
| `memory/context.py` | MemoryContext 与新类型系统集成 |
| `memory/store.py` | 清理已废弃的旧代码分支（已在 P0 中完成） |

**手动 CLI 回归**：

1. **纠正被记住**：
```powershell
python -m entry.cli run --repo . --mode plan --auto-approve \
  --task "请在处理 YAML 时使用 yaml.safe_load 而不是正则"
```
→ 验证：创建了一条带文件锚点的程序记忆

2. **重复纠正不产生重复记忆**：
同一任务执行两次 → consolidate 识别为 NOOP，不产生重复

3. **下次任务程序记忆自动激活**：
```powershell
python -m entry.cli run --repo . --mode plan --auto-approve \
  --read "config/default.yaml" \
  --task "读取配置"
```
→ 验证：程序规则出现在任务锚点消息中

**最终验证**：
```powershell
python -m pytest test_plan_mode.py
python -m compileall agent entry tools llm context memory
git diff --check
```

**反思**：这是端到端的验证门。如果某个阶段的阈值不够好（记忆太多、触发太少、
噪声大），在这里集中调优。

---

## 5. 我们明确不做的事

| 特性 | 原因 |
|---|---|
| 后台 sleep-time agent | 编码 agent 不是长期运行的服务 |
| 知识图谱（Neo4j/Neptune） | 文件→符号映射已有 `repo_map` |
| 多模态记忆（图片/音频） | 纯代码和文本场景 |
| RL 训练的记忆策略 | 单人使用场景，无训练数据管线 |
| 分布式存储（PostgreSQL/Redis/MongoDB） | 单人使用，SQLite + 文件已足够 |
| "工作记忆"作为独立模块 | 上下文窗口本身就是工作记忆 |

---

## 6. 阶段间依赖关系

```
阶段 1（类型 + 锚点）──▶ 阶段 2（提取）──▶ 阶段 3（合并去重）
                                                 │
阶段 4（检索）◀── 阶段 1（程序记忆触发需要锚点）
阶段 4（检索）◀── 阶段 3（需要去重后的记忆）
阶段 5（验证）◀── 阶段 1（文件失效需要锚点）
阶段 5（验证）◀── 阶段 2（需要验证的是自动创建的记忆）
阶段 6（集成）◀── 所有前置阶段

推荐执行顺序：1 → 2 → 3 → 4 → 5 → 6
阶段 4 和 5 理论上可在阶段 3 之后并行开发。
```

---

## 7. 成功指标

| 指标 | 目标 | 衡量方式 |
|---|---|---|
| 类型准确性 | 程序记忆始终带有锚点 | `consolidate()` 中的断言检查 |
| 去重率 | >90% 的重复事实被识别 | 阶段 3 测试中记录 ADD/NOOP 比例 |
| 程序记忆触发精度 | >80% 的触发规则是相关的 | 阶段 6 手动 CLI 审查 |
| 提取噪音 | <30% 的自动提取记忆后续被清理 | 跟踪提取数量与后续清理数量的比值 |
| 记忆占用的 token 预算 | 长期上下文 < history 预算的 15% | `_build_messages` 中估算 |
| 失效捕获率 | >50% 文件修改后的程序规则被标记 stale | 手动 CLI 审查 |
