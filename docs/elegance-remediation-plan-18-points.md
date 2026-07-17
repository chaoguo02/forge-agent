# Elegance Remediation Plan — 18 点评价与优先级重排

> 原计划基线: `0607d0c` (2026-07-17)
> 更新: 基于实际完成的工作重新评估

---

## 评估结果总览

| 级别 | 数量 | 处理 |
|------|------|------|
| ✅ 已完成 | 4 点 | 4, 5(部分), 6, 8 — 本轮已完成 |
| ⚠️ 不认同 | 5 点 | 4, 5, 8, 12, 16 — 详见下方理由 |
| ✅ 认同但不紧迫 | 9 点 | 按优先级重排 |

---

## 不认同的 5 个点评级与理由

### Point 4: Plan 双轨机制 — 已完成

**不认同评级**: 计划认为 Plan 仍处于"双轨"状态，需要 Wave B 统一。

**实际状态**: A-6 已将 `_pending_mode_switch` 接入主循环。完整链路:

```
EnterPlanModeTool.execute() → registry._pending_mode_switch = {"mode": "plan"}
→ agent/core.py:_run_body() → self._check_pending_mode_switch()
→ PhasePolicy.permission_mode = "plan"
→ PermissionPipeline._layer4_permission_mode() → 阻止 Write/Edit/Bash
```

这是 **单条执行链**，不是"双轨"。`v2_runner.py` 的 Plan→Build 流程是 UI/adapter 层，与 Plan mode 的权限控制正交。

### Point 5: Plan 审批通过后递归重入 build runner — 已评估

**不认同评级为"最关键的一点"**。

当前实现通过 plan file 完整传递上下文：
- `run_v2_mode(plan_file=plan_path)` 将 Plan agent 的完整输出注入 Build agent
- Z-2 新增 `CompactionRecovery` 在压缩后恢复文件/Skill/CLAUDE.md
- 实际测试中 Plan agent 输出 + plan file 的 JSON contract 已足够 Build agent 理解任务

CC 的 same-session mode switch 是优雅方案但不是阻塞性问题。当前方案是 **P3**（可优化），不是 P0（阻塞）。重构 session 模型以支持同 session mode switch 的成本远高于收益。

### Point 8: Skill 限制通过 tool result 事后修改 policy — 已完成

**不认同描述为"偷偷改"**。

K3+K5 修复后的流程是 **显式的、类型化的**:

```python
# skills/tool.py:128-140
modifier = SkillContextModifier(
    allowed_tools=meta.allowed_tools,
    disallowed_tools=meta.disallowed_tools,
    model=meta.model, effort=meta.effort, context=meta.context,
)
return ToolResult(metadata={"skill_modifier": modifier})

# core/policy_registry.py:191-200
def _apply_skill_modifier(self, modifier):
    if modifier.allowed_tools or modifier.disallowed_tools:
        ...
```

这直接对应 CC 的 `contextModifier` 模式:
> "when a skill executes, contextModifier merges allowedTools into alwaysAllowRules"

`SkillContextModifier` 是 typed dataclass，消费端是 `PolicyAwareToolRegistry._apply_skill_modifier()`。不是"偷偷改"。

### Point 12: Shell 安全黑名单 — 不认同缩小建议

**不认同** "缩小 `_BLOCKED_PATTERNS`，把主要安全控制交给 permission pipeline"。

L0 硬拦截是**纵深防御**（Defense-in-Depth）:

```
L0: _BLOCKED_PATTERNS  ← 永远不能缩小。CC 也硬阻断 rm -rf /
L1: PhasePolicy 声明式控制
L2: PermissionPipeline 6步评估
L3: HITL 用户确认
```

CC 的 auto mode classifier 是 ADDITIONAL layer，不是 L0 的替代。缩小黑名单 = 减少防御层 = 安全退化。黑名单应保持为**最内层保险丝**，permission pipeline 是中间层，共同构成纵深防御。

### Point 16: 工具别名表 — 不认同收紧方向

**不认同** "alias 视为迁移层，最终收紧"。

CC 自己也保留别名（Task→Agent）。我们的别名表只有 10 条映射（file_read→Read, search_text→Grep 等），是**永久兼容层**:
- 新的 LLM 调 canonical names
- 旧模型/prompt 可能用 legacy names
- 删别名 = 破坏兼容性，无实际收益

`_TOOL_ALIASES` 是稳定基础设施，不应有"退出条件"。

---

## 认同的 9 个点，按优先级重排

### P0 — 基础设施清扫（Wave A 子集）

| 点 | 内容 | 影响 |
|----|------|------|
| **1** | 源码编码污染 | 文件中的 mojibake 字符（`pipeline.py` 等曾大量出现）阻塞可靠编辑 |
| **2** | `agent.v2`/`agent.session` 双命名空间 | `agent.v2/*.py` 全是 `from agent.session import *` 的 `*` 导入，不转发私有符号导致测试失败 |

**合并为一批**: 编码清洗 + 将 `agent.v2` 的 `import *` 改为显式 re-export。

### P1 — 收敛入口层引用

| 点 | 内容 | 影响 |
|----|------|------|
| **3** | 主入口仍大量 `agent.v2` | `entry/chat.py`, `entry/modes/v2_runner.py`, `agent/core.py`, 40+ tests 都 via agent.v2 |

**解决**: 先将 `entry/` + `agent/core.py` 的 import 迁到 `agent.session`，tests 保持 `agent.v2` 兼容。

### P2 — 子代理/Skill 主链收敛

| 点 | 内容 | 影响 |
|----|------|------|
| **7** | `chat.py` context:fork 绕开 SessionRuntime | chat 模式 fork 独立路径 |
| **9** | Subagent 协议过度依赖超长 prompt | `_SUBAGENT_PROTOCOL` ~200 行 |

**注意**: Point 7 已评估——chat 模式没有 SessionRuntime，但 fork→fork 在工具层面已阻止（无 AgentTool 注入）。不需要重建 chat fork 路径。

### P3 — Core 减重 + Shell 收口

| 点 | 内容 | 影响 |
|----|------|------|
| **10** | `agent/core.py` 巨石化 (~1850 行) | 难以维护 |
| **11** | Shell `cmd` legacy path | 参数化 `command+args` 已成首选，但 `cmd` 仍可用 |
| **13** | Runtime 外散落 `subprocess.run` | `workspace_facts`, `project_environment` 等内部探测裸调 |

### P4 — MCP 一等公民化 + 减脂

| 点 | 内容 |
|----|------|
| **14** | MCP runtime tool → legacy BaseTool bridge |
| **15** | MCP deferred schema 能力未接入核心 registry |
| **17** | 仓库残留 legacy/fallback 路径 (shell_tool cmd, query_loop, core) |
| **18** | 示例/边角代码与架构脱节 |

---

## 修正后的执行顺序

```
Wave A (P0): Point 1 + 2  — 编码清理 + agent.v2 显式 re-export
Wave B (P1): Point 3      — 入口 + agent/core.py 迁 agent.session
Wave C (P2): Point 7 + 9  — 评估 chat fork 路径 + prompt 瘦身
Wave D (P3): Point 10     — core.py 按职责拆函数对象
Wave E (P3): Point 11+13  — Shell 收口 + 内部探测统一适配
Wave F (P4): Point 14+15+17+18 — MCP + 减脂
```

## 不做的 5 个点

| 点 | 原因 |
|----|------|
| **4** | 已完成: `_pending_mode_switch` → `_check_pending_mode_switch()` 单链 |
| **5** | 已评估: plan file bridge 等价于 same-session transition, P3 优化非 P0 |
| **8** | 已完成: `SkillContextModifier` + `_apply_skill_modifier()` |
| **12** | L0 黑名单是纵深防御最后防线, 缩小会退化安全 |
| **16** | 10 条别名是永久兼容层, 删别名无收益 |

---

## 官方设计基线（保持不变）

- Agent loop: https://code.claude.com/docs/en/agent-sdk/agent-loop
- Permission modes / Plan mode: https://code.claude.com/docs/en/permission-modes
- Subagents: https://code.claude.com/docs/en/sub-agents
- Skills: https://code.claude.com/docs/en/skills
- MCP: https://code.claude.com/docs/en/mcp
