# 上下文压缩接入 — 最终执行计划

> 问题: Z-1~5 的类/方法已定义但未接入真实执行链路
> 原则: 每一个改动都必须有 CC 依据, 定位到具体代码行

---

## 批次Y-1: MicroCompactor 接入 _build_messages 管道

### CC 依据

`microCompact.ts` — 在每次 API 调用前自动运行, 清除旧工具输出。

### 现状

`MicroCompactor` 类已定义在 `context/compaction.py`, 但没有任何代码调用它。

### 接入点

`agent/core.py:1549-1567` — `_build_messages()` 方法, 在 `build_request_messages()` 之前:

```python
# 接入: 在每次构建请求消息前, 先做 MicroCompact
if getattr(self, "_micro_compactor", None) is None:
    from context.compaction import MicroCompactor
    self._micro_compactor = MicroCompactor()
history_dicts = self._micro_compactor.compact(history_dicts)
```

### 涉及文件

`agent/core.py` — `_build_messages()` 方法

---

## 批次Y-2: _adjust_index_for_tool_pairs 接入 compact_history

### CC 依据

`adjustIndexToPreserveAPIInvariants()` — 向后扩展 startIndex, 保证切割后的消息数组对 API 合法。

### 现状

方法已定义但 `compact_history()` 在分割消息时不调用它。

### 接入点

`context/compaction.py:226` — `compact_history()` 中 `compact_targets = rest[:compact_end]` 之后:

```python
# 接入: 调整 compact_end 确保不切开 tool_use/tool_result 配对
adjusted_end = self._adjust_index_for_tool_pairs(rest, compact_end)
compact_targets = rest[:adjusted_end]
```

### 涉及文件

`context/compaction.py` — `compact_history()` 方法

---

## 批次Y-3: CompactionRecovery 引用链路修复

### CC 依据

CC 压缩后通过 `POST_COMPACT_TOKEN_BUDGET=50,000` 重新注入文件/Skill/CLAUDE.md。

### 现状

`CompactionRecovery.__init__` 接受 `file_cache`/`skill_buffer`/`project_dir`, 但调用方 (`_build_recovery_messages`) 传递的值可能为 None。需要确保这些引用在编译时有效。

### 接入点

`agent/core.py:1571-1578` — `_build_recovery_messages()` 方法:

```python
def _build_recovery_messages(self) -> list:
    file_cache = None
    if hasattr(self._full_registry, "_read_cache"):
        file_cache = self._full_registry._read_cache
    skill_buf = None
    # Find skill buffer from SkillTool in registry
    for name, tool in getattr(self._full_registry, "_tools", {}).items():
        if name == "Skill" and hasattr(tool, "_buffer"):
            skill_buf = tool._buffer
            break
    ...
```

### 涉及文件

`agent/core.py` — `_build_recovery_messages()` 方法

---

## 批次Y-4: 短期记忆深度整合

### CC 依据

CC 的自动记忆系统: MEMORY.md 自动写入, CLAUDE.md 静态配置, Auto-memory 跨会话学习。

### 现状

`memory/` 有 18 个文件但整合松散。agent 只在启动时做简单记忆注入。

### 接入点

在 `agent/core.py` 的任务结束时, 自动将关键发现写入 agent memory:

```python
# run() 返回前
if self._memory_context and self._memory_context.enabled:
    self._extract_success_memories(task, log, summary)
```

这个方法已存在但调用范围有限。扩展为: 每次 subagent 完成后也沉淀结构化发现。

### 涉及文件

`agent/core.py` — `_extract_success_memories()` 调用点
