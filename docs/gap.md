总体结论
当前架构已经从“大量散落逻辑”演进为较清晰的四层结构：
entry/                 CLI、Chat、Plan 审批
    ↓
agent/session/         会话、Agent 定义、Subagent 编排
    ↓
agent/core.py          ReAct 主循环与完成判定
    ↓
core/ + executor/      工具策略、进程、MCP、工作区事实
方向整体正确，尤其是：
agent/session/ 成为会话编排中心。
core/ 与 executor/ 职责比以前清晰。
Subagent 已有持久化会话、深度、Fork、Worktree、后台通知。
Plan 已能“只保存不执行”。
状态路径位于项目 Git 树外。
工具权限和状态逐步转为类型化。
但目前仍处于“骨架正确，部分链路没有真正闭环”的阶段。最严重的问题不是缺少高级功能，而是若干代码“注释声称已对齐 Claude Code”，实际执行链没有接通。
本次最终审计基线是提交 9d3d1d7。审计过程中仓库从 ca0851b 又推进了 M1/M2 两个 MCP 提交，因此以下结论已经按最新 HEAD 重新核对。
0. 当前仓库的前置 P0：目录迁移尚未闭环
最近把 agent/v2/ 迁移为 agent/session/、runtime/ 迁移为 executor/，方向合理，但兼容层已经破坏测试入口。
例如 [agent/v2/task_tool.py (line 1)](/D:/StudyProjects/ProjectBench/forge-agent/agent/v2/task_tool.py:1) 使用：
from agent.session.task_tool import *
星号导入不会转发 _format_fork_result，而核心测试仍从旧路径导入它，导致 tests/test_v2_runtime.py 在收集阶段直接失败。
另外 3 个 MCP 测试仍 monkeypatch 已不存在的 runtime.*，产生：
ModuleNotFoundError: No module named 'runtime'
验证事实：
核心 V2 测试：收集失败。
其余 MCP、Plan、Skill 对齐测试：绝大部分通过。
另有 3 个 MCP 测试因旧模块路径失败。
这意味着当前不能把“已有测试多数通过”等价为“五条架构链路可用”。应先完成迁移闭环，否则后续重构的回归信号不可信。
1. ReAct 层
Claude Code 的思想
Claude Code 的核心循环非常简单：
输入系统提示、历史和工具定义。
模型生成文本或工具调用。
Runtime 执行工具并返回结果。
重复，直到模型返回不含工具调用的最终消息。
返回结果、用量和会话 ID。
工具权限、Hooks、预算、上下文压缩是循环外侧的 Runtime 控制面，而不是让模型输出特定字符串来驱动。Claude Code Agent Loop
我们做得正确的部分
[agent/core.py (line 419)](/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:419) 已把逐步约束交给 RuntimeController。
工具调用、观察、消息配对和并行执行链基本成立。
TaskStateMachine 使用 Enum，而不是用自然语言判断生命周期。
Completion Guard 使用 Git workspace delta 作为编辑事实源。
Hook 可以在完成前阻止停止。
Context Manager、Artifact 和压缩已经独立成模块。
OpenAI/Anthropic 原生 tool call 最终都会映射为统一 Action。
其中 Git Diff 完成事实是比 Claude Code 更严格的合理差异，符合本项目“客观事实源”原则，应保留。
差距
R1 — P0：非原生工具调用路径仍依赖文本关键词
[llm/openai_backend.py (line 393)](/D:/StudyProjects/ProjectBench/forge-agent/llm/openai_backend.py:393) 定义了：
_FINISH_KEYWORDS = (...)
_GIVE_UP_KEYWORDS = (...)
随后根据回答是否包含 "task complete"、"unable to" 等文本决定成功或放弃；无法识别时直接转为 GIVE_UP。
这正是核心原则禁止的字符串启发式。它会导致：
合法最终回答因为没有特定关键词而被判定失败。
正文偶然出现 “unable to” 被误判放弃。
不同模型、语言和表达方式产生不同生命周期结果。
Plan 模式尤其容易“生成了计划，但 Runtime 认为 gave_up”。
正确方向：Provider 边界只根据协议事实判断：
有 tool calls → 执行工具。
正常 stop 且无 tool calls → 最终回答。
Provider 明确错误/截断 → 类型化失败。
永远不解析回答语义来选择状态。
R2 — P1：生命周期控制存在三套重叠机制
当前同时存在：
RuntimeController
TaskStateMachine
ReActAgent._run_body() 内联终止逻辑
连续工具失败就至少在这些位置重复处理：
[agent/runtime_controller.py (line 226)](/D:/StudyProjects/ProjectBench/forge-agent/agent/runtime_controller.py:226)
[agent/session/task_state_machine.py (line 183)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_state_machine.py:183)
[agent/core.py (line 1215)](/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1215)
部分 Guard 还是空壳，注释明确说明“实际检查在 _run_body()”。
这属于过度设计：抽象存在，但事实源仍在主循环里。建议只保留：
一个状态机负责合法状态迁移。
一个 Runtime 决策器负责返回类型化下一步。
Guard 必须真正被统一调用，不能再有“注册了但实际不生效”的占位 Guard。
R3 — P1：Compaction 仍通过文本前缀识别内部消息
[context/compaction.py (line 239)](/D:/StudyProjects/ProjectBench/forge-agent/context/compaction.py:239) 通过：
content.startswith("[Conversation compacted")
识别压缩块，另有 "rejected" in content.lower() 等文本语义判断。
正确方向是给 LLMMessage 增加类型化消息种类，例如：
MessageKind.COMPACTION_BOUNDARY
MessageKind.RUNTIME_NOTICE
MessageKind.TOOL_RESULT
展示文本只用于呈现，不能反向决定控制流。
R4 — P1：所有 Subagent 都关闭压缩
[agent/core.py (line 1514)](/D:/StudyProjects/ProjectBench/forge-agent/agent/core.py:1514) 使用 compact_history=False 判断 Subagent，并完全跳过压缩。
短任务没问题，但长时间测试、日志处理和嵌套 Agent 很容易耗尽上下文。Claude Code 的 Subagent 是独立上下文，不等于“禁止压缩”。
2. Plan 层
Claude Code 的思想
Plan 是一种正交的 Permission Mode：
允许读取文件和执行只读探索命令。
禁止源代码编辑。
模型将计划写入计划文件。
调用 ExitPlanMode 把计划交给用户审批。
审批后在同一会话退出 Plan Mode，切换到用户选择的权限模式。
可以保留规划上下文，也可以由用户选择清空。
Claude Code 不要求计划必须包含框架自定义 JSON 合同。Plan Mode、Tools Reference
我们做得正确的部分
Plan Agent 是只读权限。
Plan 文件放在项目 Git 树外。
文件名使用任务摘要哈希，稳定且不会泄露原始任务。
SAVE 和 EXECUTE 是不同的强类型审批动作。
用户选择保存时不会执行。
只有验证成功的计划才覆盖磁盘计划。
审批 UI 与状态服务已经分离。
差距
P1 — P0：EnterPlanMode/ExitPlanMode 是未接通的“装饰性实现”
[tools/plan_mode_tool.py (line 19)](/D:/StudyProjects/ProjectBench/forge-agent/tools/plan_mode_tool.py:19) 向 registry 写入：
registry._pending_mode_switch = ...
但整个项目没有任何主循环代码读取 _pending_mode_switch。
同时内置 Build/Plan 工具集合也没有声明 EnterPlanMode 或 ExitPlanMode。因此这两个工具：
虽然被注册到基础 registry；
实际 Agent 看不到；
即使自定义 Agent 看到了，调用后也不会真正切换模式。
这是典型的“接口存在，任务流不存在”。
P2 — P0/P1：Plan 被强制绑定到六字段 JSON 合同
[entry/modes/v2_runner.py (line 419)](/D:/StudyProjects/ProjectBench/forge-agent/entry/modes/v2_runner.py:419) 对计划强制执行：
JSON 提取；
Pydantic 校验；
两轮修复；
再渲染为 Markdown。
这正是之前 Plan 消耗预算却迟迟不能展示计划的重要原因之一。
JSON 合同本身并非错误，但它不应成为“用户看到计划”的前置条件。Claude Code 的事实契约是“Plan 文件 + 审批状态”，不是某个固定 JSON schema。
建议：
Markdown 计划始终可以保存和展示。
可选执行元数据由 Runtime 生成，而不是要求 LLM 重复输出。
target_files 不应成为所有计划的必填项；大型重构在探索阶段可能无法穷举。
校验失败不应吞掉已经可读的计划。
P3 — P1：审批后创建了新 Build 根会话
[entry/modes/v2_runner.py (line 533)](/D:/StudyProjects/ProjectBench/forge-agent/entry/modes/v2_runner.py:533) 审批后递归调用 run_v2_mode(agent_name="build")，重新创建根会话。
这与 Claude Code 的“同一会话退出 Plan Mode”不同，导致：
规划期间读取的事实丢失。
Subagent 结果和工具历史不能自然延续。
只能重新注入计划文档。
Session DB 出现 Plan 根会话和 Build 根会话两套身份。
用户反馈和审批历史割裂。
正确方向：同一个 SessionRecord 发生类型化权限模式转换：
PLAN/EXPLORING
    → PLAN/AWAITING_APPROVAL
    → BUILD/EXECUTING
是否清空历史应是审批选项，不应通过重新建 Session 隐式实现。
P4 — P1：Plan Agent 缺少只读 Shell 探索能力
内置 _DEFAULT_READONLY_TOOLS 没有 Bash。Claude Code Plan Mode 可以运行读取性质的 Shell 命令，具体权限仍由策略层判断。
我们的做法更安全，但降低了：
项目结构探测；
构建配置读取；
git log、git grep、依赖命令查询；
只读测试收集。
更合理的是让 Shell 可见，然后由 Runtime 根据命令效果和 Permission Mode 判定，而不是物理删除整个 Shell 能力。
3. Subagent 层
Claude Code 的思想
当前 Claude Code Subagent 契约包括：
> Status: this file contains historical gap notes.
> For current Subagent truth, prefer `docs/subagent-comparison.md` and
> `docs/v2-react-architecture.md`.

具名 Subagent 默认 fresh context。
Fork 继承父上下文。
Subagent 默认后台运行，需要结果时才前台。
后台权限请求上浮主会话并标明 Agent。
最大嵌套深度 5，恢复后深度不变。
Fork 不能继续 Fork。
只有顶层 Subagent 的最终摘要返回主会话。
Subagent 可预加载 Skills、声明 MCP Servers、Hooks、权限模式和 Worktree 隔离。Subagents
我们做得正确的部分
这是目前最接近 Claude Code 的一层：
AgentSpawnRequest 将身份、上下文来源、执行位置、工作区模式正交化。
具名 Agent fresh context、Fork parent snapshot 已实现。
最大深度 5 并持久化。
Fork→Fork 被禁止。
会话消息、结果、generation 和通知持久化。
前台、后台、等待、取消、恢复均有类型化返回值。
Worktree 隔离和 Git 证据保留已经建立。
Parent 只接收结构化结果/摘要。
Agent 工具可由具名 Agent 声明并进行嵌套委派。
差距
S1 — P0：子 Agent 权限模式会修改共享 PermissionPipeline
[agent/session/runtime.py (line 886)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:886) 直接执行：
self._base_registry._permission_pipeline.set_permission_mode(...)
这是共享对象。并行 Subagent 会产生：
一个子 Agent 改变另一个子 Agent 的权限。
子 Agent 改变主 Agent 后续权限。
后台 Agent 完成后权限模式没有可靠恢复。
一对多 fan-out 存在竞态。
这违反项目级隔离和 Context Object 原则。
正确方向：每个 Session 创建不可变或派生的 PermissionContext，Registry 绑定该 Context，不修改基础 registry。
S2 — P0：后台 Subagent 的 Agent-scoped Hooks/MCP 没有清理
前台路径在 finally 中注销 Hooks、断开 MCP；后台路径直接进入 _start_background_execution()，没有传递清理回调。
相关位置：
注册：[agent/session/runtime.py (line 894)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:894)
前台清理：[agent/session/runtime.py (line 915)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:915)
后台执行：[agent/session/runtime.py (line 1071)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/runtime.py:1071)
结果是后台 Agent 的 Hook/MCP 生命周期泄漏到后续会话。
S3 — P1：默认仍是前台，与当前 Claude Code 默认不同
[agent/session/task_tool.py (line 325)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/task_tool.py:325) 在未提供参数时默认：
ExecutionPlacement.FOREGROUND
Claude Code 从 v2.1.198 起默认后台，只在父 Agent 必须等待结果时前台。
不应简单把默认值改成后台。更合理的声明式方式是保留 AUTO 到 Runtime，然后由依赖事实决定：
本轮后续逻辑依赖结果 → foreground。
独立调查、审查、并行验证 → background。
显式用户要求优先。
S4 — P1：Subagent frontmatter 的 Skills/Memory 没进入真实子执行链
runtime_prompt_builder.py 支持预加载 Skills 和 Memory，但它只在根 run_session() 路径调用。
真正的 run_child_agent() 使用自己的 _build_system_messages()，没有调用 Runtime Prompt Builder。因此：
skills: 字段解析成功，但具名子 Agent 启动时不加载。
memory: 字段同样失效。
测试若只检查 parser，会误判为已经实现。
S5 — P1：Agent-scoped Hook 注册在全局共享 Registry
_register_agent_hooks() 直接修改 dispatcher 内部全局 registry。多个同类型并发 Agent 会共享、重复和相互注销 Hook。
应将 Hook 集合绑定到 Session/Agent Execution Context，而不是动态修改全局集合。
4. MCP 层
Claude Code 的思想
当前 Claude Code MCP 主要特征：
支持 stdio、HTTP、SSE、WebSocket。
项目、用户、企业托管等配置作用域。
默认后台连接。
HTTP/SSE 自动重连。
支持工具、Resources、Prompts、动态 list_changed。
默认使用 Tool Search，工具 schema 按需进入上下文。
alwaysLoad 可声明例外。
支持 OAuth、Elicitation、交互注解和 Channels。
MCP 大输出有告警和上限。Claude Code MCP
我们做得正确的部分
四种 transport 已存在。
独立 executor/mcp/ 层方向正确。
自动重连已设为最多 5 次指数退避。
Resources list/read 工具已接入 manager。
MCP 工具名称规范为 mcp__server__tool。
工具错误可转换成结构化失败。
项目和用户级配置已经开始支持。
MCPToolProps 正在取代散落的动态属性。
HTTP Content-Type 验证已加入。
SSE tools/list_changed 能被解析。
差距
M1 — P0：新实现的 Agent-scoped MCP 仍未真正进入子 Agent 工具池
目前至少有三处断点：
[agent/session/mcp_integration.py (line 103)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/mcp_integration.py:103) 的 server_tools 按 server__tool 前缀匹配，但实际名称是 mcp__server__tool。

connect_agent_servers() 只把新 Proxy 放进 MCPToolIntegration._tools，没有注册进 SessionRuntime._base_registry。

子 Agent Registry 最终从 base_registry.filtered(...) 选工具。因此即使名字计算正确，新连接的工具也不存在于被过滤的基础池中。

也就是说 M1 的单元连接生命周期可能通过，但端到端 Agent 调用仍不可用。
M2 — P0：Tool Search 只有展示文本，没有完成 schema 注入
项目中有两条互不相连的实现：
[executor/mcp/registry.py (line 46)](/D:/StudyProjects/ProjectBench/forge-agent/executor/mcp/registry.py:46) 能生成带 defer_loading 的 API schema。
[core/base.py (line 737)](/D:/StudyProjects/ProjectBench/forge-agent/core/base.py:737) 的真实 Agent schema 路径完全不调用它。
与此同时 [tools/workflow_tool.py (line 130)](/D:/StudyProjects/ProjectBench/forge-agent/tools/workflow_tool.py:130) 的 ToolSearch 只返回匹配工具的名称和描述，没有：
把完整 schema 加入后续模型请求；
返回 Anthropic tool_reference；
更新当前 Registry 可见集合。
因此现在既不是 Claude 原生 deferred schema，也不是可靠的自研按需加载。大多数 MCP schema 仍可能在请求开始时全部进入上下文。
M3 — P0/P1：Agent-scoped disconnect 实现存在直接错误
[agent/session/mcp_integration.py (line 198)](/D:/StudyProjects/ProjectBench/forge-agent/agent/session/mcp_integration.py:198) 中：
sn in getattr(rt, "mcp_props", None)
MCPToolProps 是 dataclass，不是可迭代容器。
随后：
t.server_name
全局 MCP Proxy 初始化时没有统一设置 server_name 属性。
这会让清理路径产生 TypeError 或 AttributeError。
M4 — P1：动态工具刷新没有接到上层 Registry
Bridge 的 _on_list_changed() 可以调用 callback，但 Sync Manager 没有为初始 bridge 注册 set_tools_changed_callback()。
即使 bridge 刷新成功：
manager tool map 不一定刷新；
integration Proxy 列表不刷新；
Session Registry 更不会刷新。
所以当前是“解析了 notification”，不是“动态更新已经实现”。
M5 — P1：WaitForMcpServers 实际不等待
工具只是读取当前连接状态并返回 “retry later”，没有等待、事件订阅或超时阻塞逻辑。
此外 initialize() 仍同步连接全部服务，与 Claude Code 的后台连接模型不同。
M6 — P2：功能面差距
当前尚缺：
MCP Prompts 的真实发现和执行；CLI 读取 _prompts，但 manager 没有生产它。
OAuth 认证和安全 token 存储。
Elicitation。
Channels。
企业托管配置。
alwaysLoad 配置端到端语义。
> Status update (2026-07-17): this gap report includes historical findings. Several former P0/P1 items in the Skills/Subagent/MCP area have already been converged:
> - `allowed-tools` / `disallowed-tools` semantics are now applied through the policy pipeline as pre-approval + deny rules.
> - `context: fork` no longer uses an ad hoc child path; it goes through the unified `SessionRuntime` spawn flow.
> - agent-scoped MCP lifecycle hooks (`connect_agent_servers()` / `disconnect_agent_servers()`) now exist; remaining MCP debt is mainly around deeper contract cleanup and first-class schema flow.
> Keep using this file as a historical comparison ledger, but verify current code before treating a listed item as still-open.

MCP 输出 10k 警告/25k 默认上限。
这些不应该一次性全做。优先级应低于 Tool Search、Agent-scoped 生命周期和 Registry 闭环。
5. Skill 层
Claude Code 的思想
Claude Code Skills 遵循渐进披露：
平时只把名称和描述放入上下文。
用户 /skill-name 或模型通过 Skill 工具调用后，才加载完整正文。
正文作为一条消息留在会话中。
Compaction 后重新附加最近调用的 Skills。
context: fork 使用 fresh Subagent，不继承主对话。
allowed-tools 是临时预批准，不是工具白名单。
项目 Skill 的动态 Shell 注入受 workspace trust 和策略控制。
Subagent 的 skills: 字段在启动时预加载完整正文。Claude Code Skills
我们做得正确的部分
SKILL.md Registry 和 Frontmatter 解析较完整。
支持 disable-model-invocation、user-invocable。
支持 $ARGUMENTS 等替换。
支持 supporting files 描述。
模型平时只看到 Skill metadata。
有直接 /skill-name 和模型 Skill 工具两条入口。
已解析 context: fork、agent、model、effort、allowed/disallowed tools。
已有 live refresh 基础。
差距
K1 — P0：用户直接 /skill-name 当前会调用不存在的方法
[entry/chat.py (line 425)](/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:425) 调用：
self._skill_registry._get_skill_meta(name)
但 Registry 只有公开的 get_skill_meta()。
因此直接调用 Skill 会在真正渲染前抛 AttributeError。
K2 — P0：动态 Shell 注入绕过 Runtime 和权限系统
[skills/registry.py (line 400)](/D:/StudyProjects/ProjectBench/forge-agent/skills/registry.py:400) 直接使用：
subprocess.run(..., shell=True, cwd=skill_dir)
这绕过了：
Runtime 编码清洗；
项目绝对路径约束；
PermissionPipeline；
Hook；
Workspace trust；
项目级命令环境；
审计事件记录。
这是当前最严重的安全架构偏差之一。项目 Skill 一旦被模型自动加载，就可能执行任意 Shell。
正确方向：Skill 渲染器只能产生 DynamicContextRequest；Runtime 在权限和项目 Context 下执行，再把 UTF-8 结果交回渲染器。
K3 — P0：SkillContextModifier 有消费者，没有生产者
[core/policy_registry.py (line 191)](/D:/StudyProjects/ProjectBench/forge-agent/core/policy_registry.py:191) 等待：
result.metadata["skill_modifier"]
但 [skills/tool.py (line 125)](/D:/StudyProjects/ProjectBench/forge-agent/skills/tool.py:125) 返回的 ToolResult 没有 metadata，也没有创建 SkillContextModifier。
因此以下字段在模型调用 Skill 时全部无效：
allowed-tools
disallowed-tools
model
effort
context: fork
K4 — P0：context:fork 实现与官方语义相反且代码本身不可用
[entry/chat.py (line 464)](/D:/StudyProjects/ProjectBench/forge-agent/entry/chat.py:464) 明确把主对话历史赋给 fork Agent：
fork_agent._pending_history = self._shared_history
而官方 context: fork 是 fresh context，不应看到主对话。
结果返回部分又尝试构造：
type(fork_agent).__new__(type(fork_agent)).__class__(
    role="assistant", content=result.summary
)
这实际是在用 ReActAgent 类接收 role/content，不是构造 LLMMessage，极可能在 Agent 已执行完后抛异常并打印 “fork failed”。
此外这个路径：
绕过 SessionRuntime.spawn_agent()；
没有 Session DB；
没有 Agent 深度；
没有后台状态；
没有取消和通知；
没有正确 Worktree/权限继承。
正确方向：Skill fork 必须转换成普通 AgentSpawnRequest.named()，复用唯一 Subagent 流程，不能维护第二套 fork 实现。
K5 — P1：allowed-tools 语义实现反了
[core/policy_registry.py (line 67)](/D:/StudyProjects/ProjectBench/forge-agent/core/policy_registry.py:67) 把 allowed-tools 传给 with_allowed_tools()，实际是缩小可用工具集合。
Claude Code 的 allowed-tools 是免审批授权，不是限制工具集合。真正限制工具的是 disallowed-tools 或权限 deny 规则。
K6 — P1：Skill 生命周期与 Compaction 不一致
当前 Buffer：
最多 3 个 Skill；
每个最多 5,000 字符，约 1,250 tokens；
LRU 淘汰。
Claude Code 是：
Skill 正文作为消息保留；
压缩后重新附加最近一次调用；
每个最多保留约 5,000 tokens；
总预算约 25,000 tokens。
我们的 Buffer 只截断工具输出，并没有与 Compactor 的重附加机制连接。Skill 很可能在压缩后丢失。
K7 — P1：Skill 标准路径不兼容
CLI 主要扫描 .forge-agent/skills/，而 Claude Code/Agent Skills 标准路径是 .claude/skills/，并支持从当前目录到仓库根、以及访问子目录时的按需发现。
可以保留 .forge-agent/skills/，但应把 .claude/skills/ 作为兼容事实源，而不是自行发明唯一目录。
综合优先级
优先级	应处理事项
P0-0	修复 agent.v2/runtime 迁移兼容层，使完整测试恢复可运行
P0-1	Skill Shell 注入全部改走 Runtime；修复直接调用与 context:fork
P0-2	打通 MCP Agent-scoped 工具池和 Tool Search schema 链
P0-3	删除文本关键词完成判断，Provider 正常 stop 即最终回答
P0-4	修复 Subagent 共享 PermissionPipeline 和后台资源泄漏
P1-1	将 Plan 改为同 Session 的正交 Permission Mode
P1-2	去掉 Plan 强制 JSON 前置门槛，保留可选类型化执行元数据
P1-3	打通 Subagent skills/memory/hooks 的 session-scoped 注入
P1-4	合并 RuntimeController、TSM 和主循环中的重复控制
P2	OAuth、Elicitation、Channels、企业 MCP、完整 Skill compaction

最终判断
项目没有“整体走错”。最有价值的基础——Runtime 事实源、强类型状态、Session 持久化、Worktree 隔离、声明式 Agent 定义——已经建立。
当前真正的问题是：
多个功能以“字段解析、类定义、注释和单元测试”的形式存在，但没有贯穿到唯一真实执行链。

下一阶段不应继续增加 Claude Code 功能数量，而应以端到端契约为单位收口：
定义被解析
  → Runtime 接收
  → 权限/上下文正确绑定
  → 模型真正可见
  → 工具真正可调用
  → 结果持久化
  → 清理与恢复成立
  → E2E 验证
在这个闭环完成前，继续添加 OAuth、Channels、更多 Hooks 或更复杂状态机只会扩大“表面实现”。
