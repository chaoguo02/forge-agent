# React 前端审计修复计划

> 25 defects found. Prioritized by severity × impact × fix complexity.

## Batch Plan

### Batch A (🔴 Critical — 3 defects, 3 files)

| # | Defect | Root Cause | Fix |
|---|--------|-----------|-----|
| 1 | loadMessages clobbers traceEvents | Parallel fetches, set() replaces timeline | Merge instead of replace; use Promise.all |
| 2 | wsCloseInfo false disconnect | onopen doesn't clear wsCloseInfo | Clear wsCloseInfo in onopen |
| 3 | Tab switch kills WS | ChatView conditional mount | Move WS lifecycle to App level |

### Batch B (🟡 High — 4 defects, 3 files)

| # | Defect | Fix |
|---|--------|-----|
| 4 | WS error silent | set({ error: "Connection error" }) in onerror |
| 6 | SessionTree re-fetches on every event | Debounce to 2s, only on subagent events |
| 7 | Tool count doubled | Remove `observation` from tool count handler |
| 11 | isRunning stuck | Add 5min timeout watchdog in sendChat |

### Batch C (🟡 High — 3 defects, 3 files)

| # | Defect | Fix |
|---|--------|-----|
| 5 | EventSidebar filters dead | Add onClick handlers + filter state |
| 8 | EventSidebar stats re-fetch storm | Debounce to 5s |
| 10 | No error boundary | Wrap App in ErrorBoundary |

### Batch D (🟢 Medium — 4 defects, 3 files)

| # | Defect | Fix |
|---|--------|-----|
| 14 | backgroundAgents leak | Prune completed entries after 5min |
| 15 | updateSettings raw fetch | Use apiPost |
| 18 | SubagentDetail wrong message | Distinguish load error vs empty |
| 23 | WsStatusEvent type as string | Use literal union type |

### Deferred

| # | Defect | Reason |
|---|--------|--------|
| 9 | PlanView clear() cross-session | Needs session-scoped store redesign |
| 12 | File upload non-functional | Needs FormData + backend upload handling |
| 13 | SessionSidebar batch reset | Needs persistent selection model |
| 16 | ToolApprovalCard JSON.stringify | Memoization — low perf impact |
| 19 | MessageBubble XSS | Already mitigated by escapeHtml |
| 20 | Composer touch events | Low impact |
| 21 | EventSidebar fake timestamps | Use real timestamps from events |
| 22 | WsMeta unused | Cleanup only |
| 24 | diff_id=0 bug | Edge case |
| 25 | SessionSidebar error not rendered | Needs UI redesign |
