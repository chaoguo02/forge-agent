# Session Compression

## 压缩分层

压缩发生在两个不同层面，不要混淆：

| 层面 | 目的 | 对持久化的影响 |
|------|------|--------------|
| **Context Window** | 压缩 LLM 输入，防止超出 token 限制 | **不修改** SQLite/JSONL |
| **Session Storage** | 归档旧 session，减少磁盘占用 | **修改** 存储层 |

现有代码只实现了 **Context Window 压缩**。Session Storage 压缩尚未实现。

## Context Window 压缩 Pipeline

位置：`agent/context_trimming.py` + `context/manager.py`

执行时机：每次 LLM 调用前

```
                   Budget
                    │
                    ▼
                   Snip
                    │
                    ▼
              MicroCompact
                    │
                    ▼
               Collapse
                    │
                    ▼
             AutoCompact
                    │
                    ▼
              LLM 调用
```

### 1. Budget（token 预算）

```python
# context/token_budget.py
class TokenBudget:
    """控制每次 LLM 调用的最大 token 数。"""
    # request_budget_tokens: 110000 (默认)
    # 超过此值的请求会被截断
```

### 2. Snip（删除旧消息）

```python
# agent/core.py → _snip_history()
# 策略：从最早的消息开始删，直到 token 数低于阈值
# 保留最近的 N 条消息（history_max_messages: 200）
```

### 3. MicroCompact（折叠连续 tool 消息）

```python
# agent/context_trimming.py → _micro_compact()
# 合并连续的 tool result，只保留摘要
# 阈值：tool_result_budget_tokens (默认 4000)
```

### 4. Collapse（语义摘要）

```python
# context/manager.py → CollapseStore
# 用 LLM 生成对话摘要，替换旧上下文
# 触发条件：总 token > collapse_threshold_tokens
# 结果：[summary message] + [最近 N 条完整消息]
```

### 5. AutoCompact（轮次后自动压缩）

```python
# entry/chat.py → _maybe_auto_compact_after_round()
# 每 compact_every_rounds (默认 3) 轮触发一次
# 条件：共享历史 token > session_compact_tokens (默认 30000)
```

## 关键参数（config/default.yaml）

```yaml
context:
  request_budget_tokens: 110000    # 单次请求预算
  history_max_messages: 200        # 保留最大消息数
  tool_result_budget_tokens: 4000  # tool result 压缩预算
  collapse_threshold_tokens: 30000 # 触发 collapse 的阈值
  auto_compact_after_round: true   # 轮次后自动压缩
  compact_every_rounds: 3         # 每 N 轮压缩一次
  session_compact_tokens: 30000   # 触发 session 压缩的阈值
```

## 压缩统计

每次压缩后记录：

```python
@dataclass
class CompressionStats:
    round: int                     # 第几轮
    before_tokens: int             # 压缩前 token
    after_tokens: int              # 压缩后 token
    messages_removed: int          # 删除/折叠的消息数
    method: str                    # "snip" | "microcompact" | "collapse" | "autocompact"
```

## 前端展示

Session 详情中显示：

```
Compression:
  Total rounds:  12
  Last compact:  collapse (30000 → 8500 tokens, -15 messages)
  Avg reduction: 62%
```

## Session Storage 压缩（待实现）

目标：归档完成的 session，释放磁盘空间。

```python
class StorageCompressor(Protocol):
    def archive_session(id: str) -> ArchiveResult: ...
    def restore_session(id: str) -> SessionRecord: ...
    def list_archived() -> list[ArchiveRecord]: ...
    def get_compression_stats() -> CompressionSummary: ...
```

策略：
- 将 `session_messages` 中超过 30 天的消息压缩为摘要
- 原始 EventLog JSONL 可以 gzip 归档
- 归档后的 session 只保留 summary + 关键事件
