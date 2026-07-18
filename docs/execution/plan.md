# Plan Mode — 执行规划与审批

## 概念

Plan mode 是 agent 在**执行前**先生成结构化计划的模式。用户审批计划后，agent 按计划执行。

## 流程

```
User: "重构 auth 模块"
   │
   ▼
Agent 进入 plan mode
   │
   ▼
Agent 生成 PlanContract（步骤列表 + 文件 + 依赖）
   │
   ▼
等待审批 ──→ POST .../approve ──→ Agent 按计划执行
   │              │
   │              └── POST .../reject ──→ Agent 重新规划
   │
   ▼
执行完成
```

## API

### POST /api/sessions/{id}/approve

批准待审批的项目。

```json
// Request
{ "comment": "Looks good" }

// Response 200
{ "approved": true }
```

### POST /api/sessions/{id}/reject

拒绝待审批的项目。

```json
// Request
{ "reason": "Need more details on step 3" }

// Response 200
{ "approved": false }
```

### GET /api/sessions/{id}/approvals

列出待审批项。

```
Response 200:
[{ "type": "plan_proposal", "summary": "...",
   "created_at": "..." }]
```

## PlanContract（待实现）

```python
@dataclass
class PlanContract:
    """结构化执行计划。"""
    title: str
    steps: list[PlanStep]
    estimated_files: list[str]
    risk_level: str  # "low" | "medium" | "high"

@dataclass
class PlanStep:
    id: str
    description: str
    action: str       # "read" | "edit" | "create" | "delete" | "verify"
    target_file: str | None
    depends_on: list[str]  # 前置步骤 id
```

前端渲染：

```
Plan: 重构 auth 模块 (risk: medium)
  ├─ [1] 分析当前 auth 实现 → read src/auth/*
  ├─ [2] 新增 JWT 中间件    → create src/auth/jwt.py (depends: [1])
  └─ [3] 更新路由注册       → edit src/routes.py (depends: [2])
```
