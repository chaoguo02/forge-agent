# forge-agent 综合行动方案

> 基于 `docs/gap.md` 审计 + WebSearch 调研 CC 实现依据
> 每个问题包括：CC 如何实现、我们哪里错了、具体怎么改

---

## P0-1: R1 — 删除文本关键词完成判断

### CC 实现依据

Claude Code 的隐式完成（默认）：`stop_reason="end_turn"` 且无 tool calls → 任务完成。

```typescript
// 查询引擎核心循环
while (true) {
    const response = askTheModel(messages)
    if (response.hasToolCalls()) {
        const results = runThoseTools()
        messages.append(results)
    } else {
        break  // ← 隐式完成：无 tool calls 即完成
    }
}
```

**不解析回答文本语义来判断生命周期。** Provider 只根据协议事实：有 tool calls → 执行工具；stop + 无 tool calls → 最终回答。

### 我们哪里错了

[llm/openai_backend.py:393](llm/openai_backend.py:393):
```python
_FINISH_KEYWORDS = ("task complete", "任务完成", ...)  # 17 个中英文关键词
_GIVE_UP_KEYWORDS = ("unable to", "无法", ...)         # 12 个放弃关键词
```

根据回答是否包含特定文本决定 success/gave_up。

### 修改方向

```python
# 正确方案：Provider 边界仅根据协议事实判断
def _classify_stop_reason(self, response: dict) -> ActionType:
    if response.get("tool_calls"):
        return ActionType.TOOL_CALL   # 有工具调用
    if response.get("finish_reason") == "stop":
        return ActionType.FINISH       # 正常 stop → 最终回答
    if response.get("finish_reason") == "length":
        return ActionType.MAX_TOKENS   # 截断 → 类型化失败
    return ActionType.FINISH           # 默认：末尾无 tool calls = 完成
```

删除 `_FINISH_KEYWORDS` 和 `_GIVE_UP_KEYWORDS` 两个元组。

---

## P0-2: K2 — Skill Shell 注入改走 Runtime

### CC 实现依据

CC Skill 的 Shell 注入有多层防护：
1. **MCP skill 跳过 shell 执行**——远程不受信任来源
2. **Workspace trust**——Shell 注入受项目信任边界控制
3. **Sandbox 可选**——`bubblewrap`/`Seatbelt` 提供 OS 级隔离
4. **Permission Pipeline**——每个命令经过 `PreToolUse hooks → deny → ask → allow`

### 我们哪里错了

[skills/registry.py:400](skills/registry.py:400) 直接用 `subprocess.run(..., shell=True, cwd=skill_dir)`，完全绕过：
- Runtime 编码清洗
- PermissionPipeline
- PreToolUse Hooks
- 项目绝对路径约束

### 修改方向

Skill 渲染器产生 `DynamicContextRequest` 而非直接执行：
```python
# skills/registry.py: _expand_inline_commands()
# 不再 subprocess.run()，而是返回未展开的占位符
# 在 Runtime 层统一执行，经过完整权限检查
def _expand_inline_commands(self, content, cwd):
    """CC-aligned: return shell request, don't execute directly."""
    # 返回 CommandRequest 对象，由 PermissionPipeline 统一处理
    requests = []
    for match in self._INLINE_CMD_RE.finditer(content):
        requests.append(ShellCommandRequest(cmd=match.group(1), cwd=cwd))
    return content, requests  # 不直接 execute
```

---

## P0-3: K1, K3 — SkillTool 与 SkillContextModifier 修复

### CC 实现依据

CC 的 `SkillTool.call()` 返回 `{ type: ToolResultType.REPROMPT, contextModifier }`。

`contextModifier` 闭包：
- `allowedTools → AppState.toolPermissionContext.alwaysAllowRules.command`
- `model → resolveSkillModelOverride()`
- `effort → AppState.effortValue`

### 我们哪里错了

**K1**: [entry/chat.py:425](entry/chat.py:425) 调 `self._skill_registry._get_skill_meta()` 但公开名是 `get_skill_meta()` → AttributeError。

**K3**: [skills/tool.py:125](skills/tool.py:125) 的 `execute()` 返回普通 `ToolResult`，不带 `metadata`。而 [core/policy_registry.py:191](core/policy_registry.py:191) 等 `result.metadata["skill_modifier"]`。

### 修改方向

```python
# skills/tool.py: SkillTool.execute()
return ToolResult(
    success=True,
    output=f"[Skill: {skill_name}]\n\n{rendered}",
    metadata={
        "skill_modifier": SkillContextModifier(
            allowed_tools=meta.allowed_tools,
            disallowed_tools=meta.disallowed_tools,
            model=meta.model,
            effort=meta.effort,
            context=meta.context,
        ),
    },
)
```

```python
# entry/chat.py: 修复调用
meta = self._skill_registry.get_skill_meta(name)  # 公开方法
```

---

## P0-4: S1 — 子 Agent 隔离 PermissionPipeline

### CC 实现依据

CC 的 Subagent 有自己的 `ToolPermissionContext`，**不共享**父的 pipeline 对象。每个 Subagent 通过 `resolveAgentTools()` 创建过滤后的工具池。

关键：per-request 的 `ToolPermissionContext` 是**不可变快照**，不修改全局状态。

### 我们哪里错了

[agent/session/runtime.py:886](agent/session/runtime.py:886) 直接修改 `self._base_registry._permission_pipeline`——这是共享对象。并行 Subagent 会互相覆盖权限模式。

### 修改方向

```python
# 为每个子 Session 创建派生的 PermissionPipeline
def _build_child_pipeline(self, parent_pipeline, child_spec):
    return parent_pipeline.for_agent(child_spec.name).with_permission_mode(
        self._resolve_child_permission_mode(parent, child)
    )
# 传递给子 Registry，不修改 _base_registry
```

---

## P0-5: M1, M2, M3 — MCP Agent-scoped 生命周期闭环

### CC 实现依据

CC Subagent frontmatter `mcpServers`：
- 内联定义：agent 启动时连接，结束时断开
- 字符串引用：复用 session 级连接
- 工具注册后对 agent 可见

### 我们哪里错了

**M1** 三处断点：
1. `server_tools` 用 `server__tool` 前缀匹配，但实际名称是 `mcp__server__tool`
2. `connect_agent_servers()` 只放 Proxy 进 `_tools`，不注册到 `_base_registry`
3. `registry.filtered(declared)` 过滤掉了新连接的工具

**M2** ToolSearch 只返回文字，不注入 schema。

**M3** `disconnect_agent_servers()` 中 `sn in getattr(rt, "mcp_props", None)` 对 dataclass 做 `in` 检查 → TypeError。

### 修改方向

```python
# M1 fix: connect_agent_servers() 注册到 base_registry
def connect_agent_servers(self, spec) -> list[str]:
    for name, config in mcp_configs:
        tools = self._manager.load_and_discover([config])
        for tool in tools:
            proxy = MCPRuntimeToolProxy(tool)
            proxy.server_name = name
            self._tools.append(proxy)
            if self._base_registry is not None:
                self._base_registry.register(proxy)  # ← 注册到基础池
    return [t.name for t in self._tools]

# M3 fix: 用 hasattr + getattr 替代 in 操作
server_name = getattr(rt, "mcp_props", None)
if server_name is not None and hasattr(server_name, "server_name"):
    if server_name.server_name in server_names:
        ...
```

---

## P0-6: P1 — EnterPlanMode/ExitPlanMode 接入主循环

### CC 实现依据

`handlePlanModeTransition(fromMode, toMode)` 直接修改全局 `AppState.toolPermissionContext.mode`：
```typescript
function handlePlanModeTransition(fromMode, toMode) {
    if (toMode === 'plan' && fromMode !== 'plan') {
        STATE.needsPlanModeExitAttachment = false
    }
    if (fromMode === 'plan' && toMode !== 'plan') {
        STATE.needsPlanModeExitAttachment = true
    }
}
```
主循环每次迭代检查 `STATE.toolPermissionContext.mode`。

### 我们哪里错了

`EnterPlanModeTool` 写入 `registry._pending_mode_switch`，但**没有代码读取它**。整个 `_signal_mode_switch()` 机制是装饰性的。

### 修改方向

```python
# agent/core.py: 主循环中检查 _pending_mode_switch
def _run_body(self, task, log, policy):
    while True:
        # ... 正常循环 ...
        if hasattr(self._registry, "_pending_mode_switch"):
            switch = self._registry._pending_mode_switch
            if switch:
                new_mode = switch["mode"]
                self._apply_mode_switch(new_mode)
                self._registry._pending_mode_switch = None
```

---

## P0-7: P2 — 去掉 Plan 的强制 JSON 前置门槛

### CC 实现依据

CC Plan Mode：
- 模型将计划写入 Markdown 文件 (`~/.claude/plans/<word-slug>.md`)
- 计划文件可编辑
- 审批后在同一 Session 切换模式执行
- **无强制 JSON Schema**

### 我们哪里错了

[entry/modes/v2_runner.py:419](entry/modes/v2_runner.py:419) 强制执行 JSON 提取 → Pydantic 验证 → 两轮修复 → 渲染。计划展示被 JSON 校验阻塞。

### 修改方向

```python
# entry/modes/v2_runner.py: 简化 Plan 审批流
# Phase 1 (当前回合): 立即保存 Markdown 计划并展示
plan_text = result.summary or ""
Path(plan_path).write_text(plan_text)

# Phase 2 (可选): 如有 JSON contract，提取为类型化元数据
contract = _try_extract_json(plan_text)  # best effort, 不阻塞

# Phase 3: 展示 + 审批
interaction.show_plan(plan_text, plan_path)
```

---

## P0-8: P3 — Plan→Build 同 Session 状态转换

### CC 实现依据

CC 的 `handlePlanModeTransition` 在同一 Session 内切换：
```
default → plan → (approval) → default/acceptEdits
```
不创建新的 Session。

### 我们哪里错了

[entry/modes/v2_runner.py:533](entry/modes/v2_runner.py:533) 递归调用 `run_v2_mode(agent_name="build")`，创建新根会话。导致规划上下文丢失。

### 修改方向

```python
# 不在 run_v2_mode() 中递归，而是在同一个 SessionRecord 上做权限模式转换
if action is PlanAction.TRIGGER_BUILD:
    # Session-level mode transition (not new session)
    session.transition_mode(SessionMode.BUILD)
    # 更新 spec.intent 和 permission_mode
    return runtime.run_session(
        session.id, agent_name="build",
        messages=[plan_context_message],  # 延续历史
        intent=TaskIntent.EDIT,
    )
```

---

## P1-1: R2 — 合并三套生命周期控制

### CC 实现依据

CC 的查询引擎是 **单一路径**：
```typescript
while (true) {
    response = queryWithRetry()
    if (response.hasToolCalls()) { executeTools(); continue }
    if (shouldStop(response)) { break }
}
```
停止条件在 `shouldStop()` 中统一判断，不存在三套独立机制。

### 修改方向

保留 `TaskStateMachine` 作为唯一生命周期权威。删除 `RuntimeController` 和 `_run_body()` 中的重复判断。Guard 注册到 TSM，TSM 驱动循环。

---

## P1-2: R3, R4 — 消息类型化 + 子 Agent 压缩

### CC 实现依据

CC 消息有明确类型：`UserMessage` / `AssistantMessage` / `ToolResult` / `CompactionBoundary` 等。

### 修改方向

```python
class MessageKind(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_RESULT = "tool_result"
    COMPACTION_BOUNDARY = "compaction_boundary"
    RUNTIME_NOTICE = "runtime_notice"
```

`Compactor` 根据 `MessageKind` 决策，不根据 `content.startswith("[Conversation compacted")`。

---

## P1-3: S2, S4, S5 — Subagent 生命周期 + 注入

### S2: 后台 Agent 清理

在 `_start_background_execution()` 中注册清理回调：
```python
def _start_background_execution(self, ..., cleanup_fn=None):
    thread = threading.Thread(target=self._run_background, args=(..., cleanup_fn))
```

### S4: Skills/Memory 注入子 Agent

在 `_build_system_messages()` 中调用 `runtime_prompt_builder.build_runtime_messages()`。

### S5: Hook 隔离

子 Agent 创建独立的 `HookConfig` snapshot，不修改全局 registry。

---

## P1-4: K4, K5 — context:fork + allowed-tools 语义修正

### K4: context:fork 语义

CC: `context: fork` 是 **fresh context** Subagent。

修复：移除 fork 中注入 `self._shared_history` 的代码。改为通过 `AgentSpawnRequest.named()` 走标准路径。

### K5: allowed-tools 语义

CC: `allowed-tools` = 免审批预批准，不是工具白名单。

修复：`PhasePolicy` 中区分 `pre_approved_tools`（免审批）和 `allowed_tools`（可见工具白名单）。

---

## 执行顺序（按 P0 → P1 → P2）

```
Phase 1 (P0): R1(关键词) → K1+K3(Skill) → K2(Skill Shell) → M1+M2+M3(MCP) → S1(Pipeline隔离)
Phase 2 (P0): P1(PlanMode) → P2(Plan JSON) → P3(Plan Session)
Phase 3 (P1): R2(生命周期) → R3+R4(消息类型化) → S2+S4+S5(Subagent) → K4+K5(Skill语义) → K6+K7(Skill)
Phase 4 (P2): M4+M5+M6(MCP增强) + 测试闭环
```

每个 Phase 完成后：全量回归测试 + commit。
