# Phase 11 Batch B Guidance — Concurrency + State Consistency

> **版本**: Draft, awaiting review  
> **日期**: 2026-07-22  
> **状态**: Draft — review gate before implementation  
> **Phase 11 目标**: 安全硬化、并发收口、失败注入、观测性固化  
> **预计总工时**: 9h

---

## 目录

1. [Batch B 目标定义](#1-batch-b-目标定义)
2. [Task Breakdown](#2-task-breakdown)
3. [文件级修改清单](#3-文件级修改清单)
4. [测试方案](#4-测试方案)
5. [回归验收标准](#5-回归验收标准)
6. [Risk Notes](#6-risk-notes)
7. [Implementation Sequence](#7-implementation-sequence)

---

## 1. Batch B 目标定义

### 目标

Batch B 负责把 harness 的并发边界收口，重点是：

- session 生命周期原子化
- per-session backend 串扰隔离
- SQLite / DB 并发回归
- cleanup 路径完整释放

### 为什么在 A 之后做 B

Batch A 先把安全底座补齐，Batch B 再把并发边界收口。这样在多 session / 子代理 / background run 的情况下，系统不会把安全与状态问题叠加在一起。

---

## 2. Task Breakdown

| ID | Task | Est. | Dependencies | Verification |
|----|------|------|-------------|--------------|
| B-1 | 会话生命周期原子化 | 3h | A-1/A-2 | 同 session 重入被阻断，delete/cancel 不留 zombie |
| B-2 | per-session backend 串扰隔离 | 2h | B-1 | model switch 只影响当前 session |
| B-3 | SQLite / DB 并发回归 | 2h | B-1 | 并发读写无 SQLITE_BUSY / 锁死 |
| B-4 | cleanup 路径收口 | 1.5h | B-1/B-2 | backend / token / callback / background run 全部释放 |
| B-5 | Batch B 全量回归 | 0.5h | B-1~B-4 | gate + 并发测试全绿 |

---

## 3. 文件级修改清单

### B-1 会话生命周期原子化

#### 主要文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [agent/session/session_store.py](../agent/session/session_store.py)
- [server/services/agent_service.py](../server/services/agent_service.py)
- [server/routers/sessions.py](../server/routers/sessions.py)

#### 修改点
1. 收紧 `try_acquire_session()` / `release_session()` 的调用边界。
2. session start / cancel / delete 统一走单入口。
3. 删除时确保状态检查与资源释放原子化。
4. 对运行中 session 的并发启动给出明确拒绝。

#### 重点验证
- 同一 session 不能重复启动
- 删除时不会留下后台线程
- cancel 后状态一致

---

### B-2 per-session backend 串扰隔离

#### 主要文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [server/services/agent_service.py](../server/services/agent_service.py)
- [agent/session/runtime_spawn.py](../agent/session/runtime_spawn.py)
- [server/services/chat_pipeline.py](../server/services/chat_pipeline.py)

#### 修改点
1. 明确 session-local backend 的读写边界。
2. 模型切换只影响当前 session。
3. 子代理继承时使用 session-local backend，而不是共享全局引用。
4. 保持 `api_key` / `base_url` / `provider` / `model` 四项配置隔离。

#### 重点验证
- 两个 session 并发切换模型不串
- 父子代理 backend 一致但不共享跨 session 状态

---

### B-3 SQLite / DB 并发回归

#### 主要文件
- [agent/session/session_store.py](../agent/session/session_store.py)
- [tests/test_e2e_core.py](../tests/test_e2e_core.py)
- [tests/manual/test_abort_e2e.py](../tests/manual/test_abort_e2e.py)

#### 修改点
1. 继续验证 WAL / busy_timeout 在并发场景下有效。
2. 补多线程 / 多 session 读写混合回归。
3. 将 `SQLITE_BUSY` 作为明确失败信号写入测试断言。

#### 重点验证
- 并发写入稳定
- 读写混合稳定
- 不出现数据库锁死

---

### B-4 cleanup 路径收口

#### 主要文件
- [agent/session/runtime.py](../agent/session/runtime.py)
- [server/services/agent_service.py](../server/services/agent_service.py)
- [agent/session/worktree_manager.py](../agent/session/worktree_manager.py)

#### 修改点
1. 会话结束时清理 backend store。
2. 清理 cancellation token。
3. 清理 approval / web callback。
4. 清理 background run 记录。

#### 重点验证
- 运行结束后无残留 session 状态
- cleanup 重入安全

---

## 4. 测试方案

### B-1 Tests
- 同 session 并发启动只允许一个成功
- delete during run 被明确拒绝或安全收敛
- cancel 后状态终止正确

### B-2 Tests
- 两个 session 并行切换不同模型
- 一个 session 的 api_key/base_url 不影响另一个
- 子代理继承正确的 session-local backend

### B-3 Tests
- 3 个 session 并发启动
- 读写混合访问
- 取消和写入并发
- `SQLITE_BUSY` 不出现

### B-4 Tests
- session 完成后 backend/token/callback/background run 均清理
- cleanup 重入不报错

---

## 5. 回归验收标准

- [ ] session 生命周期原子化
- [ ] backend 串扰隔离通过
- [ ] SQLite 并发回归通过
- [ ] cleanup 路径无残留
- [ ] 相关 gate 与并发测试全绿

---

## 6. Risk Notes

### 已知取舍

- Batch B 目标不是把所有状态逻辑重写一遍，而是把高风险竞态收口到可验证边界。
- 若发现单一 session 状态机过于复杂，可优先在 router/service 层做最小原子化封装。

### 风险升级触发条件

- 新 session 入口绕过 `try_acquire_session()`
- backend 仍有跨 session 共享引用
- cleanup 新增资源但未同步释放

---

## 7. Implementation Sequence

```
B-1: lifecycle atomicity
B-2: per-session backend isolation
B-3: SQLite concurrency regression tests
B-4: cleanup path hardening
B-5: full regression + gate run
```

---

*Batch B ready for review.*
