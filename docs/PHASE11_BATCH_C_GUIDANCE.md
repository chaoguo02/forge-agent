# Phase 11 Batch C Guidance — E2E + Failure Injection

> **版本**: Draft, awaiting review  
> **日期**: 2026-07-22  
> **状态**: Draft — review gate before implementation  
> **Phase 11 目标**: 安全硬化、并发收口、失败注入、观测性固化  
> **预计总工时**: 8h

---

## 目录

1. [Batch C 目标定义](#1-batch-c-目标定义)
2. [Task Breakdown](#2-task-breakdown)
3. [文件级修改清单](#3-文件级修改清单)
4. [测试方案](#4-测试方案)
5. [回归验收标准](#5-回归验收标准)
6. [Risk Notes](#6-risk-notes)
7. [Implementation Sequence](#7-implementation-sequence)

---

## 1. Batch C 目标定义

### 目标

Batch C 负责把 harness 的“失败路径”补齐，重点是：

- abort / cancel / timeout E2E
- 子代理失败链路
- plan / approve / execute 闭环
- failpoint 注入与终态证明

### 为什么在 B 之后做 C

Batch C 依赖 Batch B 的并发收口。只有 session 生命周期稳定后，E2E 才能可靠区分“真实失败”与“竞态噪声”。

---

## 2. Task Breakdown

| ID | Task | Est. | Dependencies | Verification |
|----|------|------|-------------|--------------|
| C-1 | Abort / cancel / timeout E2E 扩展 | 2h | B-1 | WS 收到明确终态 |
| C-2 | 子代理失败链路测试 | 2h | B-2/B-4 | 父流程可收敛，worktree 无残留 |
| C-3 | 计划 / 审批 / 执行闭环测试 | 2h | B-1 | plan→approve→execute→review 完整通过 |
| C-4 | failure injection 点补齐 | 1.5h | A-1/B-1 | malformed tool / WS / hook / MCP failpoint 可复现 |
| C-5 | Batch C 全量回归 | 0.5h | C-1~C-4 | 失败路径测试全绿 |

---

## 3. 文件级修改清单

### C-1 Abort / cancel / timeout E2E 扩展

#### 主要文件
- [tests/manual/test_abort_e2e.py](../tests/manual/test_abort_e2e.py)
- [tests/manual/test_llm_timeout_e2e.py](../tests/manual/test_llm_timeout_e2e.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)
- [server/routers/websocket.py](../server/routers/websocket.py)

#### 修改点
1. 扩展 abort/cancel/timeout 场景矩阵。
2. 每个场景都明确等待的终态。
3. WS 断开、cancel、timeout 统一可观测。
4. 避免只测 happy path。

#### 重点验证
- 用户 cancel 后能收到终态
- timeout 不是静默失败
- delete during run 可收敛

---

### C-2 子代理失败链路测试

#### 主要文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [agent/session/worktree_manager.py](../agent/session/worktree_manager.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)

#### 修改点
1. 覆盖子代理失败后的父级收敛逻辑。
2. 覆盖 worktree apply / discard / retain 行为。
3. 覆盖 background child 通知链路。
4. 覆盖 cancellation 传播。

#### 重点验证
- 子代理失败可观测
- 父流程不挂死
- worktree 清理完整

---

### C-3 计划 / 审批 / 执行闭环测试

#### 主要文件
- [server/services/chat_pipeline.py](../server/services/chat_pipeline.py)
- [hitl/pipeline.py](../hitl/pipeline.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)
- [server/services/agent_service.py](../server/services/agent_service.py)

#### 修改点
1. 覆盖 plan 创建。
2. 覆盖 approve / reject。
3. 覆盖执行与 diff review。
4. 覆盖 completion guard。

#### 重点验证
- plan→approve→execute→review 可以完整跑通
- 拒绝路径和通过路径都明确

---

### C-4 failure injection 点补齐

#### 主要文件
- [hooks/dispatcher.py](../hooks/dispatcher.py)
- [llm/tool_call_validator.py](../llm/tool_call_validator.py)
- [server/services/event_bus.py](../server/services/event_bus.py)
- [server/routers/websocket.py](../server/routers/websocket.py)

#### 修改点
1. 增加 malformed tool call failpoint。
2. 增加 hook 抛异常 failpoint。
3. 增加 WS 短暂断开 failpoint。
4. 增加 MCP tool unavailable failpoint。

#### 重点验证
- failpoint 可复现
- failpoint 终态明确
- 不出现 silent failure

---

## 4. 测试方案

### C-1 Tests
- cancel 触发后 WS 收到终态
- timeout 不产生 zombie
- delete during run 无残留

### C-2 Tests
- 子代理失败后父流程退出或降级正确
- worktree 记录一致
- cancellation 可传播

### C-3 Tests
- plan / approve / execute / review 全链路通过
- reject 路径明确

### C-4 Tests
- malformed tool call 被拒绝或转化为结构化错误
- hook 异常不导致静默崩溃
- WS 断开有明确恢复或终态

---

## 5. 回归验收标准

- [ ] abort / cancel / timeout 有明确终态
- [ ] 子代理失败链路可证明
- [ ] plan / approve / execute 闭环通过
- [ ] failure injection 可复现
- [ ] 不存在 silent failure

---

## 6. Risk Notes

### 已知取舍

- Batch C 不追求把每个失败场景都“修成成功”，而是把失败路径显式化、可观察化。
- 若某 failpoint 触发成本过高，可先从最常见的 malformed input、timeout、WS 断连开始。

### 风险升级触发条件

- 新流程没有失败终态
- 子代理失败不能回流到父级
- E2E 测试依赖人工观察日志

---

## 7. Implementation Sequence

```
C-1: abort/cancel/timeout E2E expansion
C-2: child failure chain coverage
C-3: plan/approve/execute loop coverage
C-4: failpoint injection hooks
C-5: full regression + gate run
```

---

*Batch C ready for review.*
