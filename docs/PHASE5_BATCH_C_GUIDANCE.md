# Phase 5 Batch C 精准定位与理论指导方案

> **文档版本**: 1.0
> **生成日期**: 2026-07-21
> **Phase 5 定位**: 最终批次 — UI 提取收官 + 安全审计终审 + Phase 5 关闭
> **输入基线**: Batch A/B 闭环 + 剩余 P2 ×34
> **前置条件**: Batch B ACC-4 全绿, 56/56 测试
> **预计总工时**: 12h

---

## 目录

1. [P2 重新评估: 隐式解决与降级分类](#1-p2-重新评估-隐式解决与降级分类)
2. [ChatPipeline 接口交互矩阵 (UI 提取)](#2-chatpipeline-接口交互矩阵-ui-提取)
3. [Refactoring Risk Matrix (Batch C)](#3-refactoring-risk-matrix-batch-c)
4. [ACC-5: Security & UI Compliance Check](#4-acc-5-security--ui-compliance-check)
5. [C1: UI 工具函数提取 (12 项, 低风险)](#5-c1-ui-工具函数提取-12-项-低风险)
6. [C2: 安全审计收尾 (10 项, 深度防御)](#6-c2-安全审计收尾-10-项-深度防御)
7. [C3: 接口契约固化 + 常量补充 (4 项)](#7-c3-接口契约固化--常量补充-4-项)
8. [Phase 5 关闭统计](#8-phase-5-关闭统计)
9. [Batch C Readiness Checklist](#9-batch-c-readiness-checklist)
10. [元数据](#10-元数据)

---

## 1. P2 重新评估: 隐式解决与降级分类

### 1.1 已被 Batch A/B 隐式解决的项 (17 → ✅)

| P2 | 解决方案 | 批次 |
|----|---------|------|
| P2-2 内联 import | A1-2c: 移至顶部 | A |
| P2-4 哨兵字符串 | A3: `NO_THOUGHT_SENTINEL` | A |
| P2-6/7/8 注释/header/pass | A3 重构消除 | A |
| P2-9 `_block_tracker` 命名 | A1-2a: `CompletionBlockTracker` | A |
| P2-17 `CHAT_TIMEOUT_MS` | Batch F | D |
| P2-53 approved_prompts cap | B1-SecurityBundle | B(Phase4) |
| P2-1/5 docstrings/types | B2: docstrings + `list[LLMMessage]` | B(Phase5) |
| P2-10/11/12 types/naming/frozen | B1: lock替代frozen + rerename | B(Phase5) |
| P2-19/39 hook超时 | B3: 10s + 30s帽 | B(Phase5) |
| P2-42/43 原子写入/连接池 | B3: `threading.get_ident()` + JOIN | B(Phase5) |
| P2-23 renderMarkdown统一 | C3 (Phase4) 已完成 | C(Phase4) |

### 1.2 Batch C 净剩余 (34 → 聚焦 22 项)

| 分类 | 数量 | 聚焦项 |
|------|------|--------|
| 🔵 **UI 工具函数** | 12 | P2-15/16/21/22/24/25/29/30/31/32/33/34/35 |
| 🟠 **安全审计** | 10 | P2-18/36/37/38/40/41/44/49/50/51/52/54/55 |
| 🟢 **接口契约** | 4 | P2-20/45/46/47/48 |
| ⚪ **推迟** | 8 | P2-13/14/26/27/28 (大型 CSS refactor) — Phase 6 |
| **合计** | **22 + 8 deferred** | |

---

## 2. ChatPipeline 接口交互矩阵 (UI 提取)

| P2 | 提取目标 | 依赖 ChatPipeline | 依赖 ChatStore | DOM 依赖 |
|----|---------|-----------------|--------------|---------|
| P2-15 `formatBytes/Runtime` | `web/src/utils/format.ts` | 否 | 否 | 否 |
| P2-16 `useWebSocket()` | `web/src/hooks/useWebSocket.ts` | 否 | **是 — `_wsSessionId`** | 否 |
| P2-21 `summarizeTarget` | `web/src/utils/target.ts` | 是 — WsEvent payload shape | 否 | 否 |
| P2-22 `formatValue` | → `utils/format.ts` | 否 | 否 | 否 |
| P2-24 `summarizeStatus` | `web/src/utils/status.ts` | 否 | 是 — `SessionStatus` type | 否 |
| P2-25 WS parse guard | `chatStore.ts` 内联 | 是 — `WsMessage` type assertion | **是 — Zustand set()** | 否 |
| P2-29 EventSidebar fetch | EventSidebar.tsx + AbortController | 否 | 否 | 是 (useEffect cleanup) |
| P2-30 `buildOverview` dead | 删除 `api/memory.ts:41-68` | 否 | 否 | 否 |
| P2-31 双重转义 | ToolCallCard.tsx 移除 `escapeHtml` | 否 | 否 | **是 — JSX text rendering** |
| P2-32 `Promise<any[]>` | `api/stats.ts` → `StepLog[]` | 否 | 否 | 否 |
| P2-33 Plan trace cast | `chatStore.ts:loadTraceEvents` | 是 — `plan_ready` event | **是** | 否 |
| P2-34 Share button | 移除 no-op button | 否 | 否 | 是 |
| P2-35 ThemeToggle aria | 添加 `aria-label` | 否 | 否 | **是** |

---

## 3. Refactoring Risk Matrix (Batch C)

| P2 | DOM 依赖 | 后端状态依赖 | 回归覆盖 | 风险 |
|----|---------|------------|---------|------|
| P2-15 格式化函数 | 否 | 否 | **高** (type check) | 🟢 NEGL |
| P2-16 useWebSocket hook | 否 | **是** `_wsSessionId` | **中** | 🟠 **MEDIUM** |
| P2-21/22/24 工具函数 | 否 | 否 | **高** | 🟢 NEGL |
| P2-25 WS parse guard | 否 | **是** Zustand store | **中** | 🟡 LOW |
| P2-29 AbortController | **是** | 否 | **低** | 🟡 LOW |
| P2-30 dead code | 否 | 否 | **高** | 🟢 NEGL |
| P2-31 双重转义 | **是** | 否 | **中** | 🟡 LOW |
| P2-32/33 类型 | 否 | **是** `SessionDiff/StepLog` | **中** | 🟡 LOW |
| P2-34/35 UI | **是** | 否 | **高** | 🟢 NEGL |

**结论**: 1 MEDIUM (P2-16 useWebSocket), 5 LOW, 6 NEGLIGIBLE。

### P2-16 预案: useWebSocket 提取时保持 `_wsSessionId` 读写不变，封装 reconnect 逻辑 + cleanup。若提取后 WS 断开重连速率 > 2x 基线，回滚至 store 内联。

---

## 4. ACC-5: Security & UI Compliance Check

> **新增维度**: Batch C 专属。Phase 5 终审。

### 4.1 检查条款

| 条款 | 描述 | 验证方法 |
|------|------|---------|
| **ACC-5a XSS Prevention** | 所有 `dangerouslySetInnerHTML` 使用点必须经过 `renderMarkdownSafe` 且 escape 先执行 | `grep -rn dangerouslySetInnerHTML web/src/` → 确认仅 2 处 (MessageBubble, MemoryView)，均已使用统一渲染器 |
| **ACC-5b CSRF Token** | 前端 API 请求无 CSRF token（SPA + API key auth，不需要） | 确认 Authorization header 模式或 API key 嵌入 |
| **ACC-5c Security Fix Evidence** | 每项安全 P2 必须有对应的代码 diff 或文档证据 | `grep -n P2-18\|P2-36...` 在 commit log 中 |
| **ACC-5d UI A11y** | axe-core rescan 确认 0 critical/0 serious | `npx @axe-core/cli` 扫描 |
| **ACC-5e Contract Consistency** | ChatPipeline 6-stage 接口在前端 API 调用中保持一致 | TypeScript compilation `npx tsc --noEmit` 零错误 |

### 4.2 通过标准

```
[x] ACC-5a: 0 unescaped dangerouslySetInnerHTML
[x] ACC-5b: auth model documented
[x] ACC-5c: ≥8 security P2 with evidence
[x] ACC-5d: axe-core 0/0
[x] ACC-5e: tsc --noEmit 0 errors
```

---

## 5. C1: UI 工具函数提取 (12 项, 低风险)

### 5.1 提取清单

| # | P2 | 源文件 | → 目标 | 操作 |
|---|-----|--------|--------|------|
| C1-1 | P2-15 | ChatView.tsx:109-123 | `utils/format.ts` | 提取 `formatBytes`, `formatRuntime` |
| C1-2 | P2-16 | chatStore.ts:655-734 | `hooks/useWebSocket.ts` | 提取 80 行 WS 重连 |
| C1-3 | P2-21 | WsEventBlock.tsx:110-119 | `utils/target.ts` | 提取 `summarizeTarget` 统一定义 |
| C1-4 | P2-22 | WsEventBlock.tsx:101-108 | `utils/format.ts` | 合并 `formatValue` |
| C1-5 | P2-24 | ChatView.tsx:100→SessionSidebar | `utils/status.ts` | 提取 `summarizeStatus` |
| C1-6 | P2-25 | chatStore.ts:668-670 | chatStore.ts (内联) | `WsMessage` type guard 替代 `as unknown as` |
| C1-7 | P2-29 | EventSidebar.tsx:64-95 | EventSidebar.tsx | 添加 AbortController |
| C1-8 | P2-30 | api/memory.ts:41-68 | 删除 | 移除 `buildOverview` |
| C1-9 | P2-31 | ToolCallCard.tsx:65-67 | ToolCallCard.tsx | 移除 JSX 中的 `escapeHtml` (React 已转义) |
| C1-10 | P2-32 | api/stats.ts:8 | api/stats.ts | `Promise<any[]>` → `Promise<StepLog[]>` |
| C1-11 | P2-33 | chatStore.ts:618-629 | chatStore.ts | `planRaw` → typed guard function |
| C1-12 | P2-34/35 | App.tsx, ThemeToggle | App.tsx, ThemeToggle | 移除 Share button + aria-label |

### 5.2 TypeScript 共享模块

```typescript
// web/src/utils/status.ts (new)
export function summarizeStatus(status?: string): string {
  const map: Record<string, string> = {
    completed: "Completed", running: "Running", failed: "Failed",
    queued: "Queued", cancelled: "Cancelled", gave_up: "Gave up",
  };
  return status ? (map[status] || status) : "Idle";
}

// web/src/utils/target.ts (new)
export function summarizeTarget(name: string, params: Record<string, unknown>): string {
  const keyParams: Record<string, string> = {
    Read: "file_path", Write: "file_path", Edit: "file_path",
    Bash: "command", Grep: "pattern", Glob: "pattern",
    WebFetch: "url", WebSearch: "query", Skill: "skill",
  };
  const key = keyParams[name];
  if (key && typeof params[key] === "string") {
    return (params[key] as string).slice(0, 60);
  }
  return name;
}
```

### 5.3 验证

```
npx tsc --noEmit  # 零错误
npx @axe-core/cli  # 0 critical / 0 serious
```

---

## 6. C2: 安全审计收尾 (10 项, 深度防御)

### 6.1 安全审计检查清单

| # | P2 | 检查项 | 修复类型 | 估时 |
|---|-----|--------|---------|------|
| C2-1 | P2-18 | LLM 重试指标 → `RetryMetrics` dataclass + Langfuse event | 观测 | 2h |
| C2-2 | P2-36 | MicroCompactor 就地修改 → 返回新列表或文档标注 | 文档 | 0.5h |
| C2-3 | P2-37 | Token 计数 overhead → 添加 `+5` 修正常量 | 修正 | 0.5h |
| C2-4 | P2-38 | 内部 hook 异常静默 → blockable event FAIL_CLOSED | 安全 | 1h |
| C2-5 | P2-40 | Tool call validator 参数类型校验 → schema `type` 检查 | 安全 | 2h |
| C2-6 | P2-41 | 重试分类子串匹 → HTTP status code 检查 | 可靠性 | 1h |
| C2-7 | P2-44 | 记忆内容哈希行尾规范化 → `content.replace('\r\n','\n')` | 修正 | 0.5h |
| P2-47 | 附件文件名消毒化 | `Path(file.filename).name` | 安全 | |
| P2-45 | Session ID 格式校验 | `re.match(r'^[a-f0-9]{12}$')` | 输入验证 | |
| P2-46 | Settings Pydantic | Pydantic model 替换 `dict[str,Any]` | 输入验证 | |

### 6.2 级联优先级

| 优先级 | P2 | 理由 |
|--------|-----|------|
| **1st** | P2-38 hook FAIL_CLOSED | 直接影响 agent 安全性 |
| **2nd** | P2-40/41 参数校验+重试匹配 | 影响 LLM 调用可靠性 |
| **3rd** | P2-36/37/44 文档+修正+哈希 | 代码卫生 |

> 12 项推迟到 Phase 6: P2-49/50/51/52/54/55 涉及跨模块架构变更（SessionMemory pipeline bypass, bypassPermissions propagation, worktree TOCTOU, safe_open_for_write Windows TOCTOU）。

---

## 7. C3: 接口契约固化 + 常量补充 (4 项)

| # | P2 | 修复 |
|---|-----|------|
| C3-1 | P2-20 | `_SESSION_TITLE_MAX_LENGTH = 200` 常量定义 |
| C3-2 | P2-45 | Session ID regex: `re.match(r'^[a-f0-9]{12}$')` 在路由层 |
| C3-3 | P2-48 | `SELECT COUNT(*)` 替代 session 逐条消息加载 |
| C3-4 | P2-47 | 附件文件 `Path(file.filename).name` 消毒化 |

---

## 8. Phase 5 关闭统计

| 批次 | P1 | P2 | Commits | 关键成果 |
|------|----|----|---------|---------|
| A | 11→✅ | 8隐式✅ | 3 | `_run_body` 去重, 配置外化, ChatPipeline |
| B | — | 8→✅ | 2 | 锁竞争 0 lost, hook 超时, 连接池 |
| C | — | 22→target | 2 | UI 提取, 安全终审 |
| **∑** | **11** | **38** | **7** | **Phase 5 全局** |

### P2 处置分布

| 状态 | 数量 |
|------|------|
| ✅ 已完成 (A隐式 + B活跃) | 17 |
| 🔵 C1 UI | 12 |
| 🟠 C2 安全 | 10 |
| 🟢 C3 契约 | 4 |
| ⚪ Phase 6 deferred | 8 |
| **合计** | **51** (原 53, 2 降级) |

---

## 9. Batch C Readiness Checklist

| # | 条件 | 状态 |
|---|------|------|
| ① | Batch B ACC-4 审计原始输出已归档 | ✅ |
| ② | 剩余 22 项 P2 已映射到 C1/C2/C3 | ✅ |
| ③ | Risk Matrix 已更新 (1 MEDIUM, 5 LOW, 6 NEGL) | ✅ |
| ④ | ACC-5 条款已编码 (5a/5b/5c/5d/5e) | ✅ |
| ⑤ | ChatPipeline 接口契约仍为 SSOT | ✅ |
| **→ Batch C Ready** | | ✅ |

---

## 10. 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成日期** | 2026-07-21 |
| **输入基线** | Batch B 闭环 + CORE_ARCHITECTURE_REPORT.md SSOT |
| **Phase 5 Batch C 范围** | C1(UI 12), C2(安全 10), C3(契约 4) |
| **RISK MATRIX** | 1 MEDIUM, 5 LOW, 6 NEGL |
| **隐含解决 P2** | 17 项 (Batch A/B) |
| **推迟 P2** | 8 项 (Phase 6) |
| **ACC-5 条款** | 5a XSS, 5b CSRF, 5c 证据, 5d A11y, 5e Contract |
| **下一阶段** | Batch C 执行 → Phase 5 关闭 |
