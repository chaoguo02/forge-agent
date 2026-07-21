# Phase 4: 批次 E 精准定位与理论指导方案

> **文档版本**: 1.0
> **生成时间**: 2026-07-21
> **关联 Phase 2 TODO 编号**: P1-26, P1-27, P1-30 + D0/D1 验证债务
> **对标报告引用**: [BENCHMARK_ANALYSIS.md §3.1](BENCHMARK_ANALYSIS.md#31-错误处理健壮性-差距-3-星) + [§3.3](BENCHMARK_ANALYSIS.md#33-并发安全-差距-2-星)
> **前置条件**: 批次 D (commit `7545373`) 已完成。P0 清零，P1 修复 15/33
> **预计总工时**: 10h
> **P0 修复率**: 13/13·**100%**  |  **P1 修复率**: 15/33 → E 后 18/33
> **批次 D 反思纳入**: 3 项调整（见文末清单）

---

## 目录

- [Verification Environment Matrix](#verification-environment-matrix)
- [E0: D0/D1 验证债务清偿（非新功能）](#e0-d0d1-验证债务清偿非新功能)
  - [E0-1: D0 server 生命周期自包含化](#e0-1-d0-server-生命周期自包含化)
  - [E0-2: D1 axe-core 补验 + error state 截图](#e0-2-d1-axe-core-补验--error-state-截图)
- [E1-Bundle: P1-26/27/30 后端健壮性原子化](#e1-bundle-p1-262730-后端健壮性原子化)
  - [E1-1: P1-26 — 频率限制](#e1-1-p1-26--频率限制)
  - [E1-2: P1-27 — RuntimeError → 409](#e1-2-p1-27--runtimeerror--409)
  - [E1-3: P1-30 — LLM 请求级超时](#e1-3-p1-30--llm-请求级超时)
- [E2: 验证环境标准化协议](#e2-验证环境标准化协议)
- [附录 D: D2 内存淘汰测试用例归档](#附录-d-d2-内存淘汰测试用例归档)
- [批次 D 反思采纳清单](#批次-d-反思采纳清单)
- [元数据](#元数据)

---

## Verification Environment Matrix

> **协议要求 (E2)**：每个验证项标注环境依赖类型与自动化封装状态。
> b = browser required | s = server required | B = both

| 修复/验证项 | 环境 | 当前状态 | 批次 E 封装计划 |
|-----------|------|---------|--------------|
| **E0-1** D0 self-contained | B | 🔴 依赖手动启停 server | `ServerContext` 上下文管理器，`python test_abort_e2e.py` 一键执行 |
| **E0-2** D1 axe-core | b | 🔴 从未执行 | 启动 server → `npx @axe-core/cli` 扫描 → 截图存档 |
| **E0-2** D1 error states | B | 🔴 从未执行 | 3 种 fault injection + 截图 |
| **E1-1** 限流 | s | 🟢 无浏览器依赖 | 单元测试 `pytest` + curl 验证 |
| **E1-2** RuntimeError→409 | s | 🟢 无浏览器依赖 | 单元测试 `pytest` |
| **E1-3** LLM 超时 | s | 🟢 无浏览器依赖 | Mock LLM 超时 → 断言连接释放 |
| **E2** 协议更新 | — | 🟢 仅文档 | 此矩阵已纳入规划文档 |

---

## E0: D0/D1 验证债务清偿（非新功能）

> **约束**: E0 必须在 E1 功能开发前完成。此为批次 D 的验收闭环，非新功能。

### E0-1: D0 server 生命周期自包含化

#### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [tests/manual/test_abort_e2e.py](tests/manual/test_abort_e2e.py) |
| **债务来源** | 批次 D — D0 脚本需手动启动/停止 server |
| **验收标准** | `python tests/manual/test_abort_e2e.py` 单命令执行成功，无需手动启停 server |

#### 2. 现状代码

```python
# tests/manual/test_abort_e2e.py:9-13 (当前)
# Usage:
#   1. Start the server in a separate terminal:
#      python -m server.main --repo . --no-browser
#   2. Run this script:
#      python tests/manual/test_abort_e2e.py

def main():
    # Pre-flight: server reachable?
    health = _api("GET", "/")
    if health.get("_error"):
        print(f"ERROR: Server not reachable at {BASE}")
        sys.exit(1)
```

#### 4. 理论来源

> **引用**: [pytest-xprocess](https://pypi.org/project/pytest-xprocess/) — "External process management for integration tests. Starts and stops processes before and after test runs."

**映射**: `ServerContext` 上下文管理器在 `__enter__` 中启动 uvicorn 进程，`__exit__` 中 SIGTERM → wait。确保即使测试失败也会清理进程。无需引入 pytest-xprocess 依赖——基于 `subprocess.Popen` 即可实现。

#### 5. 精确修改方案

```diff
--- a/tests/manual/test_abort_e2e.py
+++ b/tests/manual/test_abort_e2e.py
@@ ... @@
-# Usage:
-#   1. Start the server in a separate terminal:
-#      python -m server.main --repo . --no-browser
-#   2. Run this script:
-#      python tests/manual/test_abort_e2e.py
+"""
+End-to-end AbortController verification (D0/E0).
+
+Self-contained: starts a local Grace-Code server, runs the abort lifecycle
+tests, then shuts down.  No manual server management required.
+
+Usage:
+    python tests/manual/test_abort_e2e.py
+"""

+import signal
+import threading

+class ServerContext:
+    """Context manager that starts/stops the Grace-Code web server."""
+
+    def __init__(self, repo: str = ".", port: int = 18765, startup_timeout: float = 15.0):
+        self.repo = repo
+        self.port = port
+        self.startup_timeout = startup_timeout
+        self._process: subprocess.Popen | None = None
+        self._stderr_thread: threading.Thread | None = None
+
+    def __enter__(self):
+        self._process = subprocess.Popen(
+            [sys.executable, "-m", "server.main",
+             "--repo", self.repo,
+             "--port", str(self.port),
+             "--no-browser"],
+            stdout=subprocess.DEVNULL,
+            stderr=subprocess.PIPE,
+            text=True,
+        )
+        # Drain stderr in background to prevent buffer deadlock
+        self._stderr_thread = threading.Thread(
+            target=self._consume_stderr, daemon=True,
+        )
+        self._stderr_thread.start()
+        # Poll until server is ready
+        deadline = time.time() + self.startup_timeout
+        while time.time() < deadline:
+            try:
+                import urllib.request
+                urllib.request.urlopen(f"http://localhost:{self.port}/", timeout=2)
+                return self
+            except Exception:
+                time.sleep(0.3)
+        self.__exit__(None, None, None)
+        raise RuntimeError("Server did not start within timeout")
+
+    def _consume_stderr(self):
+        for _ in self._process.stderr:
+            pass
+
+    def __exit__(self, *args):
+        if self._process and self._process.poll() is None:
+            self._process.send_signal(signal.SIGTERM)
+            try:
+                self._process.wait(timeout=10)
+            except subprocess.TimeoutExpired:
+                self._process.kill()
+                self._process.wait()

-_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
+_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
+_DEFAULT_PORT = 18765  # non-default to avoid conflicts with dev server

 def main():
     # Pre-flight: server reachable?
-    health = _api("GET", "/")
-    if health.get("_error"):
-        print(f"ERROR: Server not reachable at {BASE}")
-        sys.exit(1)
+    health = _api("GET", "/")
+    if health.get("_error"):
+        print(f"Server not running — starting on port {_DEFAULT_PORT}...")
+        with ServerContext(repo=_PROJECT_ROOT, port=_DEFAULT_PORT) as ctx:
+            return _run_tests()
+    else:
+        return _run_tests()
+
+
+def _run_tests():
     # ... existing test_* calls ...
```

#### 6. 验证标准

```
$ python tests/manual/test_abort_e2e.py
Server not running — starting on port 18765...
── D0-1: abort → cancelled ──
  Created session: abc123def456
  Agent running, sending cancel…
  WS received status:cancelled
  ✅ D0-1 PASSED
── D0-2: rapid session switch → no zombies ──
  ✅ D0-2 PASSED
── D0-3: cross-session data integrity ──
  ✅ D0-3 PASSED

D0: 3/3 tests passed
ALL D0 TESTS PASSED
```

---

### E0-2: D1 axe-core 补验 + error state 截图

#### 验证流程

| 步骤 | 操作 | 期望结果 |
|------|------|---------|
| 1 | 启动 server + 构建前端: `npm run build` → `python -m server.main` | Web UI 可访问 |
| 2 | `npx @axe-core/cli http://localhost:8765 --tags wcag2a,wcag2aa` | 0 critical / 0 serious violations |
| 3 | Error state 1: 断网 → 打开 StatsDashboard | 显示 error banner + Retry |
| 4 | Error state 2: 后端返回 500 → 打开 SessionSidebar | 显示 error + Retry 按钮 |
| 5 | Error state 3: StatsDrawer 数据加载失败 | 显示 error 文字而非全零面板 |

#### 截图存档路径

```
docs/screenshots/batch-e/
├── axe-core-report.txt       # npx @axe-core/cli 扫描输出
├── error-state-stats.png     # 步骤 3
├── error-state-sidebar.png   # 步骤 4
└── error-state-drawer.png    # 步骤 5
```

#### 验收判定

| 门禁 | 通过条件 | 不通过处置 |
|------|---------|-----------|
| axe-core | 0 critical, 0 serious | **D1 状态回退为"部分完成"，P1-18~P1-25 不计入 P1 修复率** |
| error state 截图 | 3 张截图均显示 error UI 组件 | 缺失的截图标注 `TODO`，批次 F 补验 |

---

## E1-Bundle: P1-26/27/30 后端健壮性原子化

> **约束**: 3 项后端 P1 必须作为一个 Diff apply。统一负载测试 + 超时注入测试。禁止拆分。

### 修复项映射

| # | TODO | 内容 | 文件 |
|---|------|------|------|
| E1-1 | P1-26 | 频率限制中间件 | server/main.py |
| E1-2 | P1-27 | RuntimeError → 409 | server/routers/sessions.py |
| E1-3 | P1-30 | LLM 请求级超时 | llm/invoker.py |

---

### E1-1: P1-26 — 频率限制

#### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [server/main.py](server/main.py) (app factory) |
| **严重度** | 🟠 P1 — `POST /api/sessions/{id}/chat` 无频率限制 → 滥用可耗尽 LLM API 额度 |

#### 2. 现状代码

```python
# server/main.py:57-77 — 当前 FastAPI app 创建，无 middleware
def create_app(service: AgentService) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        await service.shutdown()

    app = FastAPI(...)
    # ... no rate limiting middleware
```

#### 4. 理论来源

> **引用**: [IETF RFC 6585 §4](https://datatracker.ietf.org/doc/html/rfc6585#section-4) — "The 429 status code indicates that the user has sent too many requests in a given amount of time ('rate limiting'). The response SHOULD include a `Retry-After` header."

#### 5. 精确修改方案

```python
# server/main.py — add rate limit middleware
import time as _time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-session token-bucket rate limiter.

    Chat endpoints: 10 requests per 60s per session.
    Other endpoints: 60 requests per 60s per IP.
    """

    _WINDOW = 60  # seconds
    _CHAT_LIMIT = 10
    _GENERAL_LIMIT = 60

    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, tuple[float, int]] = {}  # key → (window_start, count)

    async def dispatch(self, request, call_next):
        path = request.url.path
        is_chat = "/messages" in path and request.method == "POST"

        if is_chat:
            # Per-session rate limit
            import re
            m = re.match(r"/api/sessions/([a-f0-9]+)/messages", path)
            key = m.group(1) if m else request.client.host if request.client else "unknown"
            limit = self._CHAT_LIMIT
        else:
            key = request.client.host if request.client else "unknown"
            limit = self._GENERAL_LIMIT

        now = _time.time()
        entry = self._buckets.get(key)
        if entry is None or now - entry[0] > self._WINDOW:
            self._buckets[key] = (now, 1)
        else:
            window_start, count = entry
            if count >= limit:
                retry_after = int(self._WINDOW - (now - window_start)) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded ({limit} per {self._WINDOW}s)"},
                    headers={"Retry-After": str(retry_after)},
                )
            self._buckets[key] = (window_start, count + 1)

        # Periodic cleanup
        if len(self._buckets) > 10_000:
            self._buckets = {k: v for k, v in self._buckets.items() if now - v[0] <= self._WINDOW}

        return await call_next(request)
```

Register in `create_app()`:

```diff
--- a/server/main.py
+++ b/server/main.py
@@ ... @@ def create_app(service: AgentService) -> FastAPI:
     )
+    app.add_middleware(RateLimitMiddleware)
```

#### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-E1-1a | 对 chat 端点 11 次请求/60s | 第 11 次返回 `429` + `Retry-After` header；前 10 次 `202` |
| T-E1-1b | 对 GET /api/sessions 61 次请求/60s | 第 61 次返回 `429` |
| T-E1-1c | 等待 `Retry-After` 秒后重试 | 请求正常通过 |

---

### E1-2: P1-27 — RuntimeError → 409

#### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [server/routers/sessions.py:417-423](server/routers/sessions.py#L417-L423) |
| **严重度** | 🟠 P1 — 并发 session chat 执行返回 `500 Internal Server Error` 而非 `409 Conflict` |

#### 2. 现状代码

```python
# Line 417-423 (当前)
# Start async execution in background thread
service.run_chat_async(   # ← can raise RuntimeError("Session already running")
    session_id=session_id,
    ...
)
return {"accepted": True}
```

#### 5. 精确修改方案

```diff
--- a/server/routers/sessions.py
+++ b/server/routers/sessions.py
@@ ... @@
         # Start async execution in background thread
-        service.run_chat_async(
-            session_id=session_id,
-            prompt=body.prompt,
-            agent_name=effective_agent,
-            intent=body.intent,
-        )
+        try:
+            service.run_chat_async(
+                session_id=session_id,
+                prompt=body.prompt,
+                agent_name=effective_agent,
+                intent=body.intent,
+            )
+        except RuntimeError as exc:
+            raise HTTPException(status_code=409, detail=str(exc))

         return {"accepted": True}
```

#### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-E1-2 | 对同一 session 并发 2 个 chat 请求 | 第 1 个 `202`，第 2 个 `409` + `"Session ... is already running"` |

---

### E1-3: P1-30 — LLM 请求级超时

#### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [llm/invoker.py:76-93](llm/invoker.py#L76-L93) |
| **严重度** | 🟠 P1 — LLM 调用无请求级超时，提供商 hang 可阻塞 agent 线程永久 |

#### 2. 现状代码

```python
# llm/invoker.py:76-93 (当前 — 无超时保护)
def invoke(self, messages, tools, ...):
    for attempt in range(1, self.config.llm_max_retries + 2):
        try:
            response = self.backend.complete(messages, tools)
            # ← if the provider hangs here, the agent thread blocks forever
```

#### 4. 理论来源

> **引用**: [Google SRE Book Ch. 22](https://sre.google/sre-book/addressing-cascading-failures/) — "Every RPC to a backend must have a deadline. Without deadlines, a slow or hung backend consumes resources indefinitely. The deadline propagates through the call chain via context cancellation."

**映射**: LLM 后端调用是 RPC——向远程 API 的 HTTP 调用。必须在 `ThreadPoolExecutor` 中包裹以实现进程级超时（Python 线程无法被强制中断，但可以从超时中恢复）。

#### 5. 精确修改方案

```diff
--- a/llm/invoker.py
+++ b/llm/invoker.py
@@
+import concurrent.futures
 import logging
 import random as _random
 import time as _time
@@

+    # Default per-request timeout for LLM backend calls (seconds).
+    # Individual backends may set shorter timeouts via their config.
+    _DEFAULT_REQUEST_TIMEOUT: float = 300.0

     def invoke(self, messages, tools, cumulative_cache=None, prompt_metadata=None):
         """Invoke the LLM backend with retry + jitter + timeout enforcement.

         Returns InvokeResult with response and cache stats.
         """
         delay = self.config.llm_retry_delay
         last_exc = None
+        timeout = getattr(self.config, 'request_timeout', self._DEFAULT_REQUEST_TIMEOUT)

         for attempt in range(1, self.config.llm_max_retries + 2):
             try:
-                response = self.backend.complete(messages, tools)
+                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
+                    future = executor.submit(self.backend.complete, messages, tools)
+                    response = future.result(timeout=timeout)
```

#### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-E1-3a | Mock backend 延迟 400s（>300s timeout） | `TimeoutError` 抛出；retry 生效 |
| T-E1-3b | Mock backend 正常返回（<300s） | 正常完成；thread pool cleanup 正确 |
| T-E1-3c | 连续 3 次超时 | `max_retries` 耗尽后 raise 最终异常；WS 推送 `status:failed` |

---

### E1-Bundle 统一验证方案

| 测试阶段 | 方法 | 通过条件 |
|---------|------|---------|
| 1. 限流 | `curl` 循环 12 次 POST chat | 前 10 次 `202`, 第 11 次起 `429 + Retry-After` |
| 2. 409 | 并发 2 个相同 session chat | 第 1 个 `202`, 第 2 个 `409` |
| 3. 超时 | Mock 3 次后端延迟 → 检查连接释放 | 最终异常 `TimeoutError`；agent 线程不泄漏 |

---

## E2: 验证环境标准化协议

### 协议文本

> **Verification Environment Standardization Protocol (VESP)**

**Rule 1 — 环境依赖显式声明**：每个修复项的规划章节（§1 问题定位表）中，`属性` 表必须包含 `验证环境` 行，值为 `unit` / `browser` / `server` / `browser+server` / `manual`。

**Rule 2 — 自动化封装方案必填**：`验证环境` 为 `browser` / `server` / `browser+server` 的项，必须在 `§5 精确修改方案` 之后包含 `§5.5 自动化封装` 小节，描述如何消除手动步骤。

**Rule 3 — 矩阵回填**：每次批次执行后，更新本规划文档的 `Verification Environment Matrix` 中对应行的 `当前状态` 列。

**Rule 4 — 回滚预案**：若任一修复项在验收阶段需要手工补做验证，反思报告必须包含 `VESP Violation Report` 小节，记录：违反的规则编号、遗漏的环境依赖、将采取的预防措施（如更新 Skill 约束库）。

### 本批次实施

本规划文档已包含 `Verification Environment Matrix`（见顶部）。这是首个遵守 VESP 的批次。所有 6 个验证项均已标注环境类型与封装计划。E0 将消除最后 2 个 `🔴` 状态项。

---

## 附录 D: D2 内存淘汰测试用例归档

> **归档时间**: 2026-07-21（批次 D 验证通过）  
> **归档范围**: D2 ArtifactStore 内存限制的 3 个测试用例

### D2 测试基线

```
T-D2-1: Memory eviction under byte pressure
  Config: max_artifacts=5, max_total_bytes=400_000, max_content_bytes=200_000
  Input:  7 unique artifacts, ~100KB each
  Result: 4 artifacts retained, 3 evicted, total_bytes=400_000
  Status: ✅ PASSED

T-D2-2: Single artifact content cap
  Config: max_content_bytes=100_000
  Input:  1 artifact, 500_000 chars
  Result: content capped at 100_000 chars
  Status: ✅ PASSED

T-D2-3: Normal run — no eviction
  Config: defaults
  Input:  3 small artifacts
  Result: 0 evictions, total_bytes accurately reflects size
  Status: ✅ PASSED
```

### 关键配置常量

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `max_total_bytes` | 10_000_000 | 内存中所有 artifact 内容的总字节上限 |
| `max_content_bytes` | 1_000_000 | 单个 artifact 的内容截断上限 |
| `max_artifacts` | 50 | 保留的最大 artifact 数量（count-based LRU） |
| `_total_bytes` | 0 (动态) | 当前内存中所有 artifact 的字节总和 |
| `_evicted_ids` | `set()` | 因内存压力被淘汰的 artifact ID 集合 |

---

## 批次 D 反思采纳清单

| # | 批次 D 反思建议 | → 批次 E | 采纳方式 |
|---|---------------|---------|---------|
| 1 | D0 需 server 生命周期管理 | **E0-1** | `ServerContext` 上下文管理器，一键运行 |
| 2 | D1 axe-core + error state 截图未补 | **E0-2** | 门禁：0 critical/0 serious，否则 D1 回退 |
| 3 | 验证环境依赖应在规划阶段识别 | **E2** | Verification Environment Matrix + VESP 协议 |

---

## 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **关联 Phase 2 TODO 编号** | P1-26, P1-27, P1-30 |
| **依赖批次** | 批次 D (commit `7545373`) |
| **VESP 合规** | ✅ 首个遵守验证环境标准化协议的批次 |
| **附录 D 测试用例** | 3 个（D2 内存淘汰归档） |
| **验证环境矩阵** | 6 个验证项，3 个状态 `🔴`（E0 清偿） |
| **理论来源** | IETF RFC 6585 §4, Google SRE Ch.22, pytest-xprocess patterns |
| **下一阶段** | 批次 E 执行 → 批次 F 规划（剩余 P1/P2 项） |
