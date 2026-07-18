# Subagent Claude Code 对标重排计划

日期：2026-07-17

状态：研究结论 / 仅规划，不改代码

---

## 1. 文档目标

这份文档只讨论一件事：

把当前 `forge-agent` 的 subagent 设计，与 Claude Code 在公开资料中可确认的 subagent 设计基线做一次重新对照，明确：

- 哪些地方已经在正确方向上
- 哪些地方只是“实现可用”，但语义仍偏离
- 哪些地方不应该继续局部打补丁，而应先统一目标语义

本文件不假设我们知道 Claude Code 的私有源码实现。
所有“Claude Code 做法”仅基于公开文档与可观察行为。

---

## 2. Claude Code 的公开 Subagent 基线

以下条目来自 Claude Code 官方公开资料，作为我们后续架构取舍的约束基线。

### 2.1 Named subagent 和 fork 是两种不同语义

公开基线：

- Named subagent：从自己的 agent 定义启动，使用 fresh context
- Fork：从当前会话分叉，继承父会话上下文

含义：

- 这两者不是同一能力的不同参数
- 不能只用一个“child session”抽象把它们语义抹平

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.2 Subagent 的默认边界是“独立上下文 + 回传摘要”

公开基线：

- subagent 使用自己的上下文窗口
- 主会话通常收到的是结果摘要，而不是完整 transcript 回灌

含义：

- parent/child 之间默认不是共享 history
- child transcript persistence 是 runtime 事实，不该变成 parent prompt 的一部分

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.3 一对多并行 + 父代理综合，是官方鼓励的标准工作流

公开基线：

- Claude Code 官方明确鼓励用多个 subagents 做并行研究/检查
- 然后由父代理综合结果

含义：

- fan-out 不是边缘能力
- runtime 应以“支持并行后综合”为一等场景，而不是例外

来源：

- Claude Code / Common workflows  
  https://code.claude.com/docs/en/common-workflows
- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.4 Nested subagents 是正式能力，但有明确边界

公开基线：

- nested subagents 受支持
- 官方文档给出深度限制
- fork 不能再次 spawn fork，但仍可继续 spawn 其他 subagents

含义：

- “父 -> 子 -> 孙”不是偏门
- 但 runtime 必须有明确深度边界和能力边界

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.5 Background 不是附属能力，而是核心运行时语义

公开基线：

- 官方文档说明：自 v2.1.198 起，subagent 默认后台运行
- Claude 仅在需要结果后才能继续时，才会前台等待

含义：

- foreground / background 是 runtime 调度语义
- 不能继续把 foreground 当默认、background 当特例

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.6 Resumed subagent 是“同会话继续”，不是新 fresh child

公开基线：

- `SendMessage` / follow-up 语义是继续已有 agent 会话
- completed child 收到 follow-up 后可以恢复执行

含义：

- resume 不是“重开一个类似 child”
- child identity、历史、预算语义都应作为 runtime 事实存在

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.7 Subagent 的能力约束主要来自声明式定义，而不是长提示词

公开基线：

- 官方 subagent frontmatter 公开了大量声明式字段：
  - `tools`
  - `disallowedTools`
  - `model`
  - `permissionMode`
  - `mcpServers`
  - `hooks`
  - `skills`
  - `memory`
  - `background`
  - `isolation`
  - `initialPrompt`
  - `maxTurns`

含义：

- Claude Code 的主思路不是“靠一大段 prompt 教模型怎么当 subagent”
- 而是“先声明能力边界，runtime 再交付给模型”

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

### 2.8 Main-thread allowlist 和 nested child allowlist 不是同一语义

公开基线：

- 官方文档明确指出：`Agent(worker)` 这种括号内 allowlist 语法，只对 main thread `claude --agent` 生效
- 在 subagent 定义里，这种细粒度类型约束会被忽略

含义：

- nested subagent 的约束语义，不能简单照搬主线程 allowlist
- 如果我们把整条子代理链都做成“统一类型 allowlist 传播”，很可能比官方更强、更偏

来源：

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

---

## 3. 当前仓库的 Subagent 实现基线

下面只记录当前代码已经实现出来的、与 subagent 主链直接相关的事实。

### 3.1 当前主链骨架

当前子代理主链已经具备以下骨架：

- `AgentTool` 作为统一子代理入口  
  `agent/session/task_tool.py`
- `AgentSpawnRequest` 作为 typed spawn contract  
  `agent/session/models.py`
- `SessionRuntime` 统一负责创建/运行 child session
- child result 通过 compact `<task-notification>` 返回 parent
- `SendMessage` / `WaitForAgent` / `CancelAgent` 作为 typed child control surface
- `_ChildTurnPhase` 作为 post-child synthesis / resolution 的最小 typed overlay

相关实现文件：

- `agent/session/task_tool.py`
- `agent/session/models.py`
- `agent/session/runtime.py`
- `agent/session/agent_control_tool.py`
- `agent/core.py`

### 3.2 当前已经比较接近正确方向的部分

#### A. named vs fork 已经被显式区分

当前：

- `AgentSpawnRequest.named(...)`
- `AgentSpawnRequest.fork(...)`

位置：

- `agent/session/models.py:621`
- `agent/session/models.py:645`

判断：

- 这是正确方向
- 不应再退回“一个 child session + if/else 猜语义”的旧做法

更具体地说：

- `AgentSpawnRequest` 已把 `agent_kind`、`context_origin`、`workspace_mode`、`execution_placement` 分开建模，而不是混成一个字符串字段  
  `agent/session/models.py:546-681`
- `spawn_agent(...)` 在 runtime 层也明确分开了 named / fork 两条前置校验路径  
  `agent/session/runtime.py:791-809`

#### B. typed spawn contract 已经建立

当前：

- `AgentSpawnRequest` 对 `agent_kind / context_origin / execution_placement / workspace_mode` 做了正交建模

位置：

- `agent/session/models.py:546`

判断：

- 这是当前 subagent 架构里最值得保留的基础层

更具体地说：

- named child 必须满足：
  - `ContextOrigin.FRESH | RESUMED`
  - `definition` 必须存在
  - `workspace_mode` 必须与 definition 一致  
  `agent/session/models.py:599-610`
- fork 必须满足：
  - `ContextOrigin.PARENT_SNAPSHOT | RESUMED`
  - 不能携带 `definition`  
  `agent/session/models.py:611-617`

这部分已经明显不是“传统 if/else 字符串状态机”，应继续保留。

#### C. child control 已经拆分为 typed tools

当前：

- `SendMessage`
- `WaitForAgent`
- `CancelAgent`
- `agent_control` 仅保留兼容层

位置：

- `agent/session/agent_control_tool.py:82`
- `agent/session/agent_control_tool.py:165`
- `agent/session/agent_control_tool.py:229`

判断：

- 这比早期“全部塞到一个 agent_control action 字段里”更对

更具体地说：

- `SendMessageTool`：terminal child resume  
  `agent/session/agent_control_tool.py:82-162`
- `WaitForAgentTool`：runtime-owned liveness wait  
  `agent/session/agent_control_tool.py:165-226`
- `CancelAgentTool`：cooperative cancel  
  `agent/session/agent_control_tool.py:229-260`
- `agent_control` 只是 compatibility wrapper，不再是唯一真实接口  
  同文件后半段

#### D. child completion 已经由 runtime 注入，而不是直接回灌完整 child history

当前：

- foreground child：工具 observation 返回 `<task-notification>`
- background child：runtime 持久化 completion notification，后续 turn 再注入

位置：

- `agent/session/task_tool.py`
- `agent/session/runtime.py`
- `agent/core.py`

判断：

- 这条链路的总体设计方向与 Claude Code 的公开语义一致

更具体地说：

- background child 完成后，runtime 会把 `AgentCompletionNotification` 写入 store  
  `agent/session/runtime.py:1121-1145`
- parent 后续 turn 再消费 notification，而不是直接塞回 child 全历史
- foreground child 也只通过 compact `<task-notification>` observation 回到 parent

这条线符合“child transcript 持久化属于 runtime，parent 默认只消费 compact result”的方向。

### 3.3 当前实现的关键文件分工

为了避免后续继续“哪里都改一点”，先把 subagent 主链的职责边界写死：

#### `agent/session/task_tool.py`

当前职责：

- 解析一次 `Agent(...)` 调用参数
- 校验是否允许委派
- 把 caller 输入转成 typed planning facts
- 决策 `AUTO / FOREGROUND / BACKGROUND`
- 构造 `AgentSpawnRequest`
- 把 foreground/background result 统一格式化为 `<task-notification>`

关键位置：

- `_SpawnPlanningFacts` / `_SpawnInvocationPlan`  
  `agent/session/task_tool.py:53-76`
- `_plan_from_params(...)`  
  `agent/session/task_tool.py` 中段
- `_resolve_execution_placement(...)`  
  `agent/session/task_tool.py` 中段
- `execute(...)`  
  `agent/session/task_tool.py` 中后段

#### `agent/session/models.py`

当前职责：

- child spawn contract 的 typed SSOT
- named / fork / resumed 三种 child 启动形态

关键位置：

- `AgentSpawnRequest`  
  `agent/session/models.py:546-681`

#### `agent/session/runtime.py`

当前职责：

- 真正创建 child session
- 校验 parent-child 边界
- 记录 child metadata
- 启动 foreground 或 background 执行
- 处理 resume / wait / cancel

关键位置：

- `spawn_agent(...)`  
  `agent/session/runtime.py:755-940`
- background completion publish  
  `agent/session/runtime.py:1111-1166`
- `send_agent_message(...)`  
  `agent/session/runtime.py:1168-1293`
- `wait_for_agent(...)`  
  `agent/session/runtime.py:1295-1348`

#### `agent/session/registry_builder.py`

当前职责：

- 决定一个 session 暴露哪些 delegation tools
- 给 session-bound registry 注入：
  - `Agent`
  - `SendMessage`
  - `WaitForAgent`
  - `CancelAgent`
  - `agent_control`
  - worktree review tools

关键位置：

- `attach_delegation_tools(...)`  
  `agent/session/registry_builder.py:23-102`

#### `agent/session/subagent_registry_factory.py`

当前职责：

- 给 child subagent 构造 restricted registry
- 应用 allowed/disallowed tools
- 注入 `submit_findings`
- 需要时继续给 nested subagent 注入 delegation tools

关键位置：

- `build_restricted_registry(...)`  
  `agent/session/subagent_registry_factory.py:22-110`

#### `agent/session/runtime_prompt_builder.py`

当前职责：

- 注入 primary agent 的 delegation prompt
- 把 available subagents / worktree protocol / review protocol / failure recovery 写进 prompt

关键位置：

- `build_runtime_messages(...)`  
  `agent/session/runtime_prompt_builder.py:19-190`

---

## 4. 当前与 Claude Code 基线之间的关键差距

这里只记录真正影响总体方向的差距，不记录局部实现风格问题。

### Gap S0：我们仍然把 Subagent 看成“父 ReAct 的特殊工具”，而不是“会话树中的原生节点”

现状：

- 设计上虽已有 session tree
- 但不少语义仍从 `AgentTool` 向外扩散，而不是从“child session 是一等 runtime 实体”向内收束

表现：

- prompt 层承担了过多 delegation discipline
- placement / synthesis / child review 仍部分附着在 parent tool thinking 上

影响：

- 架构容易出现“功能能跑，但越收越散”
- 每增加一种 child behavior，都容易继续往 prompt 和 tool helper 里堆

结论：

- 这是最核心的认知差距
- 后续所有改造都应先围绕“child session 是 runtime 原生节点”来收敛

### Gap S1：background 默认语义仍未与 Claude Code 对齐

Claude Code 公开基线：

- background 是默认运行语义

我们当前：

- `AgentSpawnRequest.resolve_execution_placement()` 仍以 foreground 为保守默认
- `AgentTool` 的 runtime facts 只在部分场景提升到 background

位置：

- `agent/session/models.py:558`
- `agent/session/task_tool.py:361`

更具体地说：

- `AgentSpawnRequest.resolve_execution_placement(...)` 现在的基础规则是：
  - named + `definition.background=True` -> `BACKGROUND`
  - 其他默认 `FOREGROUND`  
  `agent/session/models.py:558-582`
- `AgentTool._resolve_execution_placement(...)` 只在“parallel + worktree fork + typed parallel-safe”这类场景再升级到 background  
  `agent/session/task_tool.py` 中 `_resolve_execution_placement`

这意味着我们的真实心智仍然是：

- foreground 是主路径
- background 是升级路径

而不是：

- background 是主路径
- foreground 是“必须等结果时”的特化路径

对后续代码的具体影响：

- `send_agent_message(...)` 被设计为“terminal child resume in background”，而不是围绕“后台 child 是常态”来设计  
  `agent/session/runtime.py:1168-1293`
- `_ChildTurnPhase` 和 completion notification 虽然已经存在，但仍然更像“后台补充机制”，而不是 parent loop 的主流 child-result 入口

影响：

- parent synthesis / notification / agent view / child control 的整体心智仍偏向“前台为主，后台为辅”
- 这会持续影响后续所有 subagent 行为设计

结论：

- 这是 P0 级语义差距

### Gap S2：nested delegation 的约束语义，很可能比 Claude Code 更强、更自创

Claude Code 公开基线：

- nested subagent 支持继续委派
- main-thread 的 `Agent(worker)` 细粒度 allowlist 语义不直接下放给 subagent

我们当前：

- nested delegation 继续走统一 declarative allowlist / `delegatable_by(...)`
- 这在工程上整齐，但不一定与官方公开语义一致

具体代码位置：

- `registry_builder.attach_delegation_tools(...)` 在 session depth 允许时，统一根据 `delegatable_by(spec)` 决定是否暴露 `Agent`  
  `agent/session/registry_builder.py:23-56`
- `spawn_agent(...)` 对 named child 的合法性继续用  
  `self._agent_registry.delegatable_by(parent_definition)` 校验  
  `agent/session/runtime.py:790-803`
- `subagent_registry_factory.build_restricted_registry(...)` 在 `session is not None` 时，又会继续给 child registry 注入 delegation tools  
  `agent/session/subagent_registry_factory.py:86-99`

影响：

- 我们可能把子代理链限制得比 Claude Code 更死
- 之后如果继续扩展 nested subagent，很可能出现“实现精致，但行为不像 Claude Code”

结论：

- 这是 P0 级语义核查点
- 在没重新定义目标前，不应继续沿这条线局部修补

这里最值得警惕的不是“代码能不能跑”，而是：

- 我们现在的 nested delegation 语义，是“整个 child tree 都遵守同一套 declarative child-type allowlist”
- Claude Code 的公开语义更像“main-thread 和 subagent-thread 的 Agent 可见性规则不完全相同”

所以这不是一个实现 bug，而是目标模型可能已经分叉了。

### Gap S3：prompt 层过重，runtime 契约层仍不够强

现状：

- runtime prompt builder 里已经塞入大量 subagent discipline、review protocol、failure recovery 规则

位置：

- `agent/session/runtime_prompt_builder.py:131`

具体表现：

- 一整段 “Delegation isolation rules”  
  `agent/session/runtime_prompt_builder.py:140-153`
- 一整段 “Atomic Task Boundaries (MANDATORY)”  
  `agent/session/runtime_prompt_builder.py:154-163`
- 一整段 “Subagent Output Review Protocol (MANDATORY)”  
  `agent/session/runtime_prompt_builder.py:164-184`
- 一整段 “Subagent Failure Recovery”  
  `agent/session/runtime_prompt_builder.py:185-190`

影响：

- 行为稳定性更多依赖模型服从提示，而不是 runtime 提供客观事实边界
- 会导致规则不断膨胀，最终把架构问题转移成提示工程问题

结论：

- 这是 P0 级方向问题
- 不是说 prompt 没用，而是不能继续让 prompt 承担本该由 runtime/metadata 承担的职责

更直接地说：

- 如果一个约束可以通过 typed contract 校验，就不应主要靠 prompt 训话
- 如果一个行为必须由 parent 正确执行，就不应主要靠 prompt 记忆

例如下面这些，本质上都应优先 runtime 化，而不是继续加 prompt：

1. child deliverable completeness
2. parent synthesis turn 中禁止继续 fan-out 的时机
3. worktree result 是否已 inspect / retain / apply / discard
4. child result 是否已被 parent resolution

### Gap S4：resume child 的能力边界仍明显窄于 Claude Code 公开行为

Claude Code 公开基线：

- follow-up / resume 是同一 agent 会话的继续
- completed child 也可恢复
- 运行中 agent 的 course correction 能力更丰富

我们当前：

- `SendMessage` 更像 terminal child resume
- `WaitForAgent` 和 `CancelAgent` 仍是较窄 contract
- 不支持真正 running-child mailbox 式消息注入

位置：

- `agent/session/agent_control_tool.py:82`

具体代码证据：

- `SendMessageTool.description` 明确写着：
  - running child 不能 live follow-up
  - 必须等 terminal 后再 `SendMessage`  
  `agent/session/agent_control_tool.py:90-97`
- `send_agent_message(...)` 里如果 child.status 是 `RUNNING / QUEUED`，直接返回 `RUNNING_UNAVAILABLE`  
  `agent/session/runtime.py:1191-1199`
- 同时它又会：
  - 从 store 取 persisted transcript
  - `prepare_session_resume(...)`
  - 走 `AgentSpawnRequest.resumed(...)`
  - 自动 background 恢复  
  `agent/session/runtime.py:1234-1293`

结论：

- 这不是必须立刻补齐的 P0
- 但必须在文档上明确：我们当前只是“收窄版 child control”，不是“完整对齐”

### Gap S5：phase discipline 虽已 typed 化，但仍是最小实现

现状：

- 已有 `_ChildTurnPhase`
- 已有 completion notification parser
- 已有 resolution/synthesis transition helper

位置：

- `agent/core.py`

更具体地说：

- `_TaskNotificationFacts` / `_task_notification_facts_from_text(...)` 已开始消化 `<task-notification>`  
  `agent/core.py`
- `_advance_child_turn_phase(...)` 已把 child-result turn 的最小状态推进集中起来  
  `agent/core.py`

但当前依然只是：

- synthesis turn
- resolution pending turn
- resolution complete -> reopen

这还不是一个完整的 child lifecycle state model。

判断：

- 这一层已经进入正确方向
- 但还只是“最小 post-child synthesis discipline”，不是完整 child-result orchestration model

结论：

- 这是 P1，不是 P0

---

## 5. 该保留什么，停止什么，重做什么

### 5.1 应保留

这些是当前架构中已经对方向有帮助的部分，应继续保留：

1. `AgentSpawnRequest` 的 typed 正交建模
2. named / fork 的显式区分
3. child completion 通过 compact notification 返回 parent，而非回灌完整 history
4. typed child control surface：`SendMessage` / `WaitForAgent` / `CancelAgent`
5. worktree-based isolation 作为 runtime-owned project isolation 手段

### 5.2 应立即停止继续局部加码的方向

以下方向在没有先统一语义前，不应继续局部扩写：

1. 继续往 runtime prompt builder 里添加更长的 subagent discipline 提示
2. 继续假设 nested delegation 必须沿整条链继承同一种细粒度 allowlist 语义
3. 继续以“foreground 默认”心智扩展 child lifecycle
4. 继续把一些本可 runtime 化的边界，转移成 prompt 规则或字符串判断

### 5.3 应重做 / 重新定义目标语义的部分

1. background 默认语义
2. nested delegation 权限边界语义
3. resumed child 的正式 contract
4. prompt discipline 与 runtime contract 的职责边界

补充说明：

这些不是“建议优化”，而是会决定后续实现到底朝哪个方向长。

如果这四项不先定下来，后续很容易继续出现：

- `task_tool.py` 收得更漂亮了，但 placement 心智仍偏
- `runtime.py` 继续加 resume / wait / cancel，但 child control 目标不清
- `runtime_prompt_builder.py` 持续变厚，runtime contract 反而不增长

---

## 6. Subagent 专项重排计划

下面的计划只规划，不在本轮执行代码修改。

## P0：先统一目标语义，再允许继续编码

### P0-1. 写清楚我们自己的 Subagent 目标语义表

必须先定出以下术语的最终语义：

- named subagent
- fork
- resumed child
- foreground
- background
- nested delegation
- direct child
- child completion notification
- post-child synthesis
- resolution pending

要求：

- 每个术语只有一个 runtime 定义
- 不能同时存在“文档语义”和“代码实际语义”两套版本

### P0-2. 重新校准 background default

目标：

- 明确我们是否要对齐 Claude Code 的“background default”公开语义

如果决定对齐：

- 则后续设计必须从“后台为常态”出发重看：
  - completion notification
  - Agent view / wait / cancel / resume
  - parent synthesis turn
  - fan-out orchestration

需要直接复核的本地代码：

- `agent/session/models.py:558-582`
- `agent/session/task_tool.py` 的 `_resolve_execution_placement(...)`
- `agent/session/runtime.py:1111-1293`
- `agent/core.py` 的 `_ChildTurnPhase` 使用点

如果决定不完全对齐：

- 必须在文档中明确写出“我们保留更保守的 foreground-first 设计”，避免继续自称完全对标 Claude Code

### P0-3. 重新定义 nested delegation contract

目标：

- 明确 nested child 是否继续沿用同一套类型 allowlist
- 或改成更接近 Claude Code 公开语义的“有 Agent 即可继续委派，但受深度和 runtime policy 限制”

这是 P0，因为这会直接影响：

- registry 暴露策略
- permission pipeline
- child runtime prompt
- nested fan-out 设计

需要直接复核的本地代码：

- `agent/session/registry_builder.py:23-102`
- `agent/session/subagent_registry_factory.py:86-99`
- `agent/session/runtime.py:790-803`

### P0-4. 给 prompt 层做职责瘦身边界

目标：

- 明确哪些规则必须进入 runtime contract
- 哪些规则可以保留在 prompt guidance

建议原则：

- 客观可验证的，进 runtime
- 模型行为建议性的，留 prompt

需要直接复核的本地代码：

- `agent/session/runtime_prompt_builder.py:131-190`
- `agent/session/task_tool.py` 的 `_build_subagent_prompt(...)`
- `tools/submit_findings_tool.py`
- `agent/completion_guard.py`

---

## P1：在统一语义后做结构化收束

### P1-1. 把 child lifecycle 抽成更正式的 runtime contract

方向：

- spawn
- running
- completed
- resumed
- background-notified
- resolution-pending
- resolved

要求：

- 不再让 phase 语义分散在 tool / prompt / event text 中
- 由 runtime 持有真正的状态机事实

直接涉及的现有代码：

- `agent/session/runtime.py`
- `agent/core.py`
- `agent/session/models.py`

### P1-2. 把 child notification 的解析与消费完全 runtime 化

当前：

- 已有最小解析 helper

后续目标：

- 让 parent 看到的不是“XML 片段导致的 phase 推断”
- 而是“runtime 已解析出的 child-result facts”

直接涉及的现有代码：

- `agent/session/task_tool.py` 的 `_format_fork_result(...)`
- `agent/session/runtime.py` 的 notification publish / claim
- `agent/core.py` 的 `_task_notification_facts_from_text(...)`

### P1-3. 把 resume contract 正式建模

方向：

- resumed child 的身份
- generation 递增
- transcript continuation
- budget / step limit 的继承与截断
- completion notification 的二次发布语义

直接涉及的现有代码：

- `agent/session/runtime.py:1168-1293`
- `agent/session/agent_control_tool.py`
- `agent/session/models.py:663-681`

### P1-4. 明确 direct child / nested child / unrelated child 的控制边界

目标：

- `SendMessage` / `WaitForAgent` / `CancelAgent` 的对象边界应更清楚
- 减少 future 扩展时的歧义

直接涉及的现有代码：

- `agent/session/runtime.py` 中 `_require_direct_child(...)` 相关逻辑
- `agent/session/agent_control_tool.py`

---

## P2：再考虑增强，而不是现在就加

这些不是当前最优先的：

1. running child 的 live mailbox / live steering
2. 更完整的 agent view
3. 更细粒度的 child-side MCP 生命周期定制
4. transcript UI / color / display-level parity

这些只有在 P0 / P1 明确后再做，才不会越做越偏。

---

## 7. 对当前代码改造的总原则

后续任何 subagent 改动，都应遵守下面 6 条：

1. 先校准 Claude Code 公开语义，再改本地实现
2. 先改 runtime contract，再改 prompt wording
3. 先改目标语义，再改局部 helper
4. 允许“我们与 Claude Code 不完全相同”，但必须明确写出差异
5. 不再把未确认的 Claude Code 私有实现，当成确定事实
6. 不为了“更优雅”引入额外抽象，除非它能减少语义漂移

---

## 8. 当前建议结论

一句话总结：

当前 `forge-agent` 的 subagent 架构，已经具备继续演进的骨架，但如果不先重定以下三个语义，就会继续出现“越改越细、越看不到头”的问题：

1. background default
2. nested delegation contract
3. prompt vs runtime contract 的职责边界

因此，下一步不应该再继续零散修改 subagent 代码，而应该先按本文件完成：

- P0 目标语义校准
- 然后再进入按批次的实现

更具体地说，当前最不该继续“边修边试”的文件是：

1. `agent/session/runtime_prompt_builder.py`
   - 因为它最容易继续承接本应 runtime 化的约束

2. `agent/session/subagent_registry_factory.py`
   - 因为 nested delegation 的目标语义还没定，继续收这里很容易把错误目标固化

3. `agent/session/runtime.py` 的 resume / background 分支
   - 因为 background default 与 resume contract 还没统一

当前最值得保留并作为后续重构锚点的文件是：

1. `agent/session/models.py`
   - typed spawn contract 已较清晰

2. `agent/session/task_tool.py`
   - 现在已经具备 typed planning facts，可作为 policy 重构入口

3. `agent/core.py`
   - 已经有最小 typed phase overlay，可继续往 runtime lifecycle 方向演进

---

## 9. 本轮涉及的本地代码定位

- `agent/session/task_tool.py`
- `agent/session/models.py`
- `agent/session/runtime_prompt_builder.py`
- `agent/session/agent_control_tool.py`
- `agent/core.py`

---

## 10. 外部资料来源

- Claude Code / Subagents  
  https://code.claude.com/docs/en/sub-agents

- Claude Code / Common workflows  
  https://code.claude.com/docs/en/common-workflows

- Claude Code / SDK  
  https://docs.anthropic.com/en/docs/claude-code/sdk
