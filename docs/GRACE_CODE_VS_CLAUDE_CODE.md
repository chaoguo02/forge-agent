# Grace Code vs Claude Code — 全维度架构对比评分

> 审计日期: 2026-07-24
> 审计范围: agent/core.py, session/runtime.py, hitl/pipeline.py, hooks/, context/, server/services/, tools/

---

## 评分总览

| 维度 | Grace Code | Claude Code | 差距 |
|------|:---------:|:----------:|------|
| **ReAct 核心循环** | 7 | 9 | 流式工具调度滞后 |
| **工具系统** | 7 | 8 | Git Tool 过度封装 |
| **权限管道** | 9 | 9 | 基本对齐 |
| **Hook 系统** | 8 | 8 | 对齐，缺文件级 matcher |
| **上下文管理** | 8 | 9 | Prompt cache 缺原生支持 |
| **事件流** | 7 | 8 | 缺 mid-stream tool dispatch |
| **多 Agent 编排** | 8 | 8 | Worktree 隔离是亮点 |
| **Prompt 组装** | 6 | 9 | 模块化不够，缺 CLAUDE.md |
| **错误恢复** | 6 | 9 | 流路径 token 估算粗糙 |
| **Git 集成** | 6 | 8 | 专用 Tool 而非 Bash 范式 |
| ****加权总分** | **7.2** | **8.6** | **差 1.4 分** |

---

## 逐维度详细分析

### 1. ReAct 核心循环 — Grace 7 / CC 9

**做对了的**:
- TSM (TaskStateMachine) 是 CC 没有的亮点——显式的状态机保证 lifecycle 正确性，verification 状态集中管理
- 双层守卫 (RuntimeController + TSM guards) 提供 defense-in-depth
- Completion guard 合理：stop hook → fact check → git diff，三层由外层到内层
- 三路退出统一走 `_build_run_result()`，输出一致

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| 工具执行时机 | LLM 完成后再 dispatch | LLM streaming 中 dispatch（speculative execution） |
| 并行检测 | `partition_tool_calls()` 基于 `ToolConcurrency` | 相同方案，但工具标记更丰富 |
| Token 流式输出 | `stream_callback` 做文本输出 | 原生 streaming + structured output |
| 输出截断恢复 | 流路径用估算，经典路径用 `finish_reason=="length"` | 统一从 provider response 读实际值 |

**核心差距**: 流式工具调度。CC 在 LLM 还在生成时就启动 `tool_use` 块的执行，我们等 LLM 完全返回再一起执行。并行 Read 当然快，但如果 LLM 生成 4 个 tool call 花了 3 秒，工具执行花了 2 秒，总共 5 秒——而 CC 在 3 秒时就已经有工具结果了。

**改进路线**: `StreamingToolExecutor.enqueue()` 已经做了 speculative start，但没有在流中主动轮询 `process_queue()`。在 `stream_iter` 的循环里加一次 `process_queue()` 调用即可实现 CC 级别的 speculative dispatch。

---

### 2. 工具系统 — Grace 7 / CC 8

**做对了的**:
- `ToolRegistry` DI 注入，权限在边界拦截
- `ToolMetadata` 声明 effects / roles / path_access / concurrency——这套元数据结构是 CC 级别的
- `StreamingToolExecutor` 的 partition 算法正确：consecutive safe → batch，non-safe → serial
- Bash 安全层：`_BLOCKED_PATTERNS` + `_READ_ONLY_COMMANDS` + `_validate_workspace_paths`

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| Git 操作 | 4 个专用 Tool | Bash 执行 `git` CLI |
| 工具总数 | ~26 个（含 4 个 Git Tool） | ~15 个（Bash 替代了 5-10 个） |
| 工具描述 Token | ~3,500 tokens | ~2,000 tokens |
| Bash→Git 引导 | Bash description 引导 LLM 不用 Bash 做 git | 无引导，LLM 自由选择 |

**核心差距**: Git Tool。审计 Phase 6 已得出 🟡 混合模式的结论，但即便改完也只是回到 Bash 范式——这本身就是 CC 已经在做且做得更好的地方。

---

### 3. 权限管道 — Grace 9 / CC 9

**几乎完全对齐**。6-layer pipeline 和 CC 一致：

| Layer | Grace Code | Claude Code | 对齐度 |
|-------|-----------|------------|:--:|
| L1 validateInput | `_layer1_validate()` — 受保护路径 + 工具自检 | `canUseTool` 系统级黑名单 | ✅ |
| L2 PreToolUse | `_layer2_hooks()` — HookDispatcher | Shell scripts via HookDispatcher | ✅ |
| L3 Rules | `_layer3_rules()` — deny→ask→allow→session | deny > ask > allow with glob | ✅ |
| L4 Permission Mode | `_layer4_permission_mode()` — bypass/acceptEdits/plan/dontAsk | 相同 4 种模式 | ✅ |
| L4.5 Prompt-based | `_match_approved_prompt()` — token overlap | `allowedPrompts` from ExitPlanMode | ✅ |
| L5 Allow + Sandbox | `_layer5_check()` — path sandbox | path sandbox via project root | ✅ |
| L6 Interactive | `_layer6_callback()` — Web callback / TTY callback | stdin control_request / control_response | ✅ |

**Grace Code 的额外亮点**: `PermissionPipeline` 原生支持 headless Web 模式——`ApprovalBroker` 用 `threading.Event` 代替 `stdin.readline()`。CC 的 headless 模式是通过 NDJSON over stdin/stdout 实现的，Grace Code 直接用 HTTP callback 解耦——在 Web-forward 架构里更干净。

**微差**: 权限规则的 `if` 条件目前只支持 `tool_input.FIELD matches 'PATTERN'`。CC 支持更丰富的条件表达式。

---

### 4. Hook 系统 — Grace 8 / CC 8

**做对了的**:
- `HookDispatcher` 事件驱动：event → matcher → execute → decide
- `BLOCKABLE_EVENTS` 区分 blockable/non-blockable
- 三层结果：BLOCK / APPROVE / CONTINUE
- Internal hooks (Python) + external hooks (subprocess)
- `_MAX_TOTAL = 30s` hook 执行预算上限（CC 无此保护）

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| 文件级 matcher | `HookMatcher(pattern="*", if_condition=...)` — 仅支持 `tool_input.FIELD matches 'PATTERN'` | 支持 `if: "tool_input.path matches 'src/**'"` |
| Hook 附加物 | `DispatchResult.additional_context` 字符串 | `HookAttachment` 带 `kind + text + source`（刚加进来但未接入 UI） |
| 每事件 context 类型 | `HookContext` 14 个扁平字段，不同事件用不同子集 | Per-event context 子类，类型安全 |

---

### 5. 上下文管理 — Grace 8 / CC 9

**做对了的**:
- CC 的 3-tier 层级：Budget → Snip → MicroCompact → AutoCompact → Collapse → Recovery
- `ConversationCompactor` 用 LLM 压缩对话历史
- 读时投影（read-time projection）：CollapseStore 不修改原始消息

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| Prompt caching | `enable_caching` 标志 + structured content blocks | 原生 Anthropic `cache_control: {"type": "ephemeral"}` |
| Auto-compact 触发 | `_execution_budget.token_used > request_budget_tokens` 时触发 | 同样用 token 计数，但更精准 |
| 压缩粒度 | 整轮对话压缩 | Per-message 标记哪些可丢弃 |
| 内存占用追踪 | `_auto_compacted` 单标志 | 多次压缩后追踪 cumulative savings |

**核心差距**: Prompt caching。Anthropic backend 可以用 structured content 实现 `cache_control` 点位——在 system prompt 末尾 + 最后一条工具结果前打标记。DeepSeek 等 OpenAI-compatible backend 不支持这个特性，无法原生利用。

---

### 6. 事件流 — Grace 7 / CC 8

**做对了的**:
- EventBus 的 SessionSubscriber 队列模式：agent thread → `call_soon_threadsafe` → asyncio drain → WebSocket broadcast
- 事件翻译层 `_translate_event()` 把内部 Event → 标准化 WS 消息
- `thought_delta` 流式输出

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| Mid-stream tool dispatch | 无——等 LLM 完成后才开始工具执行 | StreamIter 中检测 `tool_use` → 立即 dispatch |
| 事件去重 | `_seenFingerprints` (type+step+key) — 但只在实时路径 | 内置在协议层 |
| Trace replay | `/trace/events` API 过滤 lifecycle events | 无等价端点——CC 没有 Web 前端的 trace replay |
| 事件保序 | `_ordered_results = executor.collect()` — 按输入序 | 相同 |

**改进路线**: 在 `_stream_and_dispatch()` 的事件循环里，`enqueue()` 之后立即调用 `executor.process_queue()`——当前代码已经在做 `process_queue()`（line 2583），但只在 `enqueue` 后调用一次，应该在每个 `yield` 后主动 poll。

---

### 7. 多 Agent 编排 — Grace 8 / CC 8

**做对了的**:
- `SessionRuntime` + `AgentRegistryV2` 的 agent 发现和生命周期管理
- Fork / Named subagent 两种模式，场景分明
- Worktree 隔离——这是 CC 没有的机制。子 agent 在独立 worktree 上执行，parent 显式 apply/discard

**差在哪里**:

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| Agent 定义 | `.md` YAML frontmatter，工具 allowlist 声明式 | 类似，但工具集合动态生成 |
| 上下文继承 | Fork 继承 parent conversation snapshot | 同样通过 snapshot 继承 |
| 结果交付 | `SubagentReport`（结构化 findings）+ `task-notification` XML | `Task` tool 返回结构化结果 |
| 并发控制 | 一个 session 一个 agent 线程 | CC 类似 |

**亮点**: Worktree 隔离是 Grace Code 独有的——CC 的子任务在同一个工作树上执行，可能导致文件冲突。Grace Code 的 `DockerRuntime` 提供了更强的隔离。

---

### 8. Prompt 组装 — Grace 6 / CC 9

**这是最大的差距维度**。

| 维度 | Grace Code | Claude Code |
|------|-----------|------------|
| System prompt 结构 | `PromptAssembler` 从文件模板渲染 | 多段结构：capabilities + CLAUDE.md + skills + memory + repo map |
| Project instructions | 无 CLAUDE.md 等价物 | `CLAUDE.md` 项目级指令，自动发现和注入 |
| Skills | ✅ 从 `.grace/skills/` 加载，YAML 声明 | ✅ 类似 |
| Memory | `MemoryContext` + `SessionMemoryTracker` — 基础 | Multi-tier: auto-memory + session notes + CLAUDE.md |
| Tool descriptions | 每个 Tool 的 `description` 属性拼接 | 同 |
| Repo map | ✅ `RepoMap` 生成文件树摘要 | ✅ 类似 |
| 模块级全局变量 | `prompts/builder.py` 中有 `_assembler` 全局 + `_project_dir` 全局 | 无全局状态 |

**核心差距**: 
1. **无 CLAUDE.md**。这是一个显著的缺失。CLAUDE.md 是用户给 agent 提供的项目上下文（编码规范、架构说明、技术栈信息），在 CC 中是第一段注入的 system prompt 内容。没有它，agent 对项目的理解完全依赖运行时探索。
2. **Prompt assembler 全局状态**——多 session 场景下的隐患。
3. **Memory 系统相比之下太基础**。CC 有 proactive memory extraction（每轮结束后 LLM 反思并记录关键决策），Grace Code 的 `RunFinalizer` 只做了提取→存储，但没有做 active recall（运行时主动检索相关记忆）。

---

### 9. 错误恢复 — Grace 6 / CC 9

| 恢复机制 | Grace Code | Claude Code | 状态 |
|---------|-----------|------------|:--:|
| prompt-too-long → reactive compact | ✅ `_recover_from_llm_error()` | ✅ | 对齐 |
| output truncation escalation | 流路径用估算值（`estimate_tokens`）| 从 provider response 读精确值 | 🟡 |
| Tool failure → retry | ✅ consecutive failures → GIVE_UP | ✅ | 对齐 |
| Circuit breaker | ✅ Permission denials 累计 → terminate | ✅ | 对齐 |
| Budget exhausted | ✅ `ExecutionBudget.check()` → strip tools → one more turn | ✅ | 对齐 |
| max_steps → finish | ✅ RuntimeController terminates | ✅ | 对齐 |

**核心差距**: 流路径的 token 计数用 `estimate_tokens()`（字符数÷3），误差 20-30%。`StreamEvent` 没有 token 字段，需要改所有 backend adapter 的 streaming 接口。这不是架构问题，是接口演进问题。

---

### 10. Git 集成 — Grace 6 / CC 8

**CC 的做法**: 所有 git 操作通过 Bash 工具执行。LLM 自主选择 `git status --porcelain`、`git diff --stat`、`git log --oneline -5 --graph --all` 等任意组合。Bash 工具的安全层拦截危险操作（`git push --force` 等）。

**Grace Code 的做法**: 4 个专用 Git Tool 覆盖 status/diff/add/commit。Bash 的 description 引导 LLM 用专用 Tool 而非 Bash 做 git 操作。Bash 的 `_READ_ONLY_PREFIXES` 已为 11 种 git 只读操作标记为并发安全，但 `_BLOCKED_PATTERNS` 不含 `git push`、`git reset --hard` 等危险操作。

**差距本质**: 不是"专用 Tool 不好"，而是"Bash 已经有足够的 git 白名单后，专用 Tool 的维护成本 > 收益"。Phase 6 审计已给出混合模式方案。

---

## 综合判断

### 已经达到 CC 水平的（≥8 分）

- **权限管道**: 9 分。6-layer 对齐，Web headless 模式是额外优势
- **Hook 系统**: 8 分。事件驱动架构一致
- **上下文管理**: 8 分。3-tier 压缩对齐，差在 prompt cache 的原生支持
- **多 Agent 编排**: 8 分。Worktree 隔离超出 CC

### 有差距但可接受的（6-7 分）

- **ReAct 循环**: 7 分。差在流式工具调度
- **工具系统**: 7 分。Git Tool 可以瘦身
- **事件流**: 7 分。Mid-stream dispatch 可实现但未实现
- **错误恢复**: 6 分。流路径 token 估算不精确
- **Git 集成**: 6 分。混合模式待实施

### 差距较大的（≤6 分）

- **Prompt 组装**: 6 分。**无 CLAUDE.md**，memory 系统基础

---

## 改进优先级

| 优先级 | 改进项 | 预计成本 | 预估收益 |
|:--:|--------|:------:|:------:|
| **P0** | 实现 CLAUDE.md 自动发现和注入 | 1-2 天 | 每个项目零配置获得 agent 上下文指导 |
| **P0** | StreamEvent 接口加 token 字段 | 1 天 | 流路径 token 计数精确化，纠正 truncation 恢复判断 |
| **P1** | Prompt assembler 消除全局状态 | 2 天 | 多 session 并发安全，架构干净 |
| **P1** | Mid-stream speculative dispatch | 2-3 天 | 4-tool-call 步骤减少 30-40% 延迟 |
| **P2** | Git 混合模式迁移 | 1 天 | 减少 2 个 Tool + ~150 行代码 |
| **P2** | Memory active recall | 3-5 天 | 跨 session 知识积累 |

### 一句话总结

**Grace Code 在"安全和控制"维度（权限管道、Hook 系统、TSM 状态机、Worktree 隔离）已经达到甚至超越了 Claude Code；但在"智能和体验"维度（CLAUDE.md、流式调度、Memory 系统、Prompt 组装）有 1-2 代差距。差距不在架构上，在功能覆盖面上。**
