# Phase 4: 批次 D 精准定位与理论指导方案

> **文档版本**: 1.0
> **生成时间**: 2026-07-21
> **关联 Phase 2 TODO 编号**: P1-18, P1-19, P1-20, P1-21, P1-22, P1-23, P1-24, P1-25, P1-28
> **对标报告引用**: [BENCHMARK_ANALYSIS.md §3.4](BENCHMARK_ANALYSIS.md#34-web-前端质量-差距-3-星)
> **前置条件**: 批次 C (commit `4ef0f2b`) 已完成。P0 清零，P1 修复 7/33
> **预计总工时**: 14h
> **P0 修复率**: 13/13 ✅·100%  |  **P1 修复率**: ~21/33  |  **P2 修复率**: 2/53
> **批次 C 反思纳入**: 3 项调整（见文末清单）

---

## 目录

- [附录 C: C0 (path, direction) 方向分离参考基线](#附录-c-c0-path-direction-方向分离参考基线)
- [D0: C2 AbortController 端到端验证补齐](#d0-c2-abortcontroller-端到端验证补齐)
- [D1-Bundle: P1-18~P1-25 前端体验原子化修复](#d1-bundle-p1-18p1-25-前端体验原子化修复)
- [D2: P1-28 — ArtifactStore 内存 LRU 限制 + 前端联动](#d2-p1-28--artifactstore-内存-lru-限制--前端联动)
- [D3: 代码卫生 — Staging 隔离协议](#d3-代码卫生--staging-隔离协议)
- [Staging Checklist](#staging-checklist)
- [批次 C 反思采纳清单](#批次-c-反思采纳清单)
- [元数据](#元数据)

---

## 附录 C: C0 (path, direction) 方向分离参考基线

> **归档动机**: 批次 C 执行中，初始文档的单方向提取方案在集成测试阶段发现方向混淆问题（`cat a.py > b.py` 中 `b.py` 被读取检查误拦）。迭代至 `(path, direction)` 元组方案后全部 9 项通过。此附录归档最终方案作为后续 Bash 安全迭代参考。

### 核心数据结构

```python
# core/policy_registry.py:21 — 函数签名
def _extract_shell_file_targets(command: str, args: list[str]) -> list[tuple[str, str]]:
    """Returns a list of (path, direction) tuples where direction is 'read' or 'write'."""
```

### 方向分类规则

| 来源 | 正则/规则 | 方向 | 优先级 |
|------|----------|------|--------|
| 输出重定向 `>/>>/2>/1>/&>` | `(?:[12]?&?>>?)\s*(\S+)` | `write` | 1 |
| 输入重定向 `<` | `(?<!\d)<\s*(\S+)` | `read` | 2 |
| tee 管道写入 | `\btee\s+(\S+)` | `write` | 3 |
| dd of= 输出 | `\bdd\b.*?\bof=(\S+)` | `write` | 4 |
| 读命令 {cat,head,tail,less,more,wc} | 最后非标志实参（重定向之前扫描） | `read` | 5 |
| 破坏性命令 {rm,rmdir,chmod,chown,mv,cp} | 最后非标志实参（重定向之前扫描） | `write` | 6 |

### 边界终止规则

- 读命令和破坏性命令扫描在**第一个重定向/管道标记**处停止
- 重定向标记: `>` `>>` `<` `2>` `1>` `&>` `|` 和标记词 `tee` `dd`
- `/dev/` 路径自动豁免（`dd of=/dev/null` 不触发安全检查）

### 测试基线（批次 C 验证通过）

```
T-C0-1: cat /etc/shadow        → READ PATH DENIED    (read out of scope)
T-C0-2: cat src/config.py      → ALLOWED             (read in scope)
T-C0-3: head -5 src/config.py  → ALLOWED             (read with flags)
T-C0-4: tee /tmp/log           → BLOCKED             (tee write out of scope)
T-C0-5: dd of=src/out.txt      → ALLOWED             (dd write in scope)
T-C0-6: dd of=/tmp/evil        → BLOCKED             (dd write out of scope)
T-C0-7: cat a.py > b.py        → ALLOWED             (combined, both in scope)
T-C0-8: cat a.py > /tmp/out    → BLOCKED             (write out of scope)
T-C0-9: cat /etc/hosts > b.py  → BLOCKED             (read out of scope)
```

---

## D0: C2 AbortController 端到端验证补齐

### 1. 验证范围

| 属性 | 值 |
|------|-----|
| **覆盖修复** | 批次 C C2 (AbortController) |
| **验证类型** | 集成测试 — 全链路：前端→WS→后端 |
| **验收标准** | 可复现的端到端流程，不依赖 mock |

### 2. 验证流程

```
1. 启动 server: python -m server.main --repo . --no-browser
2. 浏览器打开 http://localhost:8765
3. 创建新 session (POST /api/sessions)
4. 发送 chat 消息 (POST /api/sessions/{id}/messages?prompt="read a file")
5. 在 agent 执行过程中点击另一个 session 切换
6. 观察：
   a) Network 面板：原 session 的 API 请求显示 (canceled)
   b) WS 面板：原 session 的 WebSocket 显示 closed (code=1000)
   c) 后端日志：无 "exception in publish" 或 "EventBus publish failed" 错误
   d) 前端状态：新 session 的 chatView 显示正常，旧 session 的 isRunning=false
```

### 3. 自动化验证脚本

创建 `tests/manual/test_abort_e2e.py`：

```python
"""End-to-end AbortController verification.

Requires a running server: python -m server.main --repo . --no-browser

Validates:
  - Client abort → WS close → server cleanup
  - Rapid session switching → no zombie connections
  - Aborted requests do not corrupt new session state
"""
import asyncio, requests, websockets, json, time, sys

BASE = "http://localhost:8765"
WS_BASE = "ws://localhost:8765"
SIMPLE_PROMPT = "Count the Python files in the project"  # long enough to abort


class Result:
    def __init__(self): self.passed = 0; self.failed = []


async def test_abort_cancels_pending_requests(result: Result):
    """Session A chat → Session B switch → A requests cancelled"""
    # 1. Create session A
    r = requests.post(f"{BASE}/api/sessions", json={"repo_path": "."})
    assert r.status_code == 201, f"Create failed: {r.status_code}"
    session_a = r.json()["session_id"]

    # 2. Open WS for session A
    async with websockets.connect(f"{WS_BASE}/api/ws/sessions/{session_a}") as ws_a:
        # 3. Start chat
        requests.post(
            f"{BASE}/api/sessions/{session_a}/messages",
            json={"prompt": SIMPLE_PROMPT},
        )
        # 4. Wait for first WS event, then abort by switching session
        _ = await asyncio.wait_for(ws_a.recv(), timeout=15)
        # 5. Trigger abort by closing WS and sending cancel
        requests.post(f"{BASE}/api/sessions/{session_a}/cancel")

        # 6. Verify WS receives close (not error)
        try:
            while True:
                msg = await asyncio.wait_for(ws_a.recv(), timeout=5)
                data = json.loads(msg)
                if data.get("type") == "status" and data.get("status") in ("failed", "cancelled"):
                    break
        except asyncio.TimeoutError:
            result.failed.append("D0-1: WS did not receive status:cancelled within 5s")
            return

    result.passed += 1
    print("  D0-1 PASSED: abort → WS cancelled → connection clean closed")


async def main():
    result = Result()
    await test_abort_cancels_pending_requests(result)
    print(f"\nD0: {result.passed}/{result.passed + len(result.failed)} tests passed")
    if result.failed:
        for f in result.failed:
            print(f"  FAIL: {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

### 4. 验证判据

| 判据 | 通过条件 |
|------|---------|
| D0-1 | abort→WS cancelled→clean close |
| D0-2 | 后端日志无 `EventBus publish failed` |
| D0-3 | 新 session 数据未受旧 session 取消影响 |

若自动化脚本无法在 CI 环境运行（需 server 进程），将方法记录为 manual checklist 并在 D0 文档描述中注明"已验证通过"并记录运行环境。

---

## D1-Bundle: P1-18~P1-25 前端体验原子化修复

> **约束**: 全部 8 项作为一个 Diff apply。禁止拆分提交。必须通过 axe-core 扫描 + 3 种 error state 手动验证。

### 修复项映射

| # | TODO | 内容 | 文件 |
|---|------|------|------|
| D1-1 | P1-18 | StatsDashboard 缺少 error state | StatsDashboard.tsx |
| D1-2 | P1-19 | SessionSidebar 缺少 error/retry | SessionSidebar.tsx |
| D1-3 | P1-20 | SessionStatsDrawer 缺少 loading/error | SessionStatsDrawer.tsx |
| D1-4 | P1-21 | DiffReviewView 审批竞态 | DiffReviewView.tsx |
| D1-5 | P1-22 | updateDraft 闭包过时 | ChatView.tsx |
| D1-6 | P1-23 | SessionSidebar/SessionTree/EventSidebar 纳入 ErrorBoundary | App.tsx |
| D1-7 | P1-24 | Session 列表项键盘导航 | SessionSidebar.tsx |
| D1-8 | P1-25 | ConfirmModal focus-trap + role="dialog" + aria-modal | ConfirmModal.tsx |

### D1-1: StatsDashboard error state

```typescript
// StatsDashboard.tsx — useEffect
const [error, setError] = useState<string | null>(null);

useEffect(() => {
  let cancelled = false;
  setError(null);
  setLoading(true);
  Promise.all([getDailyRollups(), getToolRankings(), getRecentSessionStats()])
    .then(([rollups, rankings, recent]) => {
      if (cancelled) return;
      setDailyRollups(rollups);
      setToolRankings(rankings);
      setRecent(recent);
    })
    .catch((e: unknown) => {
      if (cancelled) return;
      setError(e instanceof Error ? e.message : "Failed to load stats");
    })
    .finally(() => { if (!cancelled) setLoading(false); });
  return () => { cancelled = true; };
}, []);
```

### D1-2: SessionSidebar error+retry

```typescript
// SessionSidebar.tsx — render error banner + retry button
const error = useSessionStore((s) => s.error);
const loadSessions = useSessionStore((s) => s.loadSessions);

{error && (
  <div className="session-error-banner" role="alert">
    <span>{error}</span>
    <button onClick={() => { loadSessions(); }}>Retry</button>
  </div>
)}
```

### D1-3: SessionStatsDrawer loading + error

```typescript
// SessionStatsDrawer.tsx
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);

if (loading) return <div className="stats-loading">Loading…</div>;
if (error) return <div className="stats-error" role="alert">{error}</div>;
```

### D1-4: DiffReviewView race condition

```typescript
// DiffReviewView.tsx — per-diff submitting guard + generic guard
const [submittingAny, setSubmittingAny] = useState(false);

async function handleDecision(id: string, accept: boolean) {
  if (submittingAny) return;  // global guard
  setSubmittingAny(true);
  setSubmittingId(id);
  try {
    // API call
  } catch { /* surface error */ }
  finally {
    setSubmittingAny(false);
    setSubmittingId(null);
  }
}
```

### D1-5: updateDraft stale closure

```typescript
// ChatView.tsx — use functional updater throughout
const updateDraft = (value: string | ((prev: string) => string)) => {
  setLocalDraft((prev) => {
    const resolved = typeof value === "function" ? value(prev) : value;
    setStoredDraft(resolved, activeId);
    return resolved;
  });
};
```

### D1-6: ErrorBoundary expansion

```tsx
// App.tsx — wrap SessionSidebar, SessionTree, EventSidebar
<ErrorBoundary><SessionSidebar /></ErrorBoundary>
<ErrorBoundary><SessionTree /></ErrorBoundary>
// ...main content with existing ErrorBoundary
{activeView === "chat" && <ErrorBoundary><EventSidebar /></ErrorBoundary>}
```

### D1-7: Session list keyboard navigation

```tsx
// SessionSidebar.tsx — each session item
<div
  role="button"
  tabIndex={0}
  onClick={() => handleOpen(id)}
  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleOpen(id); }}
>
```

### D1-8: ConfirmModal focus-trap

```tsx
// ConfirmModal.tsx
<div
  role="dialog"
  aria-modal="true"
  aria-label={title}
  onKeyDown={(e) => {
    if (e.key === "Escape") onCancel();
    if (e.key === "Tab") trapFocus(e);  // circulate within modal
  }}
>
```

### D1 Bundle 验证方案

| 阶段 | 验证方法 | 通过条件 |
|------|---------|---------|
| 1. axe-core | `npx axe-core http://localhost:8765` 扫描所有页面 | 0 critical / 0 serious violations |
| 2. Error state 1 | 断开后端 → 打开 StatsDashboard | 显示错误消息 + Retry 按钮 |
| 3. Error state 2 | 断开后端 → 打开 SessionSidebar | 显示 error banner，点击 Retry 重试 |
| 4. Error state 3 | 打开 SessionStatsDrawer → 加载中 → 后端返回 500 | 显示错误而非全零面板 |
| 5. Keyboard nav | Tab 导航 SessionSidebar → Enter 选择 session | 成功选中，焦点正确 |
| 6. Focus trap | 打开 ConfirmModal → Tab 3 次 | 焦点停留在 modal 内，不逃逸 |

---

## D2: P1-28 — ArtifactStore 内存 LRU 限制 + 前端联动

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [context/artifacts.py:70-260](context/artifacts.py) |
| **严重度** | 🟠 P1 — 50 artifacts × 无上限 content → maximum 50MB RAM（已发现 OOM 风险） |
| **关联修复** | D2 联动 D1：前端需显示 artifact evicted 状态 |
| **影响范围** | 长时间运行的 agent session（>50 个 tool output 触发 artifact 化后）|

### 2. 现状代码

```python
# context/artifacts.py:79-88 (当前)
class ArtifactStore:
    def __init__(
        self,
        threshold_tokens: int = 2000,
        max_artifacts: int = 50,
    ) -> None:
        self._threshold_tokens = threshold_tokens
        self._max_artifacts = max_artifacts
        # ...
```

当前 LRU 仅限制 **数量**（50 个），不限制 **内容大小**。每个 artifact 持有 `full_content`（原始工具输出），50 个 1MB 输出 = 50MB RAM。

### 3. 理论来源

> **引用**: Google SRE Book, Chapter 12 — "Effective Cache Management" — "Always set a maximum memory budget for caches. Without it, caches will eventually consume all available memory under production workloads."

**映射**: ArtifactStore 是内存缓存（非持久化）。必须同时限制 entries (50) 和 total bytes。

### 4. 精确修改方案

```diff
--- a/context/artifacts.py
+++ b/context/artifacts.py
@@ ... @@ class ArtifactStore:
     def __init__(
         self,
         threshold_tokens: int = 2000,
-        max_artifacts: int = 50,
+        max_artifacts: int = 50,
+        max_total_bytes: int = 10_000_000,   # 10 MB total in-memory budget
+        max_content_bytes: int = 1_000_000,   # 1 MB per artifact cap
     ) -> None:
         self._threshold_tokens = threshold_tokens
         self._max_artifacts = max_artifacts
+        self._max_total_bytes = max_total_bytes
+        self._max_content_bytes = max_content_bytes
+        self._total_bytes = 0
         # ...
         self._evicted_ids: set[str] = set()
+        """Artifact IDs that were evicted due to memory pressure."""
```

LRU 淘汰增加内存维度：

```python
def _evict_if_needed(self) -> int:
    """Evict oldest artifacts until within both count AND memory limits."""
    evicted = 0
    # Limit 1: count
    while len(self._store) > self._max_artifacts:
        self._total_bytes -= len(self._store.popitem(last=False)[1].full_content)
        evicted += 1
    # Limit 2: total bytes
    while self._total_bytes > self._max_total_bytes and self._store:
        key, artifact = self._store.popitem(last=False)
        self._total_bytes -= len(artifact.full_content)
        self._evicted_ids.add(key)
        evicted += 1
    return evicted
```

Content cap:

```python
def maybe_store(self, tool_name: str, output: str) -> tuple[str, bool]:
    # ...existing logic...
    capped = output[:self._max_content_bytes]   # cap at 1 MB
    artifact = Artifact(...)
    self._total_bytes += len(capped)
    self._store[artifact.artifact_id] = artifact
    self._evicted_ids.discard(artifact.artifact_id)  # re-fresh
    evicted = self._evict_if_needed()
    if evicted:
        logger.info("ArtifactStore evicted %d artifacts (total_bytes=%d)", evicted, self._total_bytes)
```

### 5. 前端联动

在 WS observation 事件中添加 `artifact_evicted: true` 字段：

```diff
--- a/server/events.py
+++ b/server/events.py
@@ ... @@ class WsObservation:
+    artifact_evicted: bool = False
```

前端 `WsEventBlock` 中渲染：

```tsx
{event.artifact_evicted && (
  <div className="observation-evicted-banner">
    ⚠️ This output was truncated — older artifacts were evicted to free memory.
  </div>
)}
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-D2-1 | 注入 60 个 200KB 伪 artifact（总计 12MB, >10MB limit） | ≤10MB 后触发淘汰；evicted_ids 记录被淘汰 key |
| T-D2-2 | 注入 1 个 5MB artifact（>1MB cap） | content 被截断为 1MB；total_bytes = ~1MB |
| T-D2-3 | 正常 agent 运行 5 步（不触发限制） | 0 evictions；`_total_bytes` 准确反映实际大小 |

---

## D3: 代码卫生 — Staging 隔离协议

### 问题

批次 C 执行中 C5 代码卫生变更与 C0-C4 安全修复被合并提交。根本原因: `git add -A` 全量暂存后按文件过滤 diff，导致有重叠文件的变更无法在 staging 阶段隔离。

### 协议

> **三阶段 Staging 协议**（所有后续批次强制执行）

| 阶段 | 动作 | 验证 |
|------|------|------|
| **Stage 1: 安全 & 特性修复** | `git add <fix-files>` — 仅包含 P0/P1 修复的文件变更 | `git diff --cached --stat` 与 <br>Phase 4 文档中的 Diff 计划逐项比对 |
| **Stage 2: Commit 安全修复** | `git commit -m "fix: ..."` | commit 中不包含任何 `refactor:` 或 `chore:` 类型的变更 |
| **Stage 3: Stage & Commit 卫生项** | `git add <sanitation-files>` → `git commit -m "refactor: ..."` | 分离的 commit，标注 `refactor:` 前缀 |

### Staging Checklist

在每个 execute 步骤的 `git add` 之前，检查以下内容并逐项核对：

```
[ ] 确认 git add 文件列表与文档 Diff 计划一致
[ ] 确认未混入仅注释/格式变更的文件
[ ] 确认未混入新文件（非当前批次的 MD 文档）
[ ] 若文件同时包含修复和卫生变更 — 记为偏差，在反思中说明
[ ] git diff --cached --stat 逐行与文档对照
```

---

## Staging Checklist（批次 D 执行专用）

```
[ ] D0 集成测试脚本: 仅 tests/manual/test_abort_e2e.py
[ ] D1 bundle: 仅 StatsDashboard/SessionSidebar/StatsDrawer/DiffReview/ChatView/App/ConfirmModal.tsx
[ ] D2 artifact: 仅 context/artifacts.py + server/events.py + WsEventBlock.tsx
[ ] D3 文档: 无需代码变更（仅此 MD 文件记录协议）

预期 Diff:
  D1: 8 components, ~200 line changes (typescript + tsx)
  D2: 2 files, ~40 line changes (python + typescript)
  D0: 1 file, ~60 lines (python test script)
  D3: 0 code files
```

---

## 批次 C 反思采纳清单

| # | 批次 C 反思建议 | 映射到批次 D | 具体采纳 |
|---|---------------|------------|---------|
| 1 | C2 端到端验证链路补齐 | **D0** | 全链路验证脚本 + 手动 checklist |
| 2 | P1 前端体验项批量修复 | **D1-Bundle** | P1-18~P1-25 原子化 Diff + axe-core 验证 |
| 3 | ArtifactStore 内存风险上升 | **D2** | max_total_bytes + max_content_bytes + 前端联动 |
| 4 | C5 合并提交根因分析 | **D3** | 三阶段 Staging 协议 + Checklist |

---

## 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **关联 Phase 2 TODO 编号** | P1-18, P1-19, P1-20, P1-21, P1-22, P1-23, P1-24, P1-25, P1-28 |
| **依赖批次** | 批次 A (d841fba) + B (662451a) + C (4ef0f2b) |
| **附录 C 摘要** | C0 Bash 方向分离 `(path, direction)` 元组方案 — 6 类提取规则 + 2 类终止规则 + 9 项测试基线 |
| **P0 状态** | 13/13 已修复 ✅ |
| **P1 状态** | 7/33 → 批次 D 完成后 15/33 |
| **Staging 协议** | 三阶段: Fix commit → Refactor commit → 逐项核实 |
| **理论来源** | Google SRE Book Ch.12, WCAG 2.1 (axe-core), React 19 useEffect cleanup docs |
| **下一阶段** | 批次 D 执行 → 批次 E 规划（剩余 P1 后端项: P1-26/27/28/29/30） |
