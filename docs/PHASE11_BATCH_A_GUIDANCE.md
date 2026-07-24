# Phase 11 Batch A Guidance — Security Hardening Kickoff

> **版本**: Draft, awaiting review  
> **日期**: 2026-07-22  
> **状态**: Draft — review gate before implementation  
> **Phase 11 目标**: 安全硬化、并发收口、失败注入、观测性固化  
> **预计总工时**: 8h

---

## 目录

1. [Batch A 目标定义](#1-batch-a-目标定义)
2. [Task Breakdown](#2-task-breakdown)
3. [文件级修改清单](#3-文件级修改清单)
4. [测试方案](#4-测试方案)
5. [回归验收标准](#5-回归验收标准)
6. [Risk Notes](#6-risk-notes)
7. [Implementation Sequence](#7-implementation-sequence)

---

## 1. Batch A 目标定义

### 目标

Batch A 负责把 harness 的安全边界补齐，重点是：

- 命令注入预过滤
- sandbox env whitelist
- 路径级约束补强
- 风险登记同步

### 为什么先做 Batch A

安全是最容易被追问、也最容易出事故的底座。只要 shell / 路径 / env 三件事没收口，后面的并发、E2E、演示都可能建立在脆弱边界上。

---

## 2. Task Breakdown

| ID | Task | Est. | Dependencies | Verification |
|----|------|------|-------------|--------------|
| A-1 | 命令注入 pre-filter | 2h | — | 注入样例拒绝，合法命令通过 |
| A-2 | sandbox env whitelist | 1.5h | — | 敏感 env 不透传，白名单按策略生效 |
| A-3 | 路径级约束补强 | 3h | A-1 | 写入路径 / 重定向路径 / resolve 校验一致 |
| A-4 | 风险登记册同步 | 0.5h | A-1~A-3 | 新风险项入册，复审日期明确 |
| A-5 | Batch A 全量回归 | 1h | A-1~A-4 | gate + 相关测试全绿 |

---

## 3. 文件级修改清单

### A-1 命令注入 pre-filter

#### 主要文件
- [core/process.py](../core/process.py)
- [tools/_test_cmd_injection_patterns.py](../tools/_test_cmd_injection_patterns.py)
- [tools/_check_cmd_injection_gate.sh](../tools/_check_cmd_injection_gate.sh)
- [tools/_quality_gate.sh](../tools/_quality_gate.sh)

#### 修改点
1. 在 `core/process.py` 的 shell 执行入口增加 pre-filter。
2. 扩充 `tools/_test_cmd_injection_patterns.py` 的恶意样例库。
3. `tools/_check_cmd_injection_gate.sh` 保持为最薄 gate wrapper。
4. `tools/_quality_gate.sh` 中 `CMD-INJ` 失败信息分类更清晰。

#### 重点验证
- `$(...)`、反引号、`${...}` 明确拒绝
- 普通 shell 命令不被误伤
- `FORGE_SANDBOX=docker` 时 gate 正常工作

---

### A-2 sandbox env whitelist

#### 主要文件
- [core/process.py](../core/process.py)
- [tools/_check_sandbox_config.py](../tools/_check_sandbox_config.py)
- [tools/_check_sandbox_config.sh](../tools/_check_sandbox_config.sh)
- [tools/_check_sandbox_isolation.sh](../tools/_check_sandbox_isolation.sh)

#### 修改点
1. `core/process.py` 中增加 env whitelist 过滤逻辑。
2. 明确允许透传的变量集合。
3. `_check_sandbox_config.py` 校验资源限制能否解析。
4. `_check_sandbox_isolation.sh` 校验 Docker 是否可达。

#### 重点验证
- 默认 env 不透传
- `FORGE_*` / `LANGFUSE_*` / `PATH` / `HOME` 按策略透传
- 敏感变量不进入容器

---

### A-3 路径级约束补强

#### 主要文件
- [core/base.py](../core/base.py)
- [hitl/pipeline.py](../hitl/pipeline.py)
- [agent/core.py](../agent/core.py)
- [server/services/agent_service.py](../server/services/agent_service.py)

#### 修改点
1. 写入目标路径纳入统一检查。
2. shell 重定向目标也纳入检查。
3. `Write/Edit/Bash` 使用统一的 resolve + relative_to 校验。
4. 对敏感路径 fail closed。

#### 重点验证
- 允许合法路径写入
- 拒绝路径穿越
- 拒绝 shell 间接写敏感目录

---

### A-4 风险登记册同步

#### 主要文件
- [docs/RISK_REGISTER.md](RISK_REGISTER.md)
- [docs/PHASE11_HARNESS_MATURITY_PLAN.md](PHASE11_HARNESS_MATURITY_PLAN.md)

#### 修改点
新增风险项：
- 命令注入 pre-filter 不完整
- sandbox env 透传过宽
- 路径级约束不完整

#### 重点验证
- 每项风险有升级条件
- 每项风险有复审日期

---

## 4. 测试方案

### A-1 Tests
- 注入样例全部拒绝
- 合法 shell 命令通过
- gate 脚本输出稳定

### A-2 Tests
- 宿主环境敏感变量不出现在 sandbox 内
- 白名单变量保留
- Docker 不可用时失败原因可读

### A-3 Tests
- 路径穿越写入被拒绝
- 合法路径写入通过
- shell 重定向目标被检查

### A-4 Tests
- 风险条目生成正确
- 复审信息完整

---

## 5. 回归验收标准

- [ ] 命令注入样例全部被拒绝
- [ ] sandbox env whitelist 生效
- [ ] 路径级约束覆盖写入与重定向
- [ ] 风险登记册补齐对应条目
- [ ] 相关 gate 全绿

---

## 6. Risk Notes

### 已知取舍

- 这里先做“可验证的实用防线”，不追求一次性上到 Claude Code 级 AST 安全分析。
- shell 安全会先以 pre-filter + path check + sandbox 限制构成三层边界。

### 风险升级触发条件

- 新 shell 入口绕过统一检查
- env whitelist 增加过快导致默认泄漏
- 路径约束在新工具上失效

---

## 7. Implementation Sequence

```
A-1: core/process.py pre-filter + injection tests
A-2: sandbox env whitelist + sandbox scripts
A-3: path constraint tightening in tool/pipeline entrypoints
A-4: risk register update
A-5: regression + gate run
```

---

*Batch A ready for review.*
