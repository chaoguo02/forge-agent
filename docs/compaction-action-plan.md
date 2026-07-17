# 上下文压缩 — 完整执行计划

> 每个改动都有 CC 源码依据, 定位到具体文件和行号

---

## 批次一览

| 批次 | 内容 | 优先级 | 文件数 |
|------|------|--------|--------|
| Z-1 | request_budget_tokens + history_max_messages 修正 | P0 | 2 |
| Z-2 | 压缩后恢复: 文件 + Skill + CLAUDE.md 重新注入 | P1 | 3 |
| Z-3 | 工具调用对完整性保护 | P1 | 1 |
| Z-4 | CompactBoundary 标记完善 | P2 | 1 |
| Z-5 | MicroCompact 层 (轻量无API清理) | P2 | 1 |

---

## Z-1: token 预算修正

### CC 依据

CC 无 `request_budget_tokens` 概念——它直接使用模型上限 (200,000 tokens)。
我们 DeepSeek v4 的上下文是 128K, 当前 `request_budget_tokens=70,000` 仅用 55%。

### 代码位置

`agent/core.py:98` — `request_budget_tokens: int = 70_000`  
`agent/core.py:103` — `history_max_messages: int = 40`  
`config/default.yaml:83` — `request_budget_tokens: 70000`

### 修改

```python
# agent/core.py
request_budget_tokens: int = 110_000   # 从 70K 提升到 110K (85% of 128K)
history_max_messages: int = 200        # 从 40 提升到 200
```

```yaml
# config/default.yaml
request_budget_tokens: 110000
```

---

## Z-2: 压缩后恢复 (Post-Compaction Re-Injection)

### CC 依据

CC 压缩后通过 `POST_COMPACT_TOKEN_BUDGET=50,000` 预算重新注入:
- 最近 5 个文件内容 (每个 ≤5K)
- 激活的 Skill 指令 (总预算 25K)
- CLAUDE.md 内容
- MCP 工具发现结果

### 设计

在 `ConversationCompactor.compact_history()` 返回后, 调用方将恢复消息注入到 history 中。
新增 `CompactionRecovery` 类管理这个过程。

### 代码位置

1. `context/compaction.py` — 新增 `CompactionRecovery` 类
2. `agent/core.py:1527-1555` — `_build_messages` 中在 compaction 后调用 recovery

### 修改

```python
# context/compaction.py — 新增类
class CompactionRecovery:
    def __init__(self, file_read_cache, skill_buffer, project_dir):
        self._file_cache = file_read_cache
        self._skill_buffer = skill_buffer
        self._project_dir = project_dir

    def build_recovery_messages(self, compacted: list[dict]) -> list[dict]:
        """返回应注入的高优先级上下文消息。"""
        msgs = []
        # 1. 恢复最近的 Skill 内容 (快照)
        if self._skill_buffer:
            for name, content in self._skill_buffer.snapshot():
                msgs.append({
                    "role": "user",
                    "kind": "runtime_notice",
                    "content": f"[Post-compaction: skill '{name}']\n{content}",
                })
        # 2. 恢复文件缓存中的最近文件
        if self._file_cache:
            recent = list(self._file_cache.entries.keys())[-5:]
            for path in recent:
                content = self._file_cache.get(path)
                if content:
                    msgs.append({
                        "role": "user",
                        "content": f"[Post-compaction: {path}]\n{content[:5000]}",
                    })
        return msgs
```

---

## Z-3: 工具调用对完整性保护

### CC 依据

`adjustIndexToPreserveAPIInvariants()` — 向后扩展 startIndex, 确保:
1. 每个 tool_result 都有对应的 tool_use (不产生孤儿结果)
2. 同一 message.id 的内容块不分开

### 代码位置

`context/compaction.py` — `ConversationCompactor.compact_history()`

### 修改

在确定 keep/cut 边界后, 检查边界是否切在配对的 `tool_use`/`tool_result` 之间:

```python
def _adjust_index_for_tool_pairs(self, messages, cut_index):
    """向后移动 cut_index, 确保不切开 tool_use/tool_result 配对。"""
    # 收集保留区内的所有 tool_result id
    result_ids = set()
    for i in range(cut_index, len(messages)):
        if messages[i].get("role") == "tool":
            result_ids.add(messages[i].get("tool_call_id"))
    # 在压缩区内查找匹配的 tool_use
    while cut_index > 0:
        msg = messages[cut_index - 1]
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            if tc.get("id") in result_ids:
                cut_index -= 1  # 向后扩展
                break
        else:
            break
    return cut_index
```

---

## Z-4: CompactBoundary 标记完善

### 已有基础

R3 已经加了 `MessageKind.COMPACTION_BOUNDARY` 和 `kind` 字段。

### 缺失

缺少 metadata: compactType, preCompactTokenCount, preservedMessageUuids。

### 代码位置

`context/compaction.py:286-295` — `build_compact_block_for_history()`

### 修改

```python
def build_compact_block_for_history(self, ...):
    return {
        "role": "user",
        "kind": "compaction_boundary",
        "compact_metadata": {
            "type": "api_summary",
            "pre_compact_tokens": pre_tokens,
            "compacted_count": num_summarized,
        },
        "content": f"[Conversation compacted — {num_summarized} messages summarized]\n\n...",
    }
```

---

## Z-5: MicroCompact 层

### CC 依据

`microCompact.ts` — 零 API 调用的单工具输出清理:
- 针对 Read/Bash/Grep/Glob/WebSearch/WebFetch/Edit/Write
- 保留最近 N 个结果
- 旧结果替换为 `[Old tool result content cleared]`

### 代码位置

`context/compaction.py` — 新增 `MicroCompactor` 类

### 修改

```python
COMPACTABLE_TOOLS = frozenset({
    "Read", "Bash", "Grep", "Glob", "WebSearch", "WebFetch", "Edit", "Write",
})

class MicroCompactor:
    def __init__(self, keep_recent: int = 5):
        self._keep_recent = keep_recent

    def compact(self, messages: list[dict]) -> list[dict]:
        """替换旧工具输出为 [Old tool result content cleared]"""
        tool_result_indices = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool" and _extract_tool_name(msg) in COMPACTABLE_TOOLS:
                tool_result_indices.append(i)
        if len(tool_result_indices) <= self._keep_recent:
            return messages
        to_clear = tool_result_indices[:-self._keep_recent]
        for i in to_clear:
            messages[i] = {**messages[i], "content": "[Old tool result content cleared]"}
        return messages
```
