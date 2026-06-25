# Langfuse 接入与分阶段开发方案

## 1. 目标与范围

本文定义 Forge Agent 接入 Langfuse 的完整实施方案，目标不是“增加一个日志平台”，而是把当前 agent 的执行过程转化为可观测、可分析、可回归、可迭代的工程系统。

本方案覆盖三类能力：

1. Observability：任务、LLM、工具、计划、多 Agent 链路观测
2. Prompt Management：提示词版本化、运行时拉取、回滚与灰度
3. Evaluation：打分、数据集、实验、回归基线

推荐落地顺序：

```text
Observability -> Prompt Management -> Evaluation
```

原因：

- Observability 是后两者的基础，没有 trace 就没有稳定的评估对象
- Prompt 远程化会改变运行时依赖，应该在观测打稳后再迁移
- Evaluation 需要先有足够稳定的 trace、会话、输出和开发流程

---

## 2. 接入后的能力清单

### 2.1 第一阶段可获得的能力（Observability）

- 看清一次任务的完整执行链路：用户任务、计划、LLM 调用、工具调用、最终结果
- 追踪 `react / plan / dag / multi-agent` 四种模式的行为差异
- 定位高成本、高延迟、低成功率的模型调用
- 分析失败原因：循环、反思触发、工具报错、测试失败、计划偏移
- 按 `mode / provider / model / tool / task_id / subtask_id / role` 过滤问题
- 在 chat 模式中把多轮交互串为同一 `session`
- 为 DAG / multi-agent 工作流建立更直观的 agent graph 视图

### 2.2 第二阶段可获得的能力（Prompt Management）

- 将 `prompts/` 中的提示词做版本管理
- 在不改代码的情况下切换 prompt 版本或 label
- 对比不同 prompt 版本的成本、时延、成功率
- 支持本地 prompt 与 Langfuse prompt 的混合回退

### 2.3 第三阶段可获得的能力（Evaluation）

- 给 trace、observation、session 写入质量分数
- 记录工程型指标：是否成功、是否通过测试、错误次数、反思次数
- 将失败案例沉淀为 dataset
- 比较“改 prompt / 改模型 / 改 agent 策略”前后的效果
- 后续接入 CI 回归实验

---

## 3. 本项目与 Langfuse 的结构映射

### 3.1 当前项目的关键落点

| 模块 | 作用 | Langfuse 映射 |
|---|---|---|
| `agent/core.py` | 主执行循环，调度 LLM 与工具 | 根 trace / agent observation |
| `agent/event_log.py` | 事件语义层 | trace metadata、辅助打分与回放 |
| `llm/base.py` | LLM 抽象层 | generation observation 的统一接入面 |
| `llm/openai_backend.py` | OpenAI 兼容模型调用 | generation 子观察点 |
| `llm/anthropic_backend.py` | Anthropic 模型调用 | generation 子观察点 |
| `entry/chat.py` | 多轮会话与模式切换 | session_id、user_id、round metadata |
| `agent/dag.py` | DAG 计划与子任务执行 | session 级多 trace 或父子 observation |
| `agent/multi_agent.py` | 多 Agent 调度与 worker 执行 | role / agent_id / worktree metadata |
| `agent/prompt.py` + `prompts/` | prompt 组装与模板目录 | 后续 Prompt Management 迁移落点 |

### 3.2 推荐的数据模型

#### 单次任务

- 一个 `Task.run()` 对应一个 Langfuse trace
- `task_id` 作为 trace 的主关联键
- `mode/provider/model/intent/repo_path` 作为 metadata

#### 单次 LLM 调用

- 一个 `backend.complete()` 或 `backend.stream()` 对应一个 `generation`
- 输入包含 messages、tools 摘要、模型名
- 输出包含 action、message、tool_calls、tokens、cache stats

#### 单次工具调用

- 一个 `ToolRegistry.execute_tool()` 对应一个 `tool`
- 输入为工具名和参数
- 输出为 observation 的成功/失败、截断后的结果、错误信息、耗时

#### Chat 会话

- `ChatSession` 跨轮共享一个 `session_id`
- 每一轮仍然各自有独立 trace
- 通过同一 `session_id` 在 Langfuse 中聚合回放

#### DAG / Multi-Agent

第一版不强求“所有子任务都嵌成一个超大 trace”，而使用更稳妥的方案：

- 每个子任务 / 子 agent 可有自己的 trace
- 它们共享同一个 `session_id`
- 用 `parent_task_id / subtask_id / role / layer / depends_on` 连接

这样做的原因：

- 当前 DAG 和多 Agent 实现中，子任务本来就独立创建 `Task` 与 `EventLog`
- 并发与线程隔离下，强行维护深层嵌套上下文风险更高
- session 聚合已经足够满足排障与分析目的

---

## 4. 总体架构原则

### 4.1 适配层优先，避免业务代码直接依赖 SDK

新增一个独立的 Langfuse 适配层，负责：

- 初始化 client
- 提供 no-op 回退
- 屏蔽 SDK 细节
- 集中处理 masking、flush、采样、metadata 规范

推荐新增模块：

```text
observability/
  __init__.py
  langfuse_client.py
  tracing.py
  masking.py
  models.py
```

### 4.2 默认关闭，配置齐全时开启

必须满足以下要求：

- 没配 Langfuse 凭证时，应用行为与现在完全一致
- Langfuse 网络异常不影响主流程
- flush 失败只记录 warning，不中断任务

### 4.3 以抽象层手工埋点为主，而非只包 OpenAI SDK

原因：

- 项目支持 `openai / deepseek / groq / ollama / anthropic`
- 只替换 OpenAI client 会漏掉 Anthropic 及抽象层之外的信息
- 统一在 `agent/core.py`、`llm/base.py` 和工具执行链做埋点，更完整也更稳定

### 4.4 先做观测，后做远程 prompt，最后做评估

这是最小风险路径：

- 先观察现在的系统
- 再替换 prompt 来源
- 最后基于 trace 建立评估闭环

---

## 5. 分阶段开发计划

## Stage 0：基础设施与开关

目标：把 Langfuse 作为可选能力接入项目，不影响现有默认流程。

### Step 0.1：依赖与配置

改动文件：

| 文件 | 修改内容 |
|---|---|
| `pyproject.toml` | 增加 `langfuse` 依赖，建议放入 `full` 或单独 extras |
| `.env.template` | 增加 Langfuse 凭证与开关 |
| `config/default.yaml` | 增加 `observability.langfuse` 配置节 |
| `config/schema.py` | 增加配置 dataclass 与解析逻辑 |

建议配置：

```yaml
observability:
  enabled: false
  provider: "langfuse"
  environment: "development"
  flush_on_exit: true
  capture_prompts: true
  capture_tool_outputs: true
  capture_llm_outputs: true
  mask_sensitive_data: true
  sample_rate: 1.0
  langfuse:
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
    base_url: ${LANGFUSE_BASE_URL}
```

`.env.template` 增补：

```env
LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=development
```

### Step 0.2：新增适配层

新增文件：

| 文件 | 作用 |
|---|---|
| `observability/langfuse_client.py` | 初始化 Langfuse client 或 no-op client |
| `observability/tracing.py` | trace/span/generation/tool 的统一包装 |
| `observability/masking.py` | 数据脱敏规则 |
| `observability/models.py` | 统一 metadata 结构与辅助函数 |

### Step 0.3：No-op 设计

要求：

- `get_observer()` 永远返回可调用对象
- 未启用时返回 no-op observer
- 调用方不需要写大量 `if enabled`

示意：

```python
observer = get_observer(config)
with observer.start_trace(...):
    ...
```

### 验证

- `python -m compileall config observability`
- 配置关闭时，CLI 行为与现状一致
- 配置缺失时，不抛异常

### 反思

Stage 0 成败的关键不在功能多，而在“不打扰现有系统”。如果这层设计得稳，后续阶段就能低风险推进。

---

## Stage 1：单任务观测接入（最小闭环）

目标：让一次普通 `Task.run()` 在 Langfuse 中形成完整 trace。

### Step 1.1：在 `agent/core.py` 增加任务级 trace

改动文件：

| 文件 | 修改内容 |
|---|---|
| `agent/core.py` | 在 `ReActAgent.run()` 与 `_run_body()` 包裹 trace 生命周期 |

trace 建议属性：

| 字段 | 值 |
|---|---|
| `name` | `forge-task` |
| `input` | task description、intent、repo path |
| `metadata.mode` | `react` |
| `metadata.task_id` | 当前 task id |
| `metadata.repo_path` | repo path |
| `metadata.intent` | edit / analysis |
| `metadata.max_steps` | max_steps |
| `metadata.budget_tokens` | budget_tokens |

### Step 1.2：记录任务级状态与结果

在任务完成或失败时写入：

- status
- summary
- steps_taken
- total_tokens
- patch 是否存在
- error 原因

### Step 1.3：接入短生命周期 flush

因为 CLI / 单轮 run 场景是短生命周期进程，结束前应显式 flush。

推荐位置：

- `EventLog.close()` 之后
- 或 `entry/cli.py` / `entry/chat.py` 的单轮执行末尾

### 验证

- 执行一次简单 `run` 任务后，Langfuse 中出现 trace
- 关闭配置后，本地流程不变
- Langfuse 服务不可达时，不影响任务完成

### 反思

Stage 1 不求细，只求形成第一条稳定 trace。这是后续所有工作的基线。

---

## Stage 2：LLM 调用与工具调用观测

目标：把一次任务拆开，看清每个 generation 和 tool call。

### Step 2.1：LLM generation 观测

改动文件：

| 文件 | 修改内容 |
|---|---|
| `llm/base.py` | 为统一 response 结构补充可观测字段辅助方法 |
| `llm/openai_backend.py` | 在 `complete()` / `stream()` 包裹 generation |
| `llm/anthropic_backend.py` | 在 `complete()` / `stream()` 包裹 generation |

建议记录：

- model
- provider
- messages 摘要
- tool schemas 摘要
- output action
- input/output tokens
- cache stats
- duration_ms

如果不想在各 backend 内直接耦合 SDK，可在 `agent/core.py::_call_with_retry()` 外层统一包 generation。

推荐优先方案：

- generation 在 `agent/core.py::_call_with_retry()` 建立
- backend 只返回结构化结果

这样更统一，也能覆盖 OpenAI / Anthropic / mock backend。

### Step 2.2：工具调用观测

改动文件：

| 文件 | 修改内容 |
|---|---|
| `tools/base.py` 或 `ToolRegistry` 所在模块 | 包装 `execute_tool()` |
| `agent/core.py` | 在工具循环中传递 step、thought、tool metadata |

建议记录：

- tool name
- params
- step index
- success / error / timeout
- output 摘要
- error 信息
- duration_ms

### Step 2.3：Reflection 事件映射

对已有 reflection 语义做轻量映射：

- `test_failed`
- `no_edit_n_steps`
- loop detected

可作为 `event` 或 `span metadata` 记录。

### 验证

- 一次带工具调用的任务，trace 下能看到 generation 与 tool 子节点
- token 与时延在 Langfuse 中可见
- 工具错误会被正确标记

### 反思

这一阶段后，Langfuse 才真正从“任务日志”升级成“行为调试器”。

---

## Stage 3：Chat / Plan / DAG / Multi-Agent 结构化观测

目标：覆盖本项目真正有特色的工作流，而不仅是简单单轮 run。

### Step 3.1：ChatSession -> session_id

改动文件：

| 文件 | 修改内容 |
|---|---|
| `entry/chat.py` | 创建稳定 `session_id`，跨轮复用 |

建议：

- 每个 `ChatSession` 启动时生成 `session_id`
- 每轮 `Task` trace 继承该 `session_id`
- metadata 中加入 `round_count`

### Step 3.2：Plan 模式两阶段观测

改动文件：

| 文件 | 修改内容 |
|---|---|
| `agent/core.py` | phase metadata |
| `agent/plan.py` / `PlanExecuteAgent` | 标记 planning / execution |

建议写入：

- `metadata.phase = planning | execution`
- 计划文本长度
- 是否要求用户审批
- 是否 revise

### Step 3.3：DAG 子任务观测

改动文件：

| 文件 | 修改内容 |
|---|---|
| `agent/dag.py` | 每个 subtask 创建独立 trace 或 span |

推荐第一版：

- 每个 subtask 独立 trace
- 共享父 `session_id`
- metadata:
  - `parent_task_id`
  - `subtask_id`
  - `subtask_type`
  - `layer_index`
  - `depends_on`

### Step 3.4：Multi-Agent 观测

改动文件：

| 文件 | 修改内容 |
|---|---|
| `agent/multi_agent.py` | coordinator 与 sub-agent 的 trace 关联 |

建议记录：

- coordinator trace
- 每个 sub-agent 独立 trace
- metadata:
  - `role`
  - `agent_id`
  - `parent_task_id`
  - `isolation`
  - `worktree`

### 验证

- chat 多轮任务在 Langfuse 中按 session 聚合
- plan 模式能区分 planning/execution
- DAG / multi-agent 可按 subtask_id / role 过滤

### 反思

不要为了“完美的单 trace 树形结构”牺牲稳定性。对当前架构而言，`session + metadata 关联` 比深度嵌套更务实。

---

## Stage 4：数据脱敏、采样与运维保护

目标：确保接入可用于真实开发环境，而不是只在本地 demo。

### Step 4.1：Masking

改动文件：

| 文件 | 修改内容 |
|---|---|
| `observability/masking.py` | 脱敏规则 |
| `observability/langfuse_client.py` | 初始化时注册 masking hook |

至少处理以下内容：

- API key
- token / secret / password
- email / phone
- shell 输出中的敏感路径或凭证
- prompt / metadata 中的超长原始代码片段（必要时截断）

### Step 4.2：输出截断策略

建议：

- tool output 不上传全量，上传摘要和首尾片段
- prompt / response 超长时截断
- patch 默认不上传全文，只记录摘要与长度

### Step 4.3：采样与环境隔离

建议：

- `development` 环境全量采样
- `production` 支持 `sample_rate`
- 按 `environment` 字段隔离数据

### Step 4.4：故障容忍

要求：

- export 失败不影响主任务
- flush 失败不阻塞退出
- masking 异常时回退到更保守的删除策略

### 验证

- 构造包含敏感字符串的样例，确认 Langfuse 中看到的是脱敏结果
- 高失败率网络环境下任务仍正常执行

### 反思

这一阶段决定 Langfuse 是“工程能力”还是“开发风险”。必须在真正放大使用范围前完成。

---

## Stage 5：Prompt Management 迁移

目标：让 `prompts/` 从本地文件系统扩展到 Langfuse 管理。

### Step 5.1：定义 prompt 来源策略

推荐三档：

- `local`：完全使用本地 `prompts/`
- `langfuse`：完全从 Langfuse 拉取
- `hybrid`：优先 Langfuse，失败回退本地

### Step 5.2：在 `PromptAssembler` 增加远程 prompt provider

改动文件：

| 文件 | 修改内容 |
|---|---|
| `prompts/assembler.py` | 增加 provider 抽象 |
| `agent/prompt.py` | 接入远程 prompt 获取 |
| `config/schema.py` | 增加 prompt source 配置 |

推荐映射：

| 本地文件 | Langfuse prompt name |
|---|---|
| `base.md` | `forge/base` |
| `task.md` | `forge/task` |
| `task-analysis.md` | `forge/task-analysis` |
| `modes/plan.md` | `forge/modes/plan` |
| `modes/plan-execute.md` | `forge/modes/plan-execute` |
| `modes/plan-dag.md` | `forge/modes/plan-dag` |
| `modes/coordinator.md` | `forge/modes/coordinator` |

### Step 5.3：运行时拉取与编译

要求：

- 按 `production` label 拉取
- 支持变量编译
- 本地缓存最近一次成功拉取结果

### Step 5.4：trace 关联 prompt 版本

每次 LLM 调用记录：

- prompt name
- prompt version
- prompt label

### 验证

- 切换 Langfuse prompt label 后，无需改代码即可生效
- Langfuse 不可达时能稳定回退本地 prompt

### 反思

Prompt 迁移是行为变更，不只是存储变更。必须在已有 observability 的前提下做，否则难以判断行为变化来自哪里。

---

## Stage 6：Evaluation、Dataset 与实验闭环

目标：把 Langfuse 从“看发生了什么”升级到“判断改动值不值得”。

### Step 6.1：先做工程型评分

建议 score：

| 分数名 | 类型 | 含义 |
|---|---|---|
| `run_success` | BOOLEAN | 任务是否成功 |
| `tests_passed` | BOOLEAN | 是否通过测试 |
| `tool_error_count` | NUMERIC | 工具失败次数 |
| `reflection_count` | NUMERIC | 反思触发次数 |
| `max_step_reached` | BOOLEAN | 是否撞到步数上限 |

改动文件：

| 文件 | 修改内容 |
|---|---|
| `agent/core.py` | 任务结束时写 trace score |
| `agent/event_log.py` | 提供辅助统计 |
| `observability/tracing.py` | score 辅助方法 |

### Step 6.2：失败样本沉淀为数据集

来源：

- 测试失败的任务
- gave_up 的任务
- 用户明确不满意的任务

建议 dataset 命名：

```text
forge-agent/failures
forge-agent/plan-mode-edge-cases
forge-agent/tool-errors
```

### Step 6.3：建立实验对比

对比维度：

- 不同模型
- 不同 prompt 版本
- 不同 mode 注入文案
- 不同 tool policy

### Step 6.4：CI 回归预留

后续可在 CI 中跑：

- 指定 dataset
- 固定 prompt version
- 固定模型
- 输出 experiment result

### 验证

- 成功/失败任务能在 Langfuse 中看到 score
- dataset 可手动或程序化写入
- 实验结果能区分不同版本差异

### 反思

Evaluation 不是先验真理，而是反馈系统。第一版评分应优先用“工程真相”而不是主观 LLM judge。

---

## 6. 分阶段执行清单

### 阶段一：Observability 最小闭环

- [x] 增加 Langfuse 依赖与配置
- [x] 创建 `observability/` 适配层
- [x] 接入 no-op observer
- [x] 在 `ReActAgent.run()` 建立任务 trace
- [x] 在任务结束时 flush
- [x] 验证关闭配置时行为不变

### 阶段二：细粒度行为观测

- [x] 为 LLM 调用增加 generation 观测
- [x] 为工具调用增加 tool 观测
- [x] 记录 reflection、step、错误、cache stats
- [x] 验证 token / latency / error 可见

### 阶段三：工作流观测

- [x] ChatSession 增加 session_id
- [x] Plan 模式区分 planning/execution
- [x] DAG 子任务增加 trace 关联
- [x] Multi-Agent 增加 role / agent_id / parent_task_id
- [x] 验证 session 与多子任务筛选

### 阶段四：安全与运维

- [x] 增加 masking 规则
- [x] 增加输出截断
- [x] 增加采样率与 environment
- [x] 验证 Langfuse 失败不影响主流程

### 阶段五：Prompt Management

- [x] 定义 `local / langfuse / hybrid`
- [x] 为 `PromptAssembler` 增加远程 provider
- [x] 映射现有 prompts 到 Langfuse names
- [x] 记录 prompt version/label 到 trace
- [x] 验证回退机制

### 阶段六：Evaluation

- [x] 写入工程型 scores
- [x] 建立失败 dataset
- [x] 创建实验基线
- [x] 预留 CI 接口

---

## 7. 我们明确暂不做的事情

| 项目 | 原因 |
|---|---|
| 一上来就把所有 prompt 全量迁远程 | 风险高，先完成观测更稳 |
| 只包 OpenAI SDK | 会漏掉 Anthropic 和抽象层行为 |
| 把 DAG / multi-agent 强行压成一个超级大 trace | 当前并发结构下复杂度高、收益不成比例 |
| 用 LLM judge 作为第一版主评分机制 | 先用工程事实分数更稳定 |
| 全量上传工具输出、patch、原始代码 | 成本高且有隐私风险 |

---

## 8. 阶段依赖关系

```text
Stage 0 (配置与适配层)
  -> Stage 1 (任务 trace)
  -> Stage 2 (LLM + Tool 观测)
  -> Stage 3 (Chat/Plan/DAG/Multi-Agent)
  -> Stage 4 (Masking/采样/故障保护)
  -> Stage 5 (Prompt Management)
  -> Stage 6 (Evaluation)
```

说明：

- Stage 4 最晚必须在 Stage 5 之前完成
- Stage 5 必须建立在 Stage 1-3 已稳定的前提下
- Stage 6 依赖 Stage 1-3 的 trace 质量，也依赖 Stage 5 的 prompt 可追踪性

---

## 9. 成功指标

| 指标 | 目标 | 衡量方式 |
|---|---|---|
| Trace 成功率 | >95% 的任务能成功上报 trace | 对比本地任务数与 Langfuse trace 数 |
| 行为覆盖率 | LLM 调用与工具调用可见率 >90% | 抽样比对 EventLog 与 Langfuse |
| 性能开销 | 平均额外耗时 <10% | 接入前后基准比较 |
| 故障隔离 | Langfuse 故障不影响主任务成功率 | 断网与错误凭证回归测试 |
| 会话聚合准确率 | chat 多轮任务都带正确 session_id | 抽样检查 |
| Prompt 可追踪率 | 远程 prompt 调用 100% 记录版本/label | 检查 generation metadata |
| Score 可用率 | 成功/失败任务都能写入基本 score | 抽样检查 trace score |

---

## 10. 推荐开发顺序

如果按实际开发推进，建议每一阶段都以“可运行、可验证、可回退”为里程碑：

1. Stage 0：把适配层搭好
2. Stage 1：先看到第一条稳定 trace
3. Stage 2：再把 generation 与 tool 补齐
4. Stage 3：覆盖 chat / plan / dag / multi-agent
5. Stage 4：完成 masking 和容错
6. Stage 5：迁 prompt
7. Stage 6：做评估与数据集

一句话总结：

> 先把系统“看见”，再把 prompt “管住”，最后把改动“评出来”。
