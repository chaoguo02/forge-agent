# Phase 11 Harness Maturity Plan — Security, Concurrency, E2E, Observability

> **版本**: 1.0  
> **日期**: 2026-07-22  
> **状态**: Draft — awaiting implementation  
> **输入**: [BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md), [QUALITY_GATE.md](QUALITY_GATE.md), [RISK_REGISTER.md](RISK_REGISTER.md), [PHASE10_ROADMAP.md](PHASE10_ROADMAP.md)  
> **目标**: 将 harness 从“结构完整”推进到“安全可收口、并发可证明、失败可恢复、面试可展示”

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [当前差距概览](#2-当前差距概览)
3. [批次 A — 安全硬化](#3-批次-a--安全硬化)
4. [批次 B — 并发与状态一致性](#4-批次-b--并发与状态一致性)
5. [批次 C — E2E 与失败注入](#5-批次-c--e2e-与失败注入)
6. [批次 D — 观测性与演示包装](#6-批次-d--观测性与演示包装)
7. [验收门槛](#7-验收门槛)
8. [风险登记与复审建议](#8-风险登记与复审建议)
9. [批次完成后的目标状态](#9-批次完成后的目标状态)

---

## 1. 执行摘要

Grace-Code 目前已经具备完整的 agent harness 骨架：

- ReAct 主循环
- SessionRuntime 子代理编排
- ChatPipeline 聊天执行流水线
- MCP / Workflow / ToolSearch
- 质量门禁与风险登记
- WebSocket 实时事件流
- 上下文压缩与长期记忆

但若要进入“成熟的面试版本”，仍需补齐四类能力：

1. **安全硬化**：命令注入、sandbox、路径边界
2. **并发硬化**：session 生命周期原子化、backend 隔离、竞态回归
3. **E2E 与失败注入**：不仅能跑通 happy path，还要证明失败时能收敛
4. **观测性与演示包装**：把系统健康、回归证据、 demo story 固化下来

**对标 Claude Code 的方向约束**：
- 真正的“每次都要挡住”的边界，优先放在 **hooks / deny rules / sandbox**，而不是只靠模型提示或文档约定。
- `PreToolUse` 这类确定性钩子适合做命令级拦截；权限规则适合做声明式 policy；sandbox 负责 OS 边界。
- subagent 适合做隔离和并行，不适合承担主安全策略的唯一来源。

本计划按这四类拆成四个批次，每个批次都给出文件级落点、测试方案和验收标准。

---

## 2. 当前差距概览

| 维度 | 现状 | 缺口 | 优先级 |
|------|------|------|------|
| 命令注入防护 | 已有 sandbox / gate 方向 | 还缺 shell 级 pre-filter 与路径约束闭环 | P0 |
| 环境变量隔离 | 已有 Docker/sandbox 思路 | 还缺明确 whitelist 与泄漏验证 | P0 |
| session 并发 | 已有 WAL / acquire 机制 | 还缺更完整的生命周期原子化与回归测试 | P0 |
| backend 隔离 | 已朝 per-session 方向演进 | 还需证明 model switch 不串 session | P0 |
| E2E 覆盖 | 已有 abort / lifecycle 雏形 | 还缺失败注入矩阵与子代理失败链路 | P1 |
| 观测性 | 有 RetryMetrics / stats / gate | 还缺更统一的 health 视图与证据输出 | P1 |
| 面试可展示性 | 文档多，工程感强 | 还缺一套稳定 demo 流程 | P2 |

---

## 3. 批次 A — 安全硬化

> **目标**: 把“有安全意识”推进到“有明确边界和可验证防线”。

### A1. 命令注入预过滤

#### 问题定位
当前 shell 执行链路已经有部分安全约束，但对以下常见注入模式仍缺系统化 pre-filter：

- `${...}`
- `$(...)`
- 反引号
- shell 拼接式路径注入
- 通过重定向绕过路径意图

#### 相关文件
- [core/process.py](../core/process.py)
- [tools/_check_cmd_injection_gate.sh](../tools/_check_cmd_injection_gate.sh)
- [tools/_test_cmd_injection_patterns.py](../tools/_test_cmd_injection_patterns.py)
- [tools/_quality_gate.sh](../tools/_quality_gate.sh)

#### 精确修改方案
1. 在 `core/process.py` 的 shell 执行入口增加命令注入 pre-filter。
2. `tools/_test_cmd_injection_patterns.py` 补齐恶意样例矩阵。
3. `tools/_check_cmd_injection_gate.sh` 保持 gate 入口，不承载复杂逻辑。
4. `tools/_quality_gate.sh` 中 `CMD-INJ` 失败时输出更明确的分类。

#### 建议样例矩阵
| 样例 | 期望 |
|------|------|
| `echo hello` | 通过 |
| `echo $(whoami)` | 拒绝 |
| ``echo `whoami``` | 拒绝 |
| `echo ${HOME}` | 拒绝或规范化为安全模式 |
| `bash -c 'cat /etc/passwd'` | 依策略拒绝 |

#### 测试方案
- 合法 shell 命令通过
- 注入样例全部拒绝
- 现有正常工具调用不误伤
- `FORGE_SANDBOX=docker` 时 gate 生效

#### 回归验收标准
- 不出现“审批通过但 shell 逃逸”的路径
- 注入样例都能稳定失败
- gate 输出可直接读懂

---

### A2. Sandbox 环境变量白名单

#### 问题定位
当前 sandbox 方向已存在，但 env 透传还不够显式，容易引入凭据泄漏面。

#### 相关文件
- [core/process.py](../core/process.py)
- [tools/_check_sandbox_config.py](../tools/_check_sandbox_config.py)
- [tools/_check_sandbox_config.sh](../tools/_check_sandbox_config.sh)
- [tools/_check_sandbox_isolation.sh](../tools/_check_sandbox_isolation.sh)

#### 精确修改方案
1. 在 `core/process.py` 增加 env whitelist 逻辑。
2. 明确允许透传的变量集合，例如：`FORGE_*`、`LANGFUSE_*`、`PATH`、`HOME`。
3. `tools/_check_sandbox_config.py` 负责验证资源限制是否可解析。
4. `tools/_check_sandbox_isolation.sh` 负责验证 sandbox 实际可达与限制生效。

#### 测试方案
- 默认环境变量被过滤
- 允许变量按策略透传
- 敏感变量不进入容器
- sandbox 不可用时给出明确失败原因

#### 回归验收标准
- sandbox 配置有清晰白名单
- 不出现“隐式继承全部宿主环境”的情况

---

### A3. 路径级约束补强

#### 问题定位
当前已有工具级权限和审批，但路径级约束还不够完整，尤其是 shell 重定向、间接写入与 resolve 后路径穿越。

#### 相关文件
- [core/base.py](../core/base.py)
- [hitl/pipeline.py](../hitl/pipeline.py)
- [agent/core.py](../agent/core.py)
- [server/services/agent_service.py](../server/services/agent_service.py)

#### 精确修改方案
1. 将写入目标路径纳入统一检查。
2. 将 shell 重定向目标路径也纳入检查。
3. 对 `Write/Edit/Bash` 统一做 `resolve()` + `relative_to()` 校验。
4. 对敏感路径采用 fail closed。

#### 测试方案
- 允许路径内写入
- 拒绝路径穿越
- 拒绝 shell 间接写入敏感目录
- 审批和路径约束行为一致

#### 回归验收标准
- 不存在“审批了命令却绕过路径”的空间
- 路径约束与工具审批形成双层边界

---

### A4. 风险登记册同步

#### 相关文件
- [docs/RISK_REGISTER.md](RISK_REGISTER.md)
- [docs/PHASE10_ROADMAP.md](PHASE10_ROADMAP.md)

#### 建议新增风险项
- 命令注入预过滤不足
- sandbox env 透传过宽
- 路径级约束不完整

#### 回归验收标准
- 每项风险都有升级触发条件
- 修复完成后有复审日期

---

## 4. 批次 B — 并发与状态一致性

> **目标**: 把“基本能并发”推进到“竞态下仍可预测”。

### B1. 会话生命周期原子化

#### 问题定位
并发场景中最常见的问题是：

- 同 session 重入
- 创建和启动之间 TOCTOU
- 删除和执行交错
- cancel 后资源没释放干净

#### 相关文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [agent/session/session_store.py](../agent/session/session_store.py)
- [server/services/agent_service.py](../server/services/agent_service.py)

#### 精确修改方案
1. 收紧 `try_acquire_session()` / `release_session()` 的调用边界。
2. session start / cancel / delete 统一走单入口。
3. delete 后确保 backend / callback / token / background run 全部释放。
4. 对 session 状态流转增加更严格的断言。

#### 测试方案
- 同 session 并发启动只允许一个成功
- delete during run 不留 zombie
- cancel 后资源彻底回收
- 失败后可再次启动新 session

#### 回归验收标准
- session 生命周期可预测
- 竞态不依赖“运气没撞上”

---

### B2. per-session backend 串扰测试

#### 问题定位
`LLMBackend` 已经开始朝 session-local 方向收口，但仍需证明 model switch 不会跨 session 污染。

#### 相关文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [server/services/agent_service.py](../server/services/agent_service.py)
- [agent/session/runtime_spawn.py](../agent/session/runtime_spawn.py)

#### 精确修改方案
1. 确保模型切换只影响当前 session。
2. 子代理继承的 backend 也必须是 session-local。
3. `api_key` / `base_url` / `model` / `provider` 不应跨 session 污染。

#### 测试方案
- 两个 session 并行切换不同模型
- 一个 session 的 `api_key` 不影响另一个
- 子代理与父代理 backend 一致且隔离

#### 回归验收标准
- 不出现跨 session 错配
- 并发下配置稳定

---

### B3. SQLite / DB 并发回归测试

#### 相关文件
- [agent/session/session_store.py](../agent/session/session_store.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)

#### 精确修改方案
1. 在测试里覆盖 WAL / busy_timeout / 并发读写。
2. 验证多 session / 多线程同时访问稳定。
3. 把 `SQLITE_BUSY` 作为明确回归项。

#### 测试方案
- 3 个 session 并行启动
- 读写混合
- 取消和写入并发
- 存储统计读写一致

#### 回归验收标准
- 并发场景稳定
- 不再出现 SQLite 锁死

---

## 5. 批次 C — E2E 与失败注入

> **目标**: 证明系统不仅能成功，还能在失败时收敛。

### C1. Abort / Cancel / Timeout E2E 扩展

#### 相关文件
- [tests/manual/test_abort_e2e.py](../tests/manual/test_abort_e2e.py)
- [tests/manual/test_llm_timeout_e2e.py](../tests/manual/test_llm_timeout_e2e.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)

#### 建议场景矩阵
| 场景 | 期望 |
|------|------|
| 用户 cancel | WS 收到终态 |
| LLM timeout | 结构化错误回流 |
| 工具失败 | 可恢复或显式失败 |
| session delete during run | 无 zombie |
| rapid switch | 不串状态 |

#### 回归验收标准
- 每个场景都有明确终态
- 不靠人工看日志判断结果

---

### C2. 子代理失败链路测试

#### 相关文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [agent/session/worktree_manager.py](../agent/session/worktree_manager.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)

#### 精确修改方案
1. 覆盖子代理失败后父代理如何收敛。
2. 验证 worktree apply / discard / retain。
3. 覆盖 background child 完成后的通知链路。
4. 覆盖 cancellation 传播。

#### 回归验收标准
- 子代理失败可观测
- 父流程不挂死
- worktree 不残留脏状态

---

### C3. 计划 / 审批 / 执行闭环测试

#### 相关文件
- [server/services/chat_pipeline.py](../server/services/chat_pipeline.py)
- [hitl/pipeline.py](../hitl/pipeline.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)

#### 精确修改方案
覆盖以下完整链路：

- plan 创建
- approve / reject
- 执行
- diff review
- completion guard

#### 回归验收标准
- 计划流程可以完整演示
- 失败路径也能闭环

---

### C4. 失败注入点

#### 建议增加的 failpoint
- malformed tool call
- WS 短暂断开
- hook 抛异常
- MCP tool 不可用
- SQLite lock contention

#### 相关文件
- [hooks/dispatcher.py](../hooks/dispatcher.py)
- [server/services/event_bus.py](../server/services/event_bus.py)
- [server/routers/websocket.py](../server/routers/websocket.py)
- [llm/tool_call_validator.py](../llm/tool_call_validator.py)

#### 回归验收标准
- failpoint 可复现
- failpoint 有明确终态
- 不出现 silent failure

---

## 6. 批次 D — 观测性与演示包装

> **目标**: 把工程能力转化为可展示、可复盘、可讲述的证据。

### D1. 标准化 run 证据

#### 相关文件
- [llm/invoker.py](../llm/invoker.py)
- [server/services/stats_recorder.py](../server/services/stats_recorder.py)
- [server/services/stats_service.py](../server/services/stats_service.py)

#### 精确修改方案
统一保留：

- retry 次数
- 终态原因
- 错误类型
- session duration
- tool failure 分布

#### 回归验收标准
- 每次关键 run 都能复盘
- 面试时能直接展示证据

---

### D2. 小型 Harness Health 面板

#### 相关文件
- [web/src/components/StatsDashboard.tsx](../web/src/components/StatsDashboard.tsx)
- [web/src/components/SessionStatsDrawer.tsx](../web/src/components/SessionStatsDrawer.tsx)
- [web/src/components/ChatView.tsx](../web/src/components/ChatView.tsx)
- [web/src/stores/chatStore.ts](../web/src/stores/chatStore.ts)

#### 精确修改方案
做一个轻量 health 视图，显示：

- 活跃 session 数
- 最近 gate 结果
- retry 统计
- sandbox 状态
- 失败类型计数

#### 回归验收标准
- 不影响主聊天路径性能
- 数据来源明确
- 视图更新稳定

---

### D3. Demo 脚本 / 讲述材料

#### 相关文件
- [docs/BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md)
- [docs/PHASE10_ROADMAP.md](PHASE10_ROADMAP.md)
- [docs/QUALITY_GATE.md](QUALITY_GATE.md)

#### 建议准备的 3 套演示
1. 正常开发流程
2. 子代理 + worktree
3. 取消 / 失败 / 恢复

#### 回归验收标准
- 面试 / 演示可直接使用
- 不需要临时解释太多背景

---

## 7. 验收门槛

### 7.1 技术门槛

- [ ] 命令注入预过滤稳定通过
- [ ] sandbox env whitelist 生效
- [ ] 路径级约束完成闭环
- [ ] session 生命周期原子化
- [ ] backend 串扰测试通过
- [ ] 并发回归测试稳定
- [ ] abort / timeout / failure E2E 全部有明确终态
- [ ] 子代理失败链路可复现
- [ ] health / stats 证据可展示

### 7.2 面试门槛

- [ ] 能用一页图讲清 harness 架构
- [ ] 能用一次 demo 讲清安全与并发边界
- [ ] 能拿出失败恢复的实际证据
- [ ] 能解释取舍：哪些做了，哪些刻意延后

---

## 8. 风险登记与复审建议

建议在 [docs/RISK_REGISTER.md](RISK_REGISTER.md) 中新增以下条目：

| 风险 | 触发条件 | 升级路径 |
|------|----------|----------|
| 命令注入 pre-filter 不完整 | 新 shell 入口绕过统一检查 | 上升为 P0 |
| env whitelist 泄漏 | 新变量默认透传 | 收紧默认策略 |
| session 竞态回归 | 重入 / delete during run 复现 | 继续强化原子锁 |
| backend 串扰 | 多 session model switch 错配 | session-local backend 必须强制化 |
| E2E failpoint 不稳定 | 失败场景不可复现 | 改为显式 failpoint 注入 |

建议复审周期：**每批完成后立即复审一次**，再并入季度复审节奏。

---

## 9. 批次完成后的目标状态

完成本计划后，harness 应达到以下状态：

1. **安全边界明确**
   - shell 命令注入被前置拦截
   - sandbox env 泄漏可控
   - 路径写入受约束

2. **并发行为可预测**
   - 同 session 重入被拦住
   - backend 不串 session
   - DB 并发稳定

3. **失败路径可证明**
   - cancel / timeout / delete / failpoint 都有明确终态
   - 不再依赖人工观感判断系统是否“健康”

4. **可展示性增强**
   - health 面板和 stats 提供证据
   - demo story 稳定可复用
   - 面试时能讲出“我们怎么知道它成熟了”

---

*Phase 11 harness maturity plan draft ready for implementation.*
