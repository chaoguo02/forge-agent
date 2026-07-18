# Phase 2: Recovery Paths — CC-aligned 实现计划

> 依据: CC queryLoop 7 continue sites + prompt-too-long 三阶恢复瀑布

---

## CC 对照

CC 的 `while(true)` 循环有 7 个 continue site + 11 个 terminal 条件。
每次 continue 创建新 `State` 对象，`transition.reason` 记录为什么继续。

forge-agent 当前只有 2 个 continue（stop_hook_block + completion_block），其余直接 fail。

| Continue Site | CC 实现 | forge-agent | Phase 2 |
|---------------|---------|-------------|---------|
| next_turn | 正常工具执行后循环 | ✅ for step loop | - |
| max_output_tokens_escalate | 首次 8k 截断 → 静默升至 64k | ❌ 直接 fail | ✅ P0 |
| max_output_tokens_recovery | 截断后注入 "Resume directly"，最多 3 次 | ❌ | ✅ P0 |
| reactive_compact_retry | 413 → 微型压缩 → 全量压缩 → fail | ❌ | ✅ P1 |
| collapse_drain_retry | 413 → 提交已暂存的折叠 | ❌ 暂无折叠 | P3 |
| stop_hook_blocking | Hook 返回 block → 注入错误 → continue | ✅ | - |
| token_budget_continuation | 预算未用尽 → nudge + diminishing returns | ❌ | ✅ P1 |

---

## 实现方案

### A) max_output_tokens_escalate + recovery (P0)

**触发**: LLM 响应被截断（finish_reason="length" 或 output_tokens ≥ max_tokens）

**两阶段恢复**:

```
第 1 次截断
  → transition = 'max_output_tokens_escalate'
  → 静默提升 max_tokens 8k→64k（不注入用户消息）
  → 用相同输入重试

第 2+ 次截断（提升后仍截断）
  → transition = 'max_output_tokens_recovery'
  → 注入 meta 消息: "[SYSTEM] Output truncated. Resume directly — no apology, no recap."
  → recovery_count += 1，最多 MAX_RECOVERY=3
  → 超过 3 次 → 释放 withheld error → fail
```

**关键设计**（CC 的 "withholding" 模式）:
- 首次 escalation 对用户透明（用户不知道发生了截断恢复）
- 恢复消息标记 `isMeta=true`，不在 REPL 中显示
- 只在所有恢复失败后才向用户报告错误

**改动**:
- `llm/invoker.py`: `InvokeResult` 加 `truncated: bool` + `finish_reason: str`
- `agent/core.py`: 新增 `_check_output_truncation()` → continue 或 fail
- 不需要新文件，改动集中在 agent 循环中

### B) token_budget_continuation (P1)

**触发**: 模型调 FINISH 但 token budget 剩余 > 10%

**CC 的两阶段检测**:
```
1. 预算检查: used_tokens < budget * 0.9 → 没完成，继续
2. Diminishing returns: 
   - continuation_count >= 3 
   - AND 本轮新增 < 500 tokens
   - AND 上轮新增 < 500 tokens
   → 停止（模型在空转）
```

**注入的 nudge 消息**:
```
[SYSTEM] Token budget remaining: {remaining}. 
Continue working on the task if there are remaining items.
If you believe the task is complete, call finish.
```

**改动**:
- `agent/core.py`: 在 FINISH 检测后（completion guard 之前）加 budget check
- 用 AgentConfig 中的 `budget_tokens` 作为参考
- `_nudge_count` 和 `_last_nudge_tokens` 追踪 diminishing returns

### C) reactive_compact_retry (P1)

**触发**: API 返回 "prompt too long" (413 / context length exceeded)

**三阶恢复瀑布**（CC 模式）:
```
API 返回 prompt-too-long
  │
  ├─ Tier 1: Microcompact
  │     调用 compactor.micro_compact()（零 API 调用）
  │     清除旧 tool_result 内容
  │     如果释放了 token → retry
  │
  ├─ Tier 2: Reactive Compact
  │     调用 compactor.compact()（一次 LLM 调用）
  │     全量摘要旧消息
  │     hasAttemptedReactiveCompact=true（熔断器）
  │     如果成功 → retry
  │
  └─ Tier 3: 释放 withheld error → fail
```

**改动**:
- `agent/core.py`: 在 LLM 调用异常处理中加入 prompt-too-long 检测
- `context/compaction.py`: micro_compact() 方法已存在（MicroCompactor）
- 新增 `has_attempted_reactive_compact` 熔断器

---

## 文件改动计划

| 文件 | 改动 | ~行数 |
|------|------|-------|
| `llm/invoker.py` | InvokeResult 加 truncated + finish_reason | +5 |
| `agent/core.py` | 三个恢复路径 + RecoveryState 追踪 | +80 |
| `context/compaction.py` | SnipCompact（零成本空结果过滤） | +40 |

共计 ~125 行，不超过 3 个文件。

---

## 不做（Phase 2 范围外）

- ❌ Context Collapse（需要 collapse store + projectView，独立大 feature）
- ❌ Session Memory Compact（需要 tengu_session_memory 后台提取）
- ❌ collapse_drain_retry（依赖 Context Collapse，P3）
- ❌ Media size stripping（无图像输入场景）

---

## 验证

```bash
# 回归测试
pytest tests/test_plan_approval.py tests/test_plan_prompt_contract.py \
       tests/test_cc_alignment_features.py tests/test_cli_v2_orchestration.py \
       tests/test_agent_v2_mcp_integration.py tests/test_chat.py -q

# 新增: 恢复路径测试
pytest tests/test_cc_alignment_features.py -k "recovery or nudge or compact"
```
