# Analysis Mode — 只读分析

## 概念

Analysis mode 是 agent 的**只读分析**模式。agent 可以读文件、搜索、浏览，但不能修改任何文件。

## 流程

```
POST .../messages  { prompt: "分析这个项目的依赖关系", intent: "analysis" }
  │
  ▼
SessionRuntime 以 analysis intent 启动 agent
  │
  ▼
Agent 工具集限制为只读：Read / Grep / Glob / WebSearch / WebFetch
  │  （禁止：Write / Edit / Bash / GitCommit 等写操作）
  │
  ▼
执行完成，返回分析报告
```

## 与 Edit mode 的对比

| | Edit mode（默认） | Analysis mode |
|---|---|---|
| intent | `"edit"` | `"analysis"` |
| 写工具 | 可用 | 禁用 |
| Bash | 可用 | 禁用 |
| Git commit | 可用 | 禁用 |
| 返回 | 修改文件 + 摘要 | 分析报告 |
| 审批 | 可选 | 不需要 |

## 用法

```json
POST /api/sessions/{id}/messages
{ "prompt": "分析 src/auth/ 的依赖关系",
  "intent": "analysis" }
```

## 行为差异

Agent 在 analysis mode 下的行为变化：

1. **不检查 git diff** — 因为是只读，没有文件变更需要验证
2. **不生成 patch** — RunResult.patch 为 null
3. **Final summary 是分析报告** — 不是修改总结
4. **VerificationStatus = NOT_APPLICABLE** — 不需要验证

## 前端展示

Analysis 模式的 session 在 UI 上显示标签：

```
Session: "分析依赖关系" [analysis]
Agent: explore · 42 steps · 28000 tokens

Summary: 项目依赖分析报告...
┌─ 直接依赖: 12 个
├─ 间接依赖: 47 个
└─ 循环依赖: 2 处（src/auth/login.py → src/utils.py → src/auth/login.py）
```
