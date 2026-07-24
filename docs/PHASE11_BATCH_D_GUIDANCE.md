# Phase 11 Batch D Guidance — Observability + Demo Packaging

> **版本**: Draft, awaiting review  
> **日期**: 2026-07-22  
> **状态**: Draft — review gate before implementation  
> **Phase 11 目标**: 安全硬化、并发收口、失败注入、观测性固化  
> **预计总工时**: 6h

---

## 目录

1. [Batch D 目标定义](#1-batch-d-目标定义)
2. [Task Breakdown](#2-task-breakdown)
3. [文件级修改清单](#3-file-level-modification-list)
4. [测试方案](#4-testing-plan)
5. [回归验收标准](#5-acceptance-criteria)
6. [Risk Notes](#6-risk-notes)
7. [Implementation Sequence](#7-implementation-sequence)

---

## 1. Batch D 目标定义

### 目标

Batch D 负责把 harness 的“证据层”和“展示层”固化下来，重点是：

- 标准化 run 证据
- 小型 harness health 面板
- demo 脚本与讲述材料
- 最终面试可展示故事线

### 为什么在 C 之后做 D

当安全、并发、失败路径都稳定后，才适合把观测和展示封装成固定材料。否则健康面板和 demo 只会掩盖底层不稳定。

---

## 2. Task Breakdown

| ID | Task | Est. | Dependencies | Verification |
|----|------|------|-------------|--------------|
| D-1 | 标准化 run 证据 | 2h | C-1/C-2 | retry / error / duration / failure type 可复盘 |
| D-2 | 小型 harness health 面板 | 2h | D-1 | 活跃 session / gate / retry / sandbox 状态可视化 |
| D-3 | demo 脚本与讲述材料 | 1.5h | C-3 | 3 套 demo 流程可直接复用 |
| D-4 | Batch D 全量回归 | 0.5h | D-1~D-3 | 证据与展示材料齐备 |

---

## 3. 文件级修改清单

### D-1 标准化 run 证据

#### 主要文件
- [llm/invoker.py](../llm/invoker.py)
- [server/services/stats_recorder.py](../server/services/stats_recorder.py)
- [server/services/stats_service.py](../server/services/stats_service.py)
- [docs/BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md)

#### 修改点
1. 统一保留 retry 次数、终态原因、错误类型、session duration。
2. 让关键 run 有固定结构的 evidence 输出。
3. 将失败类型统计纳入 stats 视图。

#### 重点验证
- 每次关键 run 都能复盘
- 失败不只是“失败了”，而是能说明为什么失败

---

### D-2 小型 harness health 面板

#### 主要文件
- [web/src/components/StatsDashboard.tsx](../web/src/components/StatsDashboard.tsx)
- [web/src/components/SessionStatsDrawer.tsx](../web/src/components/SessionStatsDrawer.tsx)
- [web/src/components/ChatView.tsx](../web/src/components/ChatView.tsx)
- [web/src/stores/chatStore.ts](../web/src/stores/chatStore.ts)
- [web/src/stores/sessionStore.ts](../web/src/stores/sessionStore.ts)

#### 修改点
1. 增加轻量 health 视图。
2. 展示活跃 session 数、最近 gate、retry 统计、sandbox 状态。
3. 不影响主聊天路径的交互性能。

#### 重点验证
- 数据来源清楚
- 视图更新稳定
- 不引入新的 WS 竞态

---

### D-3 demo 脚本与讲述材料

#### 主要文件
- [docs/BENCHMARK_ANALYSIS.md](BENCHMARK_ANALYSIS.md)
- [docs/PHASE11_HARNESS_MATURITY_PLAN.md](PHASE11_HARNESS_MATURITY_PLAN.md)
- [docs/QUALITY_GATE.md](QUALITY_GATE.md)
- [docs/RISK_REGISTER.md](RISK_REGISTER.md)

#### 修改点
1. 准备 3 套 demo：正常开发、子代理+worktree、取消/失败/恢复。
2. 整理一页式讲述主线。
3. 让面试时能直接展示“我们怎么知道它成熟了”。

#### 重点验证
- demo 可重复
- 叙事顺序稳定
- 不依赖临场发挥

---

## 4. Testing Plan

### D-1 Tests
- 关键 run 的 evidence 结构完整
- retry / failure / duration 可查询

### D-2 Tests
- health 面板能展示正确的统计
- session 切换时不闪断
- 不影响主聊天路径

### D-3 Tests
- 三套 demo 流程都能顺利跑通
- 讲述材料与当前代码状态一致

---

## 5. Acceptance Criteria

- [ ] run 证据标准化完成
- [ ] harness health 面板可用
- [ ] demo 脚本可直接复用
- [ ] 面试故事线清晰
- [ ] 不影响主流程性能

---

## 6. Risk Notes

### 已知取舍

- D 批次是“把已完成的工程结果讲清楚”，不是新增大量业务逻辑。
- 若健康面板过重，优先保留只读统计，不引入复杂写路径。

### 风险升级触发条件

- 观测层造成主流程变慢
- 展示层与实际运行状态不一致
- demo 脚本依赖临时手工修正

---

## 7. Implementation Sequence

```
D-1: run evidence standardization
D-2: harness health panel
D-3: demo scripts + talk track
D-4: full regression + packaging review
```

---

*Batch D ready for review.*
