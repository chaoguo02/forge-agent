# Codebase Elegance Audit

本文件记录当前代码库里“能工作，但实现不够优雅、容易继续积累复杂度”的位置，目的是给后续治理提供统一入口。这里强调的是架构表达、分层一致性、维护成本和行为闭环，不等同于所有条目都是立刻会炸的功能缺陷。

## 总体判断

当前仓库的总体方向并没有走偏，尤其是在项目级隔离、状态外置、工具元数据化、Git facts 等方面已经有了比较好的骨架。但代码库存在比较明显的“过渡层滞留”现象：

- 旧命名空间与新命名空间长期并存，真正的单一事实源还没有收口。
- 一些 Claude Code 对齐能力已经“在注释和字段里存在”，但运行闭环并没有完全统一到同一条主链。
- 个别模块已经从“业务代码”演变成“兼容逻辑 + 提示工程 + 编排逻辑 + 回退逻辑”的复合体，继续叠补丁会越来越难维护。

## 重点问题

### 1. 源码里存在明显的编码污染，和“Runtime 吞掉脏活、LLM 只看干净 UTF-8”的原则相矛盾

- 位置：
  - [llm/openai_backend.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/llm/openai_backend.py:4)
  - [executor/process.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/process.py:1)
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:1)
- 现象：大量注释和文档字符串已经出现 mojibake（如 `鈥?`、`鍛戒护` 一类乱码）。
- 为什么不优雅：这会让“代码本身就是事实源”这件事打折扣，后续阅读、审计、prompt 拼接、文档输出都会被污染。
- 建议方向：把编码问题当成一类基础设施治理项，统一做 UTF-8 正规化，不要继续在乱码文件上追加逻辑。

### 2. `agent.v2` 与 `agent.session` 双命名空间长期并存，单一事实源还没真正收口

- 位置：
  - [agent/v2/runtime.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/v2/runtime.py:1)
  - [agent/v2/task_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/v2/task_tool.py:1)
  - [agent/v2/subagent.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/v2/subagent.py:1)
  - [agent/v2/mcp_integration.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/v2/mcp_integration.py:1)
- 现象：`agent.v2` 大量文件只是 `from agent.session.xxx import *` 的重导出层。
- 为什么不优雅：这会制造“看似有两套实现、实际上是一套实现加一层镜像”的认知负担，还容易出现私有符号、IDE 跳转、测试引用和真实实现脱节的问题。
- 建议方向：明确兼容层生命周期。要么把所有调用点收口到 `agent.session`，要么为 `agent.v2` 只保留极薄的显式兼容 API，而不是整文件 `import *`。

### 3. 上层入口仍大量依赖兼容命名空间，说明迁移没有真正完成

- 位置：
  - [entry/chat.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:82)
  - [entry/chat.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:134)
  - [entry/modes/v2_runner.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/modes/v2_runner.py:26)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:81)
- 现象：主入口、交互层、核心循环依然在直接 import `agent.v2.*`。
- 为什么不优雅：这意味着底层虽然已迁到 `agent.session`，但执行主链的心理模型仍停留在旧层，后续治理时会不断遇到“到底该改哪边”的分叉。
- 建议方向：把入口层的 import 全部收口到 canonical namespace，再决定兼容层是否继续存在。

### 4. Plan 目前实际上有两套机制，职责边界不够干净

- 位置：
  - [tools/plan_mode_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/plan_mode_tool.py:1)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1215)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1608)
  - [entry/modes/v2_runner.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/modes/v2_runner.py:375)
- 现象：一边有 `EnterPlanMode` / `ExitPlanMode` 这种“会话内切模式”的思路，一边 `v2_runner.py` 又维护了一整套外部 plan 工作流和审批循环。
- 为什么不优雅：同一个概念出现两条路径，意味着后续很容易出现行为不一致、一个修了另一个没修、测试覆盖也被稀释。
- 建议方向：明确 Plan 到底是“正交 permission mode”还是“单独工作流”。建议只保留一条主链，另一条退化为兼容层。

### 5. Plan 审批通过后递归进入新的 build 流程，语义上像“新开一轮”而不是“同会话切模式”

- 位置：
  - [entry/modes/v2_runner.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/modes/v2_runner.py:457)
- 现象：审批通过后调用 `run_v2_mode(...)` 重新走 build。
- 为什么不优雅：这让 Plan 和 Build 更像两个串联工作流，而不是同一 session 的 mode transition；上下文连续性、可观察性和调试心智都会变差。
- 建议方向：让 plan acceptance 变成同一 session 的显式状态流转，而不是递归重入 runner。

### 6. Mode switch 通过 registry 内部的 `_pending_mode_switch` 旗标传递，属于脆弱的隐式耦合

- 位置：
  - [tools/plan_mode_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/plan_mode_tool.py:22)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1608)
- 现象：tool 直接写 registry 私有字段，主循环再去读这个私有字段完成模式切换。
- 为什么不优雅：这是典型的“共享可变内部状态 + 约定式副作用”，既不强类型，也不利于后续替换 registry/policy 实现。
- 建议方向：把 mode switch 建模成显式运行时事件或 typed control result，而不是偷偷写对象内部字段。

### 7. Skill 的 `context: fork` 仍绕开 SessionRuntime，自己在 `chat.py` 里手搓子代理执行

- 位置：
  - [entry/chat.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:445)
  - [entry/chat.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:503)
- 现象：`_run_skill_fork()` 直接 rebuild agent、直接创建 `Task`、直接开 `EventLog`、直接 `fork_agent.run(...)`。
- 为什么不优雅：subagent 的正式能力明明已经有 `SessionRuntime`、session store、spawn contract、notification、resume 等完整基础设施，这里却另起了一条“平行子代理链路”。
- 影响：权限、session 持久化、事件、worktree、resume、统一审计都容易和正式 subagent 主链脱节。
- 建议方向：所有 fork 型 skill 都应收敛到 `SessionRuntime.spawn_agent(...)` 这条主链。

### 8. Skill 限制是“事后修改 policy”，实现方式比较别扭

- 位置：
  - [skills/tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/skills/tool.py:125)
  - [core/policy_registry.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/core/policy_registry.py:192)
  - [core/policy_registry.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/core/policy_registry.py:198)
- 现象：`Skill` tool 先返回 metadata，再由 `PolicyAwareToolRegistry` 消费 `skill_modifier`，并通过重建 policy 的方式修改当前行为。
- 为什么不优雅：这不是“声明式预装载上下文”，而是“工具执行后回写策略”；而且 `allowed_tools`、`disallowed_tools`、model、effort、context 这些字段并没有形成统一的 typed activation 生命周期。
- 建议方向：把 skill activation 变成运行时显式状态，而不是 tool result metadata 的后处理。

### 9. Subagent 行为协议被硬编码成超长 prompt 常量，提示层过重

- 位置：
  - [agent/session/task_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:42)
- 现象：`_SUBAGENT_PROTOCOL` 把反偷懒规则、报告格式、分析流程、已知设计决策都塞进了源码常量。
- 为什么不优雅：这让 subagent 的稳定性过度依赖 prompt 文案，而不是 runtime contract、tool schema、completion requirement、typed result。
- 建议方向：能下沉到 contract/schema/runtime 的约束尽量下沉；保留 prompt，但不要让 prompt 承担主约束层。

### 10. `agent/core.py` 职责过重，已经接近“巨石 orchestrator”

- 位置：
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1215)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1419)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1458)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1498)
  - [agent/core.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1608)
- 现象：同一个类里混合了主循环、工具结果写回、plan mode 切换、reflection、missing-test 守卫、summary 抽取、context compaction 恢复、memory stale 标记等多类职责。
- 为什么不优雅：每次修一个行为都要穿过巨大上下文，局部变更很容易产生意外耦合。
- 建议方向：继续把“决策状态机”“history/materialization”“completion/guard”“mode transition”“reflection policy”拆成可组合组件。

### 11. Shell 工具仍维持双协议：参数化执行 + legacy `cmd` 字符串执行

- 位置：
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:25)
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:99)
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:158)
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:192)
- 现象：对外 schema 既支持 `command + args`，又支持 deprecated `cmd`；内部还保留字符串模式的阻断逻辑。
- 为什么不优雅：这会让 Runtime 的“参数隔离、shell=False”原则一直被 legacy 路径稀释。
- 建议方向：给 legacy `cmd` 一个清晰退场计划，最终只保留参数化执行。

### 12. Shell 安全底线仍有一部分是字符串黑名单，而不是统一声明式策略

- 位置：
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:25)
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:230)
- 现象：`_BLOCKED_PATTERNS` 和 `_check_blocked()` 仍是基于字符串匹配的命令黑名单。
- 为什么不优雅：这类规则很难完备，而且和 “PhasePolicy / PermissionPipeline / Runtime 事实层” 的声明式思路不统一。
- 建议方向：保留极小的终极保险丝可以接受，但不要继续扩张；真正的授权应尽量由 permission rules、tool metadata、runtime scope 负责。

### 13. Runtime 抽象已经建立，但仍存在多处直接 `subprocess.run(...)` 的散落执行

- 位置：
  - [executor/process.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/process.py:214)
  - [executor/project_environment.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/project_environment.py:132)
  - [executor/workspace_facts.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/workspace_facts.py:144)
- 现象：除了 Runtime 本体，环境探测和 workspace facts 里仍各自直接执行子进程。
- 为什么不优雅：这让“进程执行的唯一控制面”没有完全成立，日志、编码、超时、错误分类、平台处理会分散。
- 说明：`workspace_facts.py` 这种纯事实采集模块保留直调 git 是可以理解的，但它至少说明“进程策略”现在还不是单点。
- 建议方向：区分“Runtime 用户工具执行”和“系统内部事实采集”两类执行，并明确是否共用统一执行适配层。

### 14. MCP 集成仍停留在“runtime tool 代理回 legacy tool”的半桥接状态

- 位置：
  - [agent/session/mcp_integration.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/mcp_integration.py:17)
  - [agent/session/mcp_integration.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/mcp_integration.py:119)
  - [agent/session/mcp_integration.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/mcp_integration.py:170)
- 现象：`MCPRuntimeToolProxy` 把 runtime MCP tool 再包一层适配成 legacy `BaseTool`。
- 为什么不优雅：这意味着 MCP 还没有真正变成系统的一等公民，而是在新旧工具体系之间做桥接。
- 建议方向：长期看应让 MCP tool 直接进入统一 tool contract，而不是长期维护 proxy 双形态。

### 15. MCP 的 deferred schema 能力只存在于 executor 层，核心 registry 还没有吃透

- 位置：
  - [executor/mcp/registry.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/mcp/registry.py:46)
  - [core/base.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/core/base.py:715)
  - [core/policy_registry.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/core/policy_registry.py:171)
- 现象：executor 层已经能给 schema 标 `defer_loading`，但核心 registry 的 `get_schemas()` 仍只是普通 `tool.to_llm_schema()` 列表。
- 为什么不优雅：这类“能力在底层存在、但主链没接上”的情况最容易导致我们误以为“系统已经支持了”。
- 建议方向：把 tool schema 生产的唯一事实源收敛到一处，避免 executor 和 core 各自定义一遍 schema 语义。

### 16. 工具名兼容依赖硬编码别名表，属于必要但应收敛的过渡债务

- 位置：
  - [agent/session/agent_registry.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/agent_registry.py:16)
- 现象：旧工具名到新工具名的兼容映射写死在 `_TOOL_ALIASES` 中。
- 为什么不优雅：少量兼容映射可以接受，但如果长期扩张，就会让“声明式工具元数据”与“隐藏别名魔法”并存。
- 建议方向：把兼容窗口定死，逐步迁移 agent 定义和测试，最后收紧别名表。

### 17. 代码库里残留较多“legacy / fallback / backward compat”路径，说明收口阶段还没完成

- 位置：
  - [tools/shell_tool.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/tools/shell_tool.py:101)
  - [executor/query_loop.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/query_loop.py:224)
  - [core/base.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/core/base.py:602)
  - [agent/session/runtime.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1599)
- 现象：仓库里有大量 `legacy`、`fallback`、`backward compat` 路径和注释。
- 为什么不优雅：兼容本身没问题，但当它成为多数主链都要经过的常态时，系统会越来越难解释。
- 建议方向：为每类兼容路径定义“保留原因、退出条件、退出顺序”，否则它们会永久化。

### 18. 有示例/边角代码已经和现有目录职责脱节

- 位置：
  - [executor/examples.py](/abs/path/D:/StudyProjects/ProjectBench/forge-agent/executor/examples.py:7)
- 现象：示例文件还在 `from runtime import ...`，与当前目录结构不一致。
- 为什么不优雅：虽然不一定影响主业务，但会持续给新读代码的人错误心智模型。
- 建议方向：把示例也视为产品界面的一部分，迁到当前 canonical API，或者明确标记为历史草稿。

## 优先治理顺序

如果后续要系统整治，建议优先处理下面几组，因为它们最容易影响全局一致性：

1. 编码污染与 canonical namespace 收口。
2. Plan 主链统一，去掉双轨机制。
3. Skill fork 收敛到 SessionRuntime 主链。
4. `agent/core.py` 继续拆职责，减少巨石编排。
5. Shell legacy 路径和字符串黑名单收缩。
6. MCP schema / tool registration 真正接到核心 registry 主链。

## 不建议现在过度处理的点

下面这些属于“知道它不够优雅，但不值得立刻大动”的部分：

- 少量工具别名兼容，只要范围不继续膨胀，可以暂留。
- `workspace_facts.py` 这类事实采集模块内部直接调 git，不一定非要强行套进用户态 Runtime，只要职责边界讲清楚即可。
- 兼容层不是不能存在，问题在于它现在已经影响主链认知；如果收口后只剩薄适配层，就不算大问题。

## 结论

当前代码库最需要的不是继续“局部补丁式修正”，而是继续做“主链收口”：

- 一个 canonical namespace
- 一条 plan 主链
- 一条 subagent 主链
- 一条 skill fork 主链
- 一套 tool schema / permission / runtime 事实源

只要这几个主轴收口，很多今天看起来分散的不优雅实现会自然消失。
