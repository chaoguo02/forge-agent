# 架构整改意见与分批执行计划（更新版）

最后更新：2026-07-17  
适用基线：当前工作区（含你刚刚对 `agent/v2/*` shim 的小范围修正）

## 这次更新相对上一版的变化

这版文档基于你刚刚已经落地的小改动做了修正，不再把 `agent.v2` shim 问题当成“纯待做项”，而是改为：

- 已有正确方向的增量落地
- 需要继续把 shim 收口做完整
- 之后再迁移主入口和测试引用

你刚刚已完成的部分：

- `agent/v2/agent_definition.py`
- `agent/v2/agent_registry.py`
- `agent/v2/subagent.py`
- `agent/v2/task_tool.py`

这些文件已经从“只有 `import *`”演进为“`import *` + 显式补齐私有符号 re-export”。这个方向我认同，而且说明我们的整改可以继续沿着“先稳兼容层、再迁主入口”的顺序推进。

---

## 总体判断

我对你更新后的判断，结论仍然是：

- 主方向基本正确
- 但有几项不能过早判定为“已经解决”
- 另外现在最需要的是把计划从“观点列表”升级成“可执行批次”

我当前的判断分为三类。

### A. 我认同，并建议继续推进

- Point 1：编码污染清理
- Point 2：`agent.v2` 兼容层收口
- Point 3：主入口改用 `agent.session`
- Point 9：subagent 协议减重
- Point 10：`agent/core.py` 拆职责
- Point 11：shell `cmd` legacy path 退场
- Point 13：内部 `subprocess.run(...)` 统一适配
- Point 14：MCP 一等公民化继续推进
- Point 15：MCP deferred schema 接入核心 registry
- Point 17：legacy / fallback 做 inventory 再收口
- Point 18：示例和边角代码迁移到 canonical API

### B. 我保留意见，但不建议现在先动

- Point 7：`chat.py` 里的 skill fork 确实是分叉点，但它不是当前最阻塞成功率的问题。先把 session/subagent 主链收稳，再回头统一 chat-mode 的 spawn 语义更合理。

### C. 我不同意当前“已解决/可移除”的判断

- Point 4：Plan 不能算完全收口
- Point 5：Plan 审批后递归重入 build runner 仍是架构债务
- Point 8：Skill modifier 仍未完全对齐 Claude Code 语义
- Point 12：L0 黑名单应保留，但不能继续膨胀为主权限系统
- Point 16：工具别名可以长期保留，但应该冻结边界，不继续扩张

---

## 需要纠正的 5 个判断

### 1) Point 4 不是“已完成”，而是“部分完成”

当前已经完成的部分：

- `tools/plan_mode_tool.py:22` 通过 `_pending_mode_switch` 发起模式切换
- `agent/core.py:1608` 在主循环中消费 `_pending_mode_switch`

但仍未收口的部分：

- `entry/modes/v2_runner.py:197`
- `entry/modes/v2_runner.py:390`
- `entry/modes/v2_runner.py:457`

也就是说：

- 权限语义层面，Plan mode 已经接上主循环
- 运行编排层面，仍保留了一条独立的 Plan approval / replan / build orchestration 链路

所以这项更准确的状态应该是：

- 已部分完成
- 还不是最终收口

### 2) Point 5 不应删除，只能降级

我同意它不再是最前面的 P0 阻塞项，但不认同把它从整改计划里拿掉。

原因很简单：

- Claude Code 的理想语义是“同一 session 内切换 mode”
- 我们当前仍是“Plan 产物落文件，再由 runner 触发后续 build 路径”

这在功能上可工作，但仍然属于架构债务，而不是最终形态。

### 3) Point 8 还没有真正对齐 Claude Code 技能授权语义

关键定位：

- `skills/tool.py:128`
- `core/policy_registry.py:198`
- `core/policy_registry.py:210`
- `core/policy.py:299`

当前问题不是“有没有 typed dataclass”，这个已经有了；真正的问题是：

- skill 返回的是 `SkillContextModifier`
- 但消费时对 `allowed_tools` 走的是 `with_allowed_tools(...)`
- 而不是 `with_pre_approved_tools(...)`

这会把“本轮免确认授权”做成“直接收窄可见工具集合”，语义不等价。

所以这项状态应该是：

- 类型层已完成一半
- 语义层仍未完成

### 4) Point 12 应保留 L0，但不要继续把更多语义堆进黑名单

关键定位：

- `tools/shell_tool.py:34`
- `tools/shell_tool.py:244`

我不建议删除 `_BLOCKED_PATTERNS`，因为它是最后一道硬阻断。  
但我同样不建议继续扩张它，让它承担越来越多的权限判断职责。

更合理的边界是：

- L0：只保留少量绝对不可协商的硬阻断
- L1+：主权限语义交给 policy / permission pipeline / protected paths

### 5) Point 16 应冻结 alias 边界，而不是继续自然扩展

关键定位：

- `agent/session/agent_registry.py:16`
- `tools/file_tool.py:208`
- `tools/search_tool.py:81`
- `tools/shell_tool.py:79`

我的意见不是删除 alias，而是：

- 保留现有兼容价值
- 停止新增更多灰色别名
- 文档、测试、新实现统一使用 canonical name

---

## 结合你刚刚代码改动后的新状态

### Point 2：从“建议”升级为“已启动，继续做完整”

你已经修掉 4 个 shim：

- `agent/v2/agent_definition.py`
- `agent/v2/agent_registry.py`
- `agent/v2/subagent.py`
- `agent/v2/task_tool.py`

仓库里仍然还有若干 `agent.v2` shim 仍是单纯 `import *`，例如：

- `agent/v2/models.py`
- `agent/v2/runtime_prompt_builder.py`
- `agent/v2/runtime.py`
- `agent/v2/mcp_integration.py`
- `agent/v2/agent_factory.py`
- `agent/v2/session_store.py`
- `agent/v2/task_state_machine.py`
- `agent/v2/run_context.py`
- `agent/v2/task_contract.py`
- `agent/v2/worktree_service.py`
- `agent/v2/subagent_registry_factory.py`
- `agent/v2/registry_builder.py`
- `agent/v2/result_contract.py`
- `agent/v2/execution_budget.py`

其中并不是所有 shim 都需要显式补齐私有符号，但至少应该做一次分组：

1. 纯公开 API shim：保留 `import *` 即可  
2. 被测试或入口直接引用私有符号的 shim：显式补齐 re-export  
3. 几乎无人引用的 shim：后续直接迁移入口后可删除

这一步现在已经具备继续推进的条件。

### Point 3：主入口仍大量依赖 `agent.v2`

当前主入口和关键路径仍有明显 `agent.v2` 依赖：

- `entry/chat.py`
- `entry/cli.py`
- `entry/modes/v2_runner.py`
- `entry/worktree_admin.py`
- `agent/core.py`
- `agent/runtime_controller.py`

这说明我们还没有真正让 `agent.session` 成为唯一 canonical implementation。

### Point 8：文档里不能再写“已完成”

因为 `core/policy_registry.py` 当前仍然是：

- 有 `with_pre_approved_tools(...)`
- 但 skill modifier 消费时走的是 `with_allowed_tools(...)`

所以这项要从“已完成”改回“待修正”。

---

## 批次划分

下面的批次是按“先稳兼容层，再迁主入口，再收紧语义，再做减重”的顺序排的。每一批都控制在 15 个文件以内。

### Batch 1：补齐 `agent.v2` shim 分组与显式 re-export 收口

目标：

- 把 `agent.v2` 兼容层从“半隐式”收口成“可审计的兼容层”
- 不改主行为，只修兼容契约

建议文件：

- `agent/v2/models.py`
- `agent/v2/runtime_prompt_builder.py`
- `agent/v2/runtime.py`
- `agent/v2/mcp_integration.py`
- `agent/v2/agent_factory.py`
- `agent/v2/session_store.py`
- `agent/v2/task_state_machine.py`
- `agent/v2/run_context.py`
- `agent/v2/task_contract.py`
- `agent/v2/worktree_service.py`
- `agent/v2/subagent_registry_factory.py`
- `agent/v2/registry_builder.py`
- `agent/v2/result_contract.py`
- `agent/v2/execution_budget.py`
- `agent/v2/__init__.py`

本批原则：

- 不做业务重写
- 只做 shim 分类、补齐缺失导出、补文档说明
- 若某 shim 没有私有符号需求，不强行增加额外导出

验收标准：

- `agent.v2` shim 行为可预测
- 私有符号引用不再依赖偶然行为

### Batch 2：主入口 import 迁移到 `agent.session`

目标：

- 让真正的 canonical namespace 进入主入口

建议文件：

- `entry/chat.py`
- `entry/cli.py`
- `entry/modes/v2_runner.py`
- `entry/worktree_admin.py`
- `agent/core.py`
- `agent/runtime_controller.py`

本批原则：

- 只迁 import 路径
- 不顺手改业务逻辑
- 保留 `agent.v2` 兼容层供测试与旧调用过渡

验收标准：

- 主入口不再依赖 `agent.v2` 作为一手实现层

### Batch 3：Skill modifier 语义对齐

目标：

- 把 skill 的 allowed-tools 语义从“工具集合裁剪”纠正为“本轮预授权”

建议文件：

- `skills/tool.py`
- `core/policy_registry.py`
- `core/policy.py`
- `skills/registry.py`
- 如有必要：相关测试文件

本批原则：

- 不扩大 skill 功能面
- 只修正授权语义与生命周期

验收标准：

- skill modifier 影响的是 pre-approval，而不是工具可见性误裁剪
- 生命周期清晰，能说明何时生效、何时清除

### Batch 4：Plan / approval 双轨收口设计

目标：

- 先把 Plan 的“当前状态”和“目标状态”在代码上分清
- 再逐步缩减 `v2_runner.py` 的独立编排职责

建议文件：

- `tools/plan_mode_tool.py`
- `agent/core.py`
- `entry/modes/v2_runner.py`
- `entry/cli.py`
- 相关 plan approval 测试

本批原则：

- 先补注释、契约、状态边界
- 不急于一步到位重写成同 session 切换
- 先避免继续新增第二套 Plan 语义

验收标准：

- 文档和实现对 Plan 的状态描述一致
- 后续可继续演进，而不是越改越分叉

### Batch 5：subagent 协议减重 + completion contract 下沉

目标：

- 减少 `_SUBAGENT_PROTOCOL` 这种超重 prompt 对稳定性的依赖

建议文件：

- `agent/session/task_tool.py`
- `agent/session/subagent.py`
- `agent/session/runtime.py`
- `agent/session/result_contract.py`
- `agent/session/task_contract.py`
- `agent/session/agent_factory.py`

本批原则：

- 角色说明保留
- 输出结构、完成条件、诊断结构尽量下沉到 typed contract / runtime

验收标准：

- subagent 成功性不再过度依赖超长协议 prompt

### Batch 6：`agent/core.py` 拆职责

目标：

- 将主循环与周边机制拆开

建议文件：

- `agent/core.py`
- 新拆分出的 3~6 个 supporting module

建议拆分方向：

- loop driver
- mode switch handling
- reflection / review policy
- completion policy
- history materialization

本批原则：

- 第一轮只搬运职责，不变行为

验收标准：

- `agent/core.py` 明显瘦身
- 主循环结构更接近 Claude Code 的干净 loop 骨架

### Batch 7：Shell 收口 + 内部进程调用统一适配

目标：

- 统一“用户态 shell 调用”和“内部事实采集”的底层进程适配约束

建议文件：

- `tools/shell_tool.py`
- `executor/process.py`
- `executor/project_environment.py`
- `executor/workspace_facts.py`
- 必要的 shared adapter 文件

本批原则：

- `command + args` 成为唯一主路径
- `cmd` 退为兼容路径并显式标记
- 内部 `subprocess.run(...)` 共享编码、timeout、cwd 校验、错误归类

验收标准：

- 进程执行语义更统一
- 项目隔离边界更稳定

### Batch 8：MCP registry 一等公民化

目标：

- 让 MCP 的 deferred schema / metadata 真正接入核心 registry

建议文件：

- `agent/session/mcp_integration.py`
- `executor/mcp/registry.py`
- `core/policy_registry.py`
- 相关 MCP 测试文件

本批原则：

- 短期保留 bridge
- 中期把桥降为薄适配层

验收标准：

- registry 层理解 deferred schema
- MCP 不再主要靠 legacy proxy 挂接

### Batch 9：legacy inventory + examples 清理

目标：

- 把历史遗留路径做成可删除清单，而不是无限保留

建议文件：

- `executor/examples.py`
- `entry/chat.py`
- `tools/shell_tool.py`
- `agent/core.py`
- 其他 legacy/fallback 明显驻留点

本批原则：

- 每个 fallback 都写清楚“谁在用、为何保留、何时删除”
- 没有调用价值的优先删

验收标准：

- 仓库里不再存在来源不明的 fallback

### Batch 10：chat-mode / skill fork / subagent 统一评估专项

目标：

- 回头评估 `chat.py` 自己那套 fork 语义是否要并入统一 spawn service

建议文件：

- `entry/chat.py`
- `agent/session/task_tool.py`
- `agent/session/runtime.py`
- `agent/session/agent_factory.py`

本批原则：

- 这批放到最后
- 只在前面主链稳定后再做

验收标准：

- 不再存在第三套 subagent 语义继续长大

---

## 推荐执行顺序

如果我们按“低风险、先收口、再重构”的方式推进，我建议顺序如下：

1. Batch 1：`agent.v2` shim 收口
2. Batch 2：主入口 import 迁移
3. Batch 3：Skill modifier 语义修正
4. Batch 4：Plan / approval 双轨收口
5. Batch 5：subagent contract 减重
6. Batch 6：`agent/core.py` 拆职责
7. Batch 7：shell + process adapter
8. Batch 8：MCP registry 一等公民化
9. Batch 9：legacy inventory + examples
10. Batch 10：chat-mode fork 统一评估

---

## 我的最终建议

如果我们要继续保持“全局一致，不打补丁式修修补补”的原则，那么接下来最合理的做法不是直接散点改代码，而是：

- 以这份文档为唯一整改基线
- 从 Batch 1 开始按批推进
- 每批结束都复核：是否让架构更单轨、更声明式、更 typed、更接近 Claude Code 的语义

当前最适合立刻开工的是：

- Batch 1
- Batch 2
- Batch 3

因为这三批会直接决定后续所有整改，是不是建立在一个稳定的 canonical 架构之上。
