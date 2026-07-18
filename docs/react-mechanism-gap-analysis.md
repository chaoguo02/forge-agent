# ReAct 机制 CC 差距分析

> 调研日期: 2026-07-17
> 最后更新: 2026-07-17 (Phase 1+2 实现完成)
> 依据: CC 源码分析 (DeepWiki/社区拆解) + 官方文档

## 实现进度

| 优先级 | 项目 | 状态 |
|--------|------|------|
| P0 | 流式工具执行 (StreamingToolExecutor + OpenAI stream_iter) | ✅ |
| P0 | Per-call 并发安全 (partition + Bash 命令解析) | ✅ |
| P1 | 恢复路径 (escalate/recovery/compact/nudge) | ✅ |
| P1 | SnipCompact (零成本空结果过滤) | ✅ |
| P1 | Bash 错误级联取消 + 事件驱动 collect | ✅ |
| P1 | 终止条件 (prompt_too_long/hook_stopped/tool_use_stop 等) | ✅ |
| P2 | PostResponse hook + non_blocking_error 分类 | ✅ |
| P2 | Subagent: background default + prompt 瘦身 + nested delegation | ✅ |
| P2 | Subagent: child notification runtime-ify + live steering | ✅ |
| P3 | Immutable TurnState | ⬜ RecoveryState 已覆盖核心模式 |
| P3 | 5 层记忆系统 | ⬜ 大 feature |
| P3 | Context Collapse | ⬜ 需要 collapse store |

---

## 一、两系统 ReAct 循环全景对比

### 1.1 Claude Code 的 queryLoop

CC 的核心是一个 **`async while(true)` generator** (`src/query.ts`)，称为 `queryLoop()`。所有入口（REPL、SDK、Remote）全部通过同一个循环。

```
┌─────────────────────────────────────────────────────────┐
│  queryLoop(state) → while(true)                         │
│                                                        │
│  1. Build Query (system prompt + history + tools)       │
│  2. Call Model API (streaming)                          │
│  3. Parse Response → tool_use blocks?                   │
│     ├─ No  → Terminal(completed)                        │
│     └─ Yes → execute tools, append results              │
│  4. Check compaction threshold                          │
│  5. next iteration (new State object)                   │
└─────────────────────────────────────────────────────────┘
```

**核心设计原则**：

| 原则 | 说明 |
|------|------|
| **Wholesale replacement** | 每次 `continue` 创建新 `State` 对象，不修改 in-place |
| **Single-fire guards** | 布尔保护位（如 `hasAttemptedReactiveCompact`）防止无限重试 |
| **Async overlap** | Tool-use summary 生成与下一轮 API 调用并发执行 |
| **Transcript-first** | 用户消息在 API 调用**之前**写入磁盘，进程崩溃后可恢复 |
| **Generator all the way down** | `query`/`queryLoop`/`queryModel`/`handleStopHooks` 都是 `async function*` |

### 1.2 forge-agent 的 ReActAgent.run()

```
┌─────────────────────────────────────────────────────────┐
│  ReActAgent.run(task, event_log) → RunResult            │
│                                                        │
│  for step in range(1, max_steps + 1):                   │
│    1. RuntimeController.check() → 终止/继续/注水         │
│    2. TSM Guard 评估                                     │
│    3. build_messages(history, budget)                    │
│    4. LLMInvoker.call_with_retry(messages, tools)        │
│    5. Parse response → Action                           │
│    6. TOOL_CALL → validate_tool_calls → execute → obs   │
│    7. FINISH   → completion_fact_check → stop_hook      │
│                  → completion_guard → reflection         │
│    8. GIVE_UP  → terminate                              │
│    9. post-tool hooks + artifact extraction              │
└─────────────────────────────────────────────────────────┘
```

**核心差异**：

| 维度 | CC | forge-agent |
|------|----|-------------|
| 循环风格 | `while(true)` + generator | `for step in range(1, max_steps)` |
| 状态管理 | 新 State 对象 per iteration | mutable history + _child_turn_phase |
| API 调用 | 流式 StreamingToolExecutor | 同步 call_with_retry |
| 工具执行 | 流式分派 + 并发分区 | 顺序执行 + PARALLEL_SAFE 标记 |
| 终止判定 | 11 种 Terminal 原因 | FINISH/GIVE_UP/MAX_STEPS/CANCELLED |
| 恢复路径 | 7 种 continue site | 2 种 (stop_hook_block, completion_block) |

---

## 二、逐项差距分析

### 2.1 循环控制流：for-range vs while-true

**CC**: `while(true)` + `yield Terminal` 退出。循环内 7 个 continue 位置，每个位置创建新的 State 对象继续循环。

**forge-agent**: `for step in range(1, max_steps)` 提前限制步数。恢复逻辑只处理两种场景：stop hook block 和 completion guard block，其他异常直接 terminate。

**差距**：
- ❌ 缺少 reactive_compact_retry（413 prompt-too-long → 压缩后重试）
- ❌ 缺少 max_output_tokens_escalate（输出截断时自动提升 max_tokens）
- ❌ 缺少 max_output_tokens_recovery（截断后注入 "Resume directly" + 最多 3 次恢复）
- ❌ 缺少 collapse_drain_retry（提示过长 → 阶段性上下文折叠后重试）
- ✅ 有 stop_hook_blocking 恢复（stop hook 重试上限 3 次）
- ✅ 有 completion_block 恢复（completion_fact_check + completion_guard 注入后 continue）

**建议**：
1. 在 LLM 调用层加入 max_output_tokens 自动提升（8k → 64k，静默一次）
2. 加入 token budget continuation 机制（模型提前停止但 budget 未耗尽 → 注入 nudge 继续）
3. prompt-too-long 时触发逐级压缩（drain → collapse → reactive_compact）而非直接失败

### 2.2 状态管理：Immutable State vs Mutable Fields

**CC**: 每次循环迭代创建新 `State` 对象。State 字段包含 `messages`、`turnCount`、`stopHookActive`、`hasAttemptedReactiveCompact` 等。

**forge-agent**: ReActAgent 作为有状态对象，内部维护 `_stop_hook_count`、`_child_turn_phase` 等可变字段。ConversationHistory 是共享可变对象。

**差距**：
- ❌ 可变状态使恢复逻辑散落在多处，难以追踪
- ❌ 没有 single-fire guard 惯用法（如 `hasAttemptedReactiveCompact`）
- ❌ `_child_turn_phase` 作为 mutable field 跨 step 传递，需要手动重置

**建议**：
1. 提取 `AgentTurnState` dataclass，每次 step 后返回新实例或 None (terminal)
2. 关键 guard 位（has_attempted_compact, max_output_recovery_count）作为状态字段
3. `_child_turn_phase` 纳入 turn state 管理

### 2.3 工具执行：流式分派 vs 全量等待

**CC 的 StreamingToolExecutor**（这是最大差距）：

```
模型流式输出
  ├─ "I'll start by reading the file..."  ← 文本先渲染
  ├─ tool_use(Read)  ← 立即分派执行（不等后续 tool_use）
  ├─ "Now I'll search for..."            ← 文本继续渲染
  └─ tool_use(Grep)  ← 立即分派执行
  
  → Read 和 Grep 可以在模型还在生成文本时并行完成
  → 工具执行 + 文本生成 完全并发
```

**forge-agent**: 
```python
response = self._call_with_retry(messages, tools)  # 等待完整响应
action = response.action  # 解析 Action
# 然后才执行工具
for tool_call in action.tool_calls:
    result = registry.execute_tool(tool_call.name, tool_call.params)
```

**差距**：
- ❌ 必须等待完整响应才能执行工具 → 增加 wall-clock 延迟（典型场景 ~16%）
- ❌ 流式输出期间工具完全空闲
- ❌ 不能在工具执行期间继续渲染文本给用户

**建议** (P1)：
1. 实现 `StreamingToolExecutor` — 在流式解析到完整 `tool_use` block 时立即分派
2. 工具执行结果在 step 结束时按顺序 yield
3. 对于非流式后端保持现有行为（fallback）

### 2.4 并发执行：Partition 算法 vs PARALLEL_SAFE 标记

**CC 的 `partitionToolCalls()`**：

```
输入: [Read, Grep, Bash(ls), Edit, Read]
       ↓ per-call isConcurrencySafe() 检查
输出: Batch1[Read, Grep, Bash(ls)], Batch2[Edit], Batch3[Read]

关键: Bash("ls -la") → safe, Bash("rm -rf") → unsafe
      安全判定是 **per-call**，不是 per-tool-type
```

**forge-agent**:

```python
class ToolConcurrency(Enum):
    SERIAL = "serial"
    PARALLEL_SAFE = "parallel_safe"  # 按 tool 类型标记
```

工具注册时设置 `metadata.concurrency`，运行时按此标记决定是否并行。

**差距**：
- ❌ 并发安全是 tool-type-level，不是 per-call-level
- ❌ Bash 工具整体标记为 SERIAL，但 `ls`/`grep` 等读命令实际安全
- ❌ 没有 admission control（互斥规则：非安全工具运行时阻塞所有其他工具）
- ❌ 没有 Bash 错误级联取消（`mkdir build && cp src/* build/` → 前一个失败取消后续）

**建议** (P2)：
1. 实现 `concurrency_mode(params)` 已支持 per-call（Bash 工具可 override 为参数检查）
2. Bash 工具：解析命令，纯读命令返回 PARALLEL_SAFE
3. 实现 Bash 错误级联取消（sibling abort controller）

### 2.5 控制面：Tool Call Validation (Control Plane)

**CC**: 工具调用在执行前经过多层检查：
1. schema validation (Zod parse)
2. permission check (`checkPermissions`)
3. 互斥规则（admission control）
4. 上下文修改器队列（保证确定性）

**forge-agent**:
```python
if action.action_type == ActionType.TOOL_CALL and action.tool_calls and tools:
    _validation = validate_tool_calls(action.tool_calls, tools)
    if not _validation.valid:
        # 注入错误 observation，让 LLM 自动纠正
```

**差距**：
- ✅ 有 validate_tool_calls (schema 验证)
- ✅ 有 control plane 拒绝 + 错误注入机制
- ✅ 有 tool_use_id 规范化（后端可能不给 id）
- ❌ validate 后直接执行，没有 admission control（互斥等待队列）
- ❌ 没有 context modifier 队列机制

### 2.6 终止判定：11 条件 vs 4 条件

**CC 的 11 种 Terminal 原因**：
`completed`, `blocking_limit`, `image_error`, `model_error`, `aborted_streaming`,
`prompt_too_long`, `stop_hook_prevented`, `aborted_tools`, `hook_stopped`, `max_turns`,
`tool_use_stop`

**forge-agent**:
`FINISH`, `GIVE_UP`, `MAX_STEPS`, `CANCELLED`, `FAILED` (RunStatus enum)

**差距**：
- ❌ 缺少 `tool_use_stop`（模型调用了显式停止工具如 ExitPlanMode）
- ❌ 缺少 `prompt_too_long` 作为独立终止原因（当前直接 FAILED）
- ❌ 缺少 `hook_stopped`（hook 主动停止 session）
- ✅ 有 stop_hook 重试上限 + completion guard 双重保护

### 2.7 Nudge / Continue 机制

**CC**: 当模型自然停止（无 tool calls）但 token budget 未耗尽时，注入 nudge 消息：
> "You've stopped generating. There's budget remaining. Continue working if needed."

并有 **diminishing returns 检测**：连续 3 次 nudge 每次产生 <500 tokens → 停止继续 nudge。

**forge-agent**: 完全没有 nudge 机制。模型 FINISH 后直接进入 completion guard 流程。

**建议** (P2)：实现 budget continuation nudge，带 diminishing returns 检测。

### 2.8 Compaction: 流式 5 层 vs 离线触发

**CC 的 5 层压缩管道**（每次 API 调用前运行）：
1. `applyToolResultBudget()` — 限制单个 tool output 大小
2. `snipCompactIfNeeded()` — 裁剪中间旧消息
3. `microcompact()` — 合并连续 tool-result 对
4. `applyCollapsesIfNeeded()` — 阶段性上下文折叠
5. `autocompact()` — 全量 LLM 摘要（最昂贵）

**forge-agent**: `ConversationCompactor.tick_step()` 在每个 step 开始时检查是否需要压缩。有 MicroCompact + 全量 compact，但流程是串行的。

**差距**：
- ✅ 有 MicroCompact（零 API 调用清除旧 tool output）
- ✅ 有 CompactionRecovery（压缩后重新注入文件/技能内容）
- ❌ 没有 snipCompact（上下文接近限制时裁剪中间段）
- ❌ 没有 context collapse（阶段性折叠，可回滚）
- ❌ 压缩在 step 开始时检查，不是 API 调用前（浪费一个 step 的 token）
- ❌ 没有 reactive compact（413 错误时触发）

**建议** (P1)：将压缩检查移到 `_build_messages` 之后、LLM 调用之前（最接近上下文限制的时间点）。

### 2.9 Stop Hook 机制

**CC**:
- Stop hook 在每轮模型输出后执行（PostResponse 事件）
- 支持并行执行多个 hook
- 区分 blocking error / non_blocking error / success
- Hook 可以注入 systemMessage 到下一轮
- 还有 PreToolUse / PostToolUse / Notification / PostResponse 四种 hook 事件

**forge-agent**:
- Stop hook 在 FINISH 检测时触发（通过 HookDispatcher）
- 支持 PreToolUse / PostToolUse / Stop 三种事件
- BLOCK 控制流：返回 block/reason → 注入用户消息 + continue
- 重试上限 3 次（_MAX_STOP_HOOK_RETRIES）

**差距**：
- ✅ Stop hook 通过 dispatcher（已对齐 CC）
- ✅ PreToolUse updatedInput / PostToolUse updatedToolOutput 已实现
- ❌ 缺少 Notification hook 事件
- ❌ 缺少 PostResponse hook（模型输出后、工具执行前的全面检查点）
- ❌ Hook 结果没有区分 blocking error vs non_blocking error（全部 block 处理）

### 2.10 记忆系统：5 层 vs 2 层

**CC 的记忆系统**：Short-term → Working → Long-term (CLAUDE.md) → Summary (4级压缩) → Task persistence

**forge-agent**: ConversationHistory (短期) + MEMORY.md 持久化 (长期)

**差距**：
- ❌ 没有 working memory 抽象（当前任务状态的结构化跟踪）
- ❌ 没有 summary memory（压缩后的摘要层，CC 有 4 级压缩摘要）
- ❌ 没有 task persistence（跨 session 的任务连续性）

---

## 三、差距优先级汇总

| 优先级 | 差距 | 影响 | 实现难度 |
|--------|------|------|---------|
| 🔴 P0 | 流式工具执行 (StreamingToolExecutor) | wall-clock 延迟 ~16% | 高 |
| 🔴 P0 | 压缩检查时机 (API 调用前 vs step 开始) | Token 浪费 | 低 |
| 🟡 P1 | 循环控制流 (reactive_compact / token escalation / nudge) | 鲁棒性 | 中 |
| 🟡 P1 | Per-call 并发安全 (Bash 命令解析) | 并行效率 | 中 |
| 🟡 P1 | SnipCompact + Context Collapse | 上下文管理 | 中 |
| 🟢 P2 | Immutable TurnState + single-fire guards | 代码质量 | 中 |
| 🟢 P2 | Nudge/Continue 机制 + diminishing returns | 任务完成度 | 低 |
| 🟢 P2 | Bash 错误级联取消 (sibling abort) | 用户体验 | 低 |
| 🟢 P2 | 11 种终止条件 (tool_use_stop / prompt_too_long 等) | 可观测性 | 低 |
| 🟢 P3 | 5 层记忆系统 | 任务连续性 | 高 |
| 🟢 P3 | Hook 结果分类 (blocking/non_blocking) | Hook 可用性 | 低 |
| 🟢 P3 | PostResponse + Notification hook 事件 | Hook 覆盖面 | 低 |

---

## 四、推荐实现路线图

### Phase 1: 流式工具执行 (预计 8-12 文件)

这是最大、最影响用户体验的差距。

```
1. executor/streaming_tool_executor.py  ← 新建
   - StreamingToolExecutor 类
   - processQueue() 互斥规则
   - getCompletedResults() / getRemainingResults()
   
2. agent/core.py  ← 修改
   - 响应解析改为流式: 遇到 tool_use block 立即 yield
   - 维护 tool_call → result 映射
   
3. llm/invoker.py  ← 修改
   - 流式模式: yield (chunk_type, data) 而非等待完整响应
   
4. core/base.py  ← 修改
   - ToolConcurrency 增加 per-call 支持
   - BaseTool.concurrency_mode(params) 已支持，确保所有工具正确实现
```

### Phase 2: 恢复路径 + 压缩时机 (预计 4-6 文件)

```
1. agent/core.py  ← 修改
   - 提取 AgentTurnState dataclass
   - 加入 max_output_tokens_escalate (8k→64k)
   - 加入 token budget continuation (nudge)
   - 加入 reactive_compact_retry
   
2. context/compaction.py  ← 修改
   - 加入 SnipCompact
   - 压缩检查移到 _build_messages 之后
   
3. agent/runtime_controller.py  ← 修改
   - 加入 prompt_too_long 作为 StepAction.TERMINATE 原因
```

### Phase 3: 并发 + 记忆 + Hook (预计 5-8 文件)

```
1. core/base.py ← per-call 并发安全
2. tools/shell_tool.py ← Bash 命令解析，读命令标记 PARALLEL_SAFE
3. memory/ ← 5 层记忆 (working/summary/task_persistence)
4. hooks/ ← PostResponse + Notification 事件
```

---

## 五、关键参考

- [Claude Code 源码拆解 - 腾讯云](https://cloud.tencent.com.cn/developer/article/2698419)
- [Claude Code VS OpenCode - ReAct Loop](https://github.com/0xtresser/Claude-Code-VS-OpenCode/blob/7e81105e/EN/Chapter_03_Core_Loop_ReAct/3.1_Think_Act_Observe_Cycle.md)
- [Claude Code Handbook - Query Engine](https://github.com/inematds/claudecode-manual/blob/main/01-core-architecture/04-query-engine.md)
- [Claude Code Source - Concurrency](https://github.com/LetA-Tech/claude-code-from-source/blob/main/book/ch07-concurrency.md)
- [Anthropic Official - Parallel Tool Use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)
- [Claude Code the-loop.mdx](https://github.com/claude-code-best/claude-code/blob/79742411/docs/conversation/the-loop.mdx)
