# 六大子系统 CC 对齐期末总结

> 日期：2026-07-17
> 状态：收尾评估

---

## 总览

| 子系统 | 完成度 | 剩余工作 | 剩余工作量 |
|--------|--------|---------|-----------|
| ReAct | 95% | Context Collapse | 大 feature |
| Plan | 100% | 无 | 无 |
| Subagent | 80% | background / nested delegation / resume contract | 有 P0 语义差距 |
| MCP | 90% | On-demand connect + OAuth | 小 + 不适用部分 |
| Skills | 95% | 无 | 无 |
| Hooks | 95% | Notification event | 小 |

**总体完成度：约 92%-95%**

---

## 一、ReAct

### 已完成

| 项目 | 说明 |
|------|------|
| StreamingToolExecutor | enqueue -> dispatch -> collect，带 admission control |
| Per-call 并发安全 | partition_tool_calls，Bash 命令解析（读命令 = PARALLEL_SAFE） |
| OpenAI stream_iter | SSE chunk 中实时 yield TOOL_USE event |
| Bash 错误级联 | sibling abort controller |
| 事件驱动 collect | threading.Event wake signal 替代 sleep 轮询 |
| 恢复路径 x4 | escalate、recovery inject、reactive_compact、nudge |
| diminishing returns | 3 次 x <500 tokens -> 停止 nudge |
| SnipCompact | 零成本空结果/拒绝结果过滤 |
| 终止条件 16 种 | 覆盖 CC 的 11 种 + 5 种额外情况 |
| AgentTurnState (frozen) | immutable per-turn state，typed Transition |
| RecoveryState (frozen) | 与 AgentTurnState 一致的可变粒度 |
| 21 continue 点全部有 State 更新 | 审计完成，无遗漏 |

### 未完成

| 项目 | 说明 | 工作量 |
|------|------|--------|
| Context Collapse | collapse store + projectView 虚拟压缩视图 | 大 feature，独立计划 |
| 5 层记忆系统 | working/summary/task persistence | 大 feature，独立计划 |

---

## 二、Plan Mode

### 已完成

| 项目 | 说明 |
|------|------|
| Session 连续性 | Plan -> Build 复用同一 session（reuse_session_id） |
| Prompt-based permissions | ExitPlanModeTool.allowedPrompts，auto-allow 匹配调用 |
| System prompt 节流 | 第 1 轮全量，每 5 轮稀疏提醒，每 25 轮完整再注入 |
| JSON contract | PlanValidator + PlanContract 模型 |
| 5 选项审批 | Execute / Edit / Re-plan / Save / Abort |
| EnterPlanMode/ExitPlanMode | 信号工具，pending_mode_switch 机制 |
| Permission mode restore | prePlanMode 保存/恢复 |
| Bash 不拦截 | Plan mode Step 4 只拦 Write/Edit |

### 未完成

无。Plan mode 可以视为已完成对齐。

---

## 三、Subagent

### 已完成

| 项目 | 说明 |
|------|------|
| named / fork 显式区分 | `AgentSpawnRequest.named()` / `.fork()` |
| typed spawn contract | `AgentKind` / `ContextOrigin` / `ExecutionPlacement` / `WorkspaceMode` 正交建模 |
| child control surface | `SendMessage` / `WaitForAgent` / `CancelAgent` / `agent_control` |
| AUTO placement runtime policy | 已支持 background / foreground / auto，且具备 typed runtime 决策 |
| child resume surface | terminal child resume + Wait/Cancel 分离，比早期单一 `agent_control` 更清晰 |
| child completion -> compact notification | foreground/background 统一 `<task-notification>` 回传 |
| worktree isolation | apply/discard/retain + resolution protocol |
| child phase typed overlay | `_ChildTurnPhase` + runtime notification parsing + resolution transition helper |
| prompt 瘦身 | 已去掉一部分与 runtime 重复的强制规则 |

### 未完成

| 项目 | 说明 | 工作量 |
|------|------|--------|
| background default | Claude Code 公开语义更偏后台默认；我们当前仍是 foreground-first + 局部 runtime upgrade | P0 语义 |
| nested delegation contract | Claude Code 官方公开文档写明 subagent 不能再 spawn other subagents；我们当前允许 nested delegation，语义未对齐 | P0 语义 |
| resume / live steering boundary | 当前 `SendMessage` 仅支持 terminal child resume，不支持 running child live follow-up | P0 / P1 合同 |
| child notification full runtime-ify | 当前已从分散字符串匹配收束为集中解析，但 parent phase 仍消费 XML payload | P1 结构 |
| prompt vs runtime contract | delegation prompt 仍偏重，仍有一部分约束未完全 runtime 化 | P0 架构 |

> 注：
>
> 本节按 2026-07-17 可确认的 Claude Code 官方公开文档修正，不代表其私有源码实现细节。
> 更准确的结论是：Subagent 核心骨架已成，但仍存在关键语义差距，不能写成“已无关键差距”或“已完成 CC 语义对齐”。

---

## 四、MCP

### 已完成

| 项目 | 说明 |
|------|------|
| 4 transport | stdio / HTTP / SSE / WebSocket |
| Sync bridge | SyncMCPToolManager + 指数退避自动重试 |
| Resources 支持 | list_resources / read_resource |
| Notifications 支持 | tools/list_changed + 工具刷新 |
| Agent-scoped 连接生命周期 | connect_agent_servers / disconnect_agent_servers |
| 用户级 MCP 配置 | `~/.forge-agent.json`（对应 CC 的用户级配置思路） |
| 项目级 MCP 配置 | `.mcp.json` |
| CLI 管理命令 | mcp add/list/get/remove（支持 `--scope user/project`） |
| MCPToolIntegration | V2 session registry 集成 |
| SSE notification dispatch | MCP notification 类型分派 |
| HTTP content-type 验证 | warn on non-JSON |
| ToolSearch + WaitForMcpServers | MCP 工具发现 + 等待 |

### 未完成

| 项目 | 说明 | 工作量 |
|------|------|--------|
| On-demand connect | 懒加载（首次调用时才连接） | 小 |
| OAuth 认证 | SSE transport 自动 OAuth flow | 不适用（headless） |
| Enterprise / managed config | managed-mcp.json | 不适用（自部署） |
| 20 服务器限制 | 超限性能警告 | 很小 |

---

## 五、Skills

### 已完成

| 项目 | 说明 |
|------|------|
| 文件系统 Skill | `.forge-agent/skills/<name>/SKILL.md` |
| YAML frontmatter 解析 | model / effort / allowedTools / disable-model-invocation |
| SkillContextModifier | allowed_tools / disallowed_tools / model / effort |
| `$ARGUMENTS` 替换 | 模板变量替换 |
| CC-aligned 命名 | `Skill` 工具名 + `use_skill` alias |
| Runtime-based 执行 | `SkillTool` 接受 runtime 参数，安全执行 |
| SkillRegistry 自动创建 | registry_factory 中自动发现 |
| Chat 集成 | `/skill-name` slash command |
| 兼容路径 | `.claude/skills/` 作为备选源 |

### 未完成

无关键差距。

---

## 六、Hooks

### 已完成

| 项目 | 说明 |
|------|------|
| HookEvent 类型 | PreToolUse / PostToolUse / PostToolUseFailure / Stop / SessionStart / UserPromptSubmit / SubagentStart / SubagentStop / PostResponse / PermissionRequest |
| Per-session HookDispatcher | 克隆全局 registry + agent frontmatter hooks |
| PreToolUse updatedInput | Hook 可修改工具参数 |
| PostToolUse updatedToolOutput | Hook 可追加额外上下文 |
| Stop hook（dispatcher 优先） | 通用 block/reason 模式 |
| External hook 执行 | Runtime-managed 进程执行 |
| HookMatcher | Glob pattern 匹配 |
| non_blocking_error 分类 | Exit 0/2/other -> CONTINUE/BLOCK/NON_BLOCKING_ERROR |
| DispatchResult.warnings | 累积非阻塞错误 |
| PostResponse event | 每轮 LLM 响应后触发 |

### 未完成

| 项目 | 说明 | 工作量 |
|------|------|--------|
| Notification hook 事件 | MCP/系统级通知的 hook 事件 | 小 |

---

## 七、不再继续的项目

以下 gap 被明确评估为不适用或暂不纳入当前路线：

| 项目 | 原因 |
|------|------|
| OAuth（MCP SSE transport） | headless 模式不适用 |
| Enterprise / managed MCP config | 自部署项目不适用 |
| Elicitation（CC 的引导式对话） | 当前自部署项目不适用 |
| Channels（CC 的多通道协作） | 当前自部署项目不适用 |
| Plan mode 进入审批（Cap 1） | headless 模式跳过交互审批 |

---

## 八、最终结论

六大子系统整体都已进入收尾阶段，但其中 Subagent 不能再按“已基本完结”处理。

当前更准确的结论是：

1. **ReAct / Plan / Skills / Hooks** 已进入稳定迭代区
2. **MCP** 剩少量能力性补齐与不适用项澄清
3. **Subagent** 已完成核心骨架，但仍有关键语义差距需要先统一目标再继续实现

当前真正需要继续跟进的重点是：

1. **Context Collapse** —— 独立大 feature，需要 collapse store 基础设施
2. **5 层记忆系统** —— 独立大 feature，需要后续 extraction + consolidation 管道
3. **Subagent P0 语义校准** —— 重点包括：
   - background default
   - nested delegation contract
   - resume / live steering boundary
   - prompt vs runtime contract

也就是说，代码库整体已经处于“可以稳定迭代”的状态，但 **Subagent 仍不应视为完全收尾**。
