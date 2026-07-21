# Phase 4: 批次 A 精准定位与理论指导方案

> **文档版本**: 1.0  
> **生成时间**: 2026-07-21  
> **关联 Phase 2 TODO 编号**: P0-1, P0-2, P0-7, P0-13, P0-8  
> **对标报告引用**: [BENCHMARK_ANALYSIS.md §4-批次A](BENCHMARK_ANALYSIS.md#4-严重问题--分批修复路线图)  
> **预计总工时**: 9h  
> **前置条件**: 所有 5 项的 diff 可直接 apply；需 `pytest` + `python -m server.main` 测试环境就绪

---

## 目录

- [A1: P0-1 — SessionStore SQLite WAL 模式 + busy_timeout](#a1-p0-1--sessionstore-sqlite-wal-模式--busy_timeout)
- [A2: P0-2 — Backend Per-Session 实例化（消除全局单例竞态）](#a2-p0-2--backend-per-session-实例化消除全局单例竞态)
- [A3: P0-7 — Session 删除事务性包裹 (BEGIN IMMEDIATE)](#a3-p0-7--session-删除事务性包裹-begin-immediate)
- [A4: P0-13 — 记忆文件名路径遍历消毒化](#a4-p0-13--记忆文件名路径遍历消毒化)
- [A5: P0-8 — 工具校验失败 break→continue 修复](#a5-p0-8--工具校验失败-breakcontinue-修复)
- [元数据](#元数据)

---

## A1: P0-1 — SessionStore SQLite WAL 模式 + busy_timeout

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [agent/session/session_store.py:42-45](agent/session/session_store.py#L42-L45) |
| **函数** | `SessionStore._connect()` |
| **严重度** | 🔴 P0 — 并发 session 崩溃 |
| **关联 DB** | `.grace/v2/sessions.db`（与 `memory/sqlite_backend.py` 共库） |
| **影响调用链** | `SessionStore` 全部 CRUD + `SqliteStorageBackend` 初始化/删除/统计 + 所有通过 `_store._connect()` 的间接调用 |

### 2. 现状代码

```python
# agent/session/session_store.py:42-45 (当前)
def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self._db_path)
    conn.row_factory = sqlite3.Row
    return conn
```

### 3. 同一数据库文件的其他连接源（对照）

| 连接源 | 文件:行号 | WAL? | busy_timeout? |
|--------|-----------|------|---------------|
| `SessionStore._connect()` | session_store.py:42 | ❌ | ❌ 默认 0 |
| `SqliteMemoryBackend._conn()` | sqlite_backend.py:51-56 | ✅ | ✅ 10000ms |
| `ExternalMemoryStore._create_conn()` | external_store.py:483-488 | ✅ | ❌ |
| `test_memory_api.py` (test) | test_memory_api.py:37,63 | ❌ | ❌ |

> **关键事实**: 同一个 `sessions.db` 文件被 `SessionStore`（DELETE mode）和 `SqliteMemoryBackend`（WAL mode）同时打开。当 `SessionStore` 持有 EXCLUSIVE 锁时，`SqliteMemoryBackend` 的任何读操作都会收到 `SQLITE_BUSY` — 反之亦然。

### 4. 理论来源

#### 4.1 SQLite WAL 模式官方规范 — §3.2 并发性

> **引用**: [SQLite WAL 文档](https://www.sqlite.org/wal.html) — "WAL provides more concurrency as readers do not block writers and a writer does not block readers. Reading and writing can proceed concurrently."

**映射到本修复**: `journal_mode=DELETE`（默认）下单个 writer 获取 EXCLUSIVE 锁 — 所有其他连接被阻塞直到事务完成。改用 `journal_mode=WAL` 后写入追加到 `-wal` 文件，读者可不受阻塞地继续读取主 DB 文件。这是 Claude Code [Issue #14124](https://github.com/anthropics/claude-code/issues/14124) 的**官方验证修复方案** — 社区修复后并行 Explore 子代理冻结问题消失。

#### 4.2 SQLite `busy_timeout` 处理锁冲突

> **引用**: [SQLite busy_timeout 文档](https://www.sqlite.org/pragma.html#pragma_busy_timeout) — "When a table is locked, SQLite retries automatically for `busy_timeout` milliseconds before returning `SQLITE_BUSY`."

**映射到本修复**: 默认 `busy_timeout=0` 意味着**任何**锁冲突立即返回 `SQLITE_BUSY`，无重试。这是导致 Grace-Code 并发场景立即崩溃的直接原因。`busy_timeout=10000`（10 秒）允许两处写入排队而非立即失败。

#### 4.3 Defense in Depth: 多连接 journal_mode 一致性

> **引用**: [SQLite WAL 文件格式](https://www.sqlite.org/walformat.html) — "All processes that want to access the same database file must agree on the journal mode."

**映射到本修复**: Grace-Code 当前混合 `DELETE` 和 `WAL` 连接到同一文件。统一所有连接源为 WAL 模式。

### 5. 精确修改方案

#### 修改 1/2: `agent/session/session_store.py:42-45`（核心修改）

```diff
--- a/agent/session/session_store.py
+++ b/agent/session/session_store.py
@@ ... @@ class SessionStore:
         return self._db_path
 
     def _connect(self) -> sqlite3.Connection:
         conn = sqlite3.connect(self._db_path)
+        conn.execute("PRAGMA journal_mode=WAL")
+        conn.execute("PRAGMA busy_timeout=10000")
         conn.row_factory = sqlite3.Row
         return conn
 
     def _init_db(self) -> None:
         with self._connect() as conn:
```

#### 修改 2/2: `memory/external_store.py:486`（补充 — 添加缺失的 busy_timeout）

```diff
--- a/memory/external_store.py
+++ b/memory/external_store.py
@@ ... @@ class ExternalMemoryStore:
         Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
         conn = sqlite3.connect(self._db_path)
         conn.execute("PRAGMA journal_mode=WAL")  # 并发读写安全
+        conn.execute("PRAGMA busy_timeout=10000")
         conn.row_factory = sqlite3.Row
         return conn
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-A1-1 | 单 session 启动 → `python -m server.main --no-browser` | 无错误；service 正常初始化 |
| T-A1-2 | 启动 3 个并发 session：每个执行 `POST /api/sessions/{id}/chat`（简单任务 "list python files"）同时进行 | 所有 3 个 session 正常完成；无 `SQLITE_BUSY` |
| T-A1-3 | Session 写入同时记忆保存：1 session 执行 `Write` + 另一线程写入 10 条记忆 | 全部成功；确认 `.grace/v2/sessions.db-wal` 存在 |
| T-A1-4 | 验证 WAL 生效：Python REPL 连接 DB 执行 `PRAGMA journal_mode;` | 返回 `'wal'` |
| T-A1-5 | 停止所有连接后 `PRAGMA wal_checkpoint(TRUNCATE);` | 返回 `(0, 0, 0)` — WAL 清空且所有页合并 |

### 7. 回归验证标准

- [ ] `pytest tests/test_memory_api.py -v` — 全部通过
- [ ] `pytest tests/test_e2e_core.py -v -m e2e` — 端到端测试通过
- [ ] `python -m server.main --repo . --no-browser` 正常启动
- [ ] Web UI 中创建 session → chat → 检查执行正常
- [ ] `.grace/v2/` 目录应存在 `sessions.db-wal` 和 `sessions.db-shm` 文件

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `SessionStore._connect()` — 所有 session CRUD 路径（30+ 方法）；`SqliteStorageBackend` 全部操作；`ExternalMemoryStore` 连接 |
| **触发条件** | 仅多线程并发访问同一 `sessions.db` 时体现改进。单 session 场景行为完全不变 |
| **失败模式** | 若 `PRAGMA journal_mode=WAL` 因权限失败（如只读文件系统），首次 `_connect()` 即抛 `OperationalError`，快速暴露而非静默降级 |
| **WAL 文件空间** | 100 轮/session、每轮 5 条工具输出场景下，预计 `-wal` < 50MB；`-shm` 固定 32KB |
| **与现有 WAL 连接冲突** | 不会。多连接以相同 `journal_mode=WAL` 打开同一 DB 是安全且推荐的行为 |
| **缓解措施** | 若 WAL 失败：`_connect()` 将抛明确异常，调用方已有异常处理；启动时可在 `_init_db()` 添加 `wal_checkpoint(TRUNCATE)` 清理冗余 WAL 页 |

### 9. 设计决策备注（批判性反思）

> **反思 1: 是否引入了新的全局状态？**
> 否。WAL + busy_timeout 是 per-connection pragma，每次 `_connect()` 创建独立连接并设置独立 PRAGMA。无全局副作用。

> **反思 2: 是否与 V2 子代理编排冲突？**
> 否。子代理 Fork 创建新 git worktree 目录。`SessionStore` 可指向相同或不同 DB — WAL 模式的并发改进在两种情况下均为纯增益。

> **反思 3: 是否有更轻量的替代方案？**
> 考虑过仅添加 `busy_timeout` 不加 `WAL` — 这只缓解症状（DELETE 模式下硬等待）而非根治（读写互斥）。DELETE 模式下 writer 持有 EXCLUSIVE 锁期间所有 reader 仍被阻塞。WAL 是唯一的根本性方案。

> **反思 4: 是否需要 checkpoint 管理？**
> SQLite 默认 `wal_autocheckpoint=1000`（积压 1000 页后自动合并）。单用户场景足够。若后续支持 10+ 并发 session，可在 `shutdown()` 中显式调用 `PRAGMA wal_checkpoint(TRUNCATE)`。

---

## A2: P0-2 — Backend Per-Session 实例化（消除全局单例竞态）

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [server/services/agent_service.py:118](server/services/agent_service.py#L118) (init) + [line 620](server/services/agent_service.py#L620) (mutate) |
| **两处关键路径** | (a) `AgentService.__init__()` 创建全局 `self._backend`；(b) `_run_and_notify()` daemon 线程中 reassign |
| **影响线程** | 主线程（其他 session 的 LLM 调用）与 daemon 线程（模型切换）并发访问 |
| **严重度** | 🔴 P0 — 多 session 场景下 API key/model/base_url 泄漏/错配 |
| **关联子代理路径** | [agent/session/runtime_spawn.py:252](agent/session/runtime_spawn.py#L252) — `backend=self._backend` 传递给子代理 |

### 2. 现状代码

```python
# server/services/agent_service.py:96-123 (init — 全局单例)
self._backend = create_backend_from_config({
    "provider": self._config.llm.provider,
    "model": self._config.llm.model,
    "api_key": self._config.llm.api_key or None,
    "base_url": self._config.llm.base_url or None,
    "max_tokens": self._config.llm.max_tokens,
    "timeout_seconds": self._config.llm.timeout_seconds,
})

# server/services/agent_service.py:614-627 (daemon 线程 — 非原子 reassign)
_pending = self._runtime.pop_pending_model(session_id)
if _pending:
    _model, _provider = _pending
    self._backend = create_backend_from_config({   # ← 全局因子非安全写入
        "provider": _provider or self._config.llm.provider,
        "model": _model,
        "api_key": self._config.llm.api_key or None,
        "base_url": self._config.llm.base_url or None,
        ...
    })

# agent/session/runtime.py:838 (run_session — 使用全局 backend)
_assembly = AgentFactory.create(
    agent_name=_effective_agent,
    backend=self._backend,       # ← 读操作 — 可能与上面的写操作竞态
    ...
)

# agent/session/runtime_spawn.py:252 (子代理 — 继承同个全局 backend)
backend=self._backend,           # ← 子代理使用同一个全局 backend 引用
```

### 3. Backend 生命周期对照表

| 生命周期阶段 | 文件:行号 | 操作 | 风险 |
|-------------|-----------|------|------|
| 创建 (init) | agent_service.py:118 | `self._backend = create_backend_from_config(...)` | 仅一次，安全 |
| 读取 (主 agent) | runtime.py:838 | `AgentFactory.create(backend=self._backend, ...)` | 与写入竞态 |
| 读取 (子 agent) | runtime_spawn.py:252 | `backend=self._backend` | 与写入竞态 — 子代理继承父代理的 backend 引用 |
| 写入 (模型切换) | agent_service.py:620 | `self._backend = create_backend_from_config(...)` | 非原子，与所有读操作竞态 |
| 获取 (fork 校验) | runtime_spawn.py:95 | `spawn_context.model_name != self._backend.model_name` | 在写入中途读取 → 校验逻辑可能用错模型名 |

### 4. 理论来源

#### 4.1 Clean Architecture — 第 16 章 "The Dependency Rule" + 第 23 章 "The Main Component"

> **引用**: Robert C. Martin, *Clean Architecture* (2017), Chapter 16: "Dependencies must point inward. Nothing in an inner circle can know anything at all about something in an outer circle."

**映射到本修复**: `AgentService`（外层 — Web 适配器）不应持有和变更 `LLMBackend`（内层 — 核心业务依赖）。Backend 的生命周期应归属于 `SessionRuntime`（用例层）。这符合依赖反转原则：`AgentService` → `SessionRuntime` → `AgentFactory.create(backend=...)`，而非 `AgentService` 直接管理 backend 并传递到 Runtime。

#### 4.2 OpenHands V1 设计原则 — "Stateless Components, Single Source of Truth"

> **引用**: [OpenHands V1 SDK Architecture](https://dev.to/pickuma/openhands-review-the-open-source-autonomous-coding-agent-in-2026-5gcj) — "`Agent`, `Tool`, `LLM`, and `Condenser` are immutable Pydantic models. Only `ConversationState` is mutable, changed by appending events, never by mutating objects."

**映射到本修复**: OpenHands 将 LLM 实例作为 per-invocation 不可变配置传递给 Agent。Agent 本身是纯函数式组件。Grace-Code 的 `self._backend` 全局单例模式恰恰是此原则的反例 — backend 应在每次 `run_session()` 时按需创建或传入。

#### 4.3 FastAPI 线程安全最佳实践 (2025)

> **引用**: [FastAPI Thread Safety Best Practices](https://stackoverflow.com/questions/79805542) — "Global singletons risk race conditions without locking. Per-session instances provide the strongest isolation."

**映射到本修复**: FastAPI + daemon 线程的混合场景中，共享 mutable 状态需要显式同步。`self._backend` 的 reassign 是**非原子操作**（Python 中 `self._backend = ...` 是引用赋值，非 GIL 保护的原子操作）。两个线程读/写同一引用可导致部分初始化的对象被读取。

### 5. 精确修改方案

> **修改顺序说明**: 共 3 个文件，按依赖顺序排列。序号 1 是基础设施，序号 2/3 是使用者变更。

#### 修改 1/3: `agent/session/runtime.py` — 新增 `_backend_store` 存储与管理方法

```diff
--- a/agent/session/runtime.py
+++ b/agent/session/runtime.py
@@ ... @@ class SessionRuntime:
         self._web_confirm_callbacks: dict[str, "WebConfirmCallback"] = {}
         self._stream_callbacks: dict[str, "StreamCallback"] = {}
         self._cancellation_tokens: dict[tuple[str, int], CancellationToken] = {}
+        self._backend_store: dict[str, "LLMBackend"] = {}
+        """Per-session LLM Backend instances. 
+        Keyed by session_id to eliminate global singleton race conditions.
+        When a session_id is not present, the default backend (self._backend) 
+        is used as a fallback for backward compatibility."""
         self._background_runs: dict[tuple[str, int], threading.Thread] = {}
         self._background_runs_lock = threading.Lock()
         self._active_sessions: set[str] = set()
@@ ... @@ class SessionRuntime:
         # Mark MCP tools as UNAVAILABLE if the bridge failed to connect
         self._sync_mcp_capabilities()
 
+    def get_backend_for_session(self, session_id: str) -> "LLMBackend":
+        """Return the per-session backend or the default backend.
+        
+        Per-session backends are created by AgentService when a model switch
+        is pending. If no per-session backend exists for this session_id,
+        returns the global default backend (self._backend).
+        """
+        with self._active_sessions_lock:
+            return self._backend_store.get(session_id, self._backend)
+
+    def set_backend_for_session(self, session_id: str, backend: "LLMBackend") -> None:
+        """Store a per-session backend for the given session."""
+        with self._active_sessions_lock:
+            self._backend_store[session_id] = backend
+
+    def release_backend_for_session(self, session_id: str) -> None:
+        """Remove the per-session backend after execution completes."""
+        with self._active_sessions_lock:
+            self._backend_store.pop(session_id, None)
```

#### 修改 2/3: `server/services/agent_service.py:606-661` — Backend 创建改为 per-session 存储

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
             # ── Apply pending model switch ──
             _pending = self._runtime.pop_pending_model(session_id)
             if _pending:
                 _model, _provider = _pending
                 logger.info("Applying model switch — session=%s model=%s provider=%s",
                             session_id[:8], _model, _provider)
                 from llm.router import create_backend_from_config
-                self._backend = create_backend_from_config({
+                _session_backend = create_backend_from_config({
                     "provider": _provider or self._config.llm.provider,
                     "model": _model,
                     "api_key": self._config.llm.api_key or None,
                     "base_url": self._config.llm.base_url or None,
                     "max_tokens": self._config.llm.max_tokens,
                     "timeout_seconds": self._config.llm.timeout_seconds,
                 })
+                self._runtime.set_backend_for_session(session_id, _session_backend)
 
             # ── Apply pending effort/thinking/permission_mode ──
             _pending_effort = self._runtime.pop_pending_effort(session_id)
```

同时，在 `agent_service.py:96` 注释全局 backend 为 "fallback only"：

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
         # ── 2. Create LLM backend ──
         from llm.router import create_backend_from_config
 
+        # Default backend — used as fallback when no per-session backend
+        # has been registered. Per-session overrides are created by
+        # _run_and_notify() when a model switch is pending.
         self._backend = create_backend_from_config({
             "provider": self._config.llm.provider,
```

#### 修改 3/3: `agent/session/runtime.py:836-838` — `run_session()` 使用 per-session backend

```diff
--- a/agent/session/runtime.py
+++ b/agent/session/runtime.py
@@ ... @@ class SessionRuntime:
             from agent.session.agent_factory import AgentFactory
+            _effective_backend = self.get_backend_for_session(session_id)
             _assembly = AgentFactory.create(
                 agent_name=_effective_agent,
-                backend=self._backend,
+                backend=_effective_backend,
                 base_registry=self._base_registry,
```

`runtime_spawn.py:252` 同样更新：

```diff
--- a/agent/session/runtime_spawn.py
+++ b/agent/session/runtime_spawn.py
@@ ... @@ def spawn_agent(
         child_result = run_child_agent(
             agent_id=child.id, request=request, source_definition=definition,
             repo_path=repo_path, base_registry=self._base_registry,
-            backend=self._backend, log_dir=self._log_dir,
+            backend=self.get_backend_for_session(parent_session_id),
+            log_dir=self._log_dir,
```

在 `_run_and_notify()` 的 finally 块中添加清理：

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
             finally:
                 # Release the TOCTOU guard acquired in run_chat_async.
                 self._runtime.release_session(session_id)
+                # Release per-session backend (prevents unbounded growth)
+                self._runtime.release_backend_for_session(session_id)
```

### 5.2 现有测试覆盖盲区

| 盲区 | 现象 | 后果 |
|------|------|------|
| **子代理 Fork 时的 backend 继承** | `test_e2e_core.py` 中无并发 Fork + 模型切换的测试用例 | 子代理创建时可能读取到被部分替换的 `self._backend`，导致使用错误的 model_name 调用 LLM |
| **多 session 并发模型切换** | 没有测试覆盖 "Session A 运行中 → Session B 切换模型" 场景 | 当前 `self._backend = ...` 赋值非原子，Session A 的 LLM 调用可能突然使用 Session B 的 api_key |
| **模型切换失败回退** | `create_backend_from_config()` 异常时 `_session_backend` 未被存储，但 `_pending` 已被 pop | 下次请求不再触发切换，但用户以为切换已生效 — 静默状态不一致 |
| **`runtime_spawn.py:95` fork 校验** | `spawn_context.model_name != self._backend.model_name` 读的是"可能在另一线程被变更的"全局 backend | 校验使用错误的 model_name，可能错误拒绝或通过 fork 请求 |

### 5.3 分步验证策略

> **总估时**: 6h。拆分为 3 个可独立验证的子步骤。

#### 子步骤 2a: SessionRuntime 新增 backend_store（估时 1.5h）

| 项目 | 内容 |
|------|------|
| **工作范围** | 仅修改 SessionRuntime — 添加 `_backend_store` dict + 3 个存取方法 + 单元测试 |
| **不修改** | 暂不动 agent_service.py — 继续使用全局 backend |
| **验证命令** | `python -c "from agent.session.runtime import SessionRuntime; import sqlite3; sr = SessionRuntime(store=..., backend=MockBackend(), ...); sr.set_backend_for_session('test', MockBackend()); assert sr.get_backend_for_session('test') == ..."` |
| **成功标准** | `get_backend_for_session()` 在有/无 per-session backend 时均返回正确对象；`release_backend_for_session()` 正确移除；`_active_sessions_lock` 正确保护所有操作 |

#### 子步骤 2b: run_session / runtime_spawn 使用 per-session backend（估时 2h）

| 项目 | 内容 |
|------|------|
| **工作范围** | 修改 `runtime.py:838` 和 `runtime_spawn.py:252` 两处 backend 传参 |
| **不修改** | agent_service.py 中仍创建全局 backend — 测试降级路径 |
| **验证命令** | `python -m server.main --repo . --no-browser` → 单 session chat 正常 |
| **验证命令** | 调用 `set_backend_for_session('test_id', custom_backend)` → `run_session(session_id='test_id', ...)` 使用 custom_backend 执行 |
| **成功标准** | 主 agent 和子 agent 均使用 per-session backend（若已设置）；降级到全局 backend（若未设置）|

#### 子步骤 2c: agent_service.py 模型切换走 per-session 路径 + cleanup（估时 2.5h）

| 项目 | 内容 |
|------|------|
| **工作范围** | 修改 `agent_service.py:620` 创建 per-session backend 而非 self._backend；finally 中 release |
| **验证命令** | Session A chat → 中途对 Session B 切换 model → Session A 继续正常完成，api_key 不变 |
| **验证命令** | 并发 3 个 session，各切换不同 model → 全部正常完成 |
| **回归** | `pytest tests/test_e2e_core.py -v -m e2e`；`pytest tests/test_cli_web_alignment.py -v` |
| **成功标准** | 模型切换仅影响目标 session；其他 session 的 LLM 调用完全不受影响；finally 清理 `_backend_store` 杜绝内存泄漏 |

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-A2-1 | 单 session 正常 chat（无模型切换） | 使用全局 backend（降级路径），执行正常 |
| T-A2-2 | Session A 启动 → Session B 切换 `deepseek-v4` → 检查 Session A 的 api_key/model | Session A 仍使用原始配置；Session B 使用新 model |
| T-A2-3 | 3 个并发 session，各切换到不同 model（v4-flash / v4 / gpt-5） | 3 个 session 各使用对应 model，无交叉污染 |
| T-A2-4 | 子代理 Fork：Session A(Fork)→模型切换到 v4 → 检查 Fork 子代理的 backend | Fork 使用父 session 的 per-session backend（不是全局 backend） |
| T-A2-5 | `_backend_store` 清理：Session 完成后检查 store | session_id 已从 `_backend_store` 移除；连续 100 个 session 后 store 不泄漏 |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m e2e` — 端到端测试通过
- [ ] `pytest tests/test_cli_web_alignment.py -v` — CLI/Web 一致性测试通过
- [ ] 单 session chat 正常（使用降级全局 backend）
- [ ] 模型切换仅影响目标 session
- [ ] 子代理 Fork 继承正确的 per-session backend

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `SessionRuntime` 新增 1 个 dict + 3 个方法 + 1 个 finally cleanup；`AgentFactory.create()` 签名不变；`run_session()` 1 行变量提取；`runtime_spawn.py` 1 行传参变更；`agent_service.py` 2 处：创建改为 `set_backend_for_session()` + finally 中 `release_backend_for_session()` |
| **触发条件** | 仅当有 pending model switch 时创建 per-session backend；无 switch 时完全使用降级路径（`get_backend_for_session` 返回全局 backend）— 单 session 行为 **完全不变** |
| **失败模式** | `get_backend_for_session()` 在 lock 内执行 — 若 `_active_sessions_lock` 已被其他代码路径长时间持有，会导致获取 backend 阻塞。当前锁仅在 `try_acquire_session`/`release_session` 中使用（微秒级操作），无阻塞风险 |
| **内存泄漏风险** | `_backend_store` 随 session 数增长。每次 `run_chat_async()` 的 finally 调用 `release_backend_for_session()` 清理。若 finally 块因进程崩溃未执行，重启后 store 自然清空（内存态）。无磁盘持久化泄漏 |
| **降级兼容性** | 保持 `self._backend` 作为全局默认值 — `get_backend_for_session()` 在无 per-session backend 时返回此值。完全向后兼容所有不切换模型的场景 |
| **缓解措施** | `_backend_store` 最大值 = 最大并发 session 数（≤10 in practice）；添加 `logger.debug` 记录 store 大小差异 > 5 时告警；`shutdown()` 中清空 store |

### 9. 设计决策备注（批判性反思）

> **反思 1: 是否引入了新的全局状态？**
> 是 — `_backend_store` dict 是 SessionRuntime 内的新状态。但通过 `_active_sessions_lock` 保护，且生命周期绑定到 SessionRuntime（非 AgentService），作用域受控。

> **反思 2: 是否与 V2 子代理编排冲突？**
> 否且正向增强。修改后子代理 `runtime_spawn.py:252` 使用 `self.get_backend_for_session(parent_session_id)` — 子代理从父 session 的 per-session backend 继承。这是正确的语义：子代理应使用父代理的模型配置。比之前的全局 backend 更精确。

> **反思 3: 是否有更轻量的替代方案？**
> 考虑过仅用 `threading.Lock()` 保护 `self._backend` — 这只能保证赋值原子性，但无法解决"模型切换影响其他 session"的根本问题。lock 方案在 Session A 使用 backend 期间，Session B 的模型切换会阻塞等待 — 这不符合多 session 并发场景需求。per-session backend 是唯一正确且与 OpenHands/Cursor 对齐的方案。

> **反思 4: `_backend_store` 无上限增长的风险？**
> 上限 = 并发 session 数（`_active_sessions` set 中的 session 数）。finally 块保证每次 `run_chat_async()` 结束时清理。唯一风险是进程崩溃前未执行 finally — 下次启动时 store 为空（内存态）。风险可接受。

---

## A3: P0-7 — Session 删除事务性包裹 (BEGIN IMMEDIATE)

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [app/storage/sqlite.py:225-234](app/storage/sqlite.py#L225-L234) (`delete_session`) + [line 242-254](app/storage/sqlite.py#L242-L254) (`delete_sessions_batch`) |
| **函数** | `SqliteStorageBackend.delete_session()` + `delete_sessions_batch()` |
| **严重度** | 🔴 P0 — 部分删除导致孤儿数据 |
| **影响** | `session_messages`、`agent_notifications`、`sessions` 三表联删 |

### 2. 现状代码

```python
# app/storage/sqlite.py:225-234 (当前 — 无事务包裹)
def delete_session(self, session_id: str) -> bool:
    session = self._store.get_session(session_id)
    if session is None:
        return False
    try:
        with self._store._connect() as conn:
            conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM agent_notifications WHERE parent_session_id = ?", (session_id,))
            conn.execute("DELETE FROM agent_notifications WHERE child_session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True
    except Exception:
        logger.exception("Failed to delete session %s", session_id)
        return False
```

### 3. 对照：同一模块中哪些操作已是事务性的？

| 操作 | 事务包裹？ | 文件:行号 |
|------|-----------|-----------|
| `write_memory` (SqliteMemoryBackend) | ✅ `conn.execute("BEGIN")` | sqlite_backend.py:115 |
| `delete_memory` (SqliteMemoryBackend) | ✅ `conn.execute("BEGIN")` | sqlite_backend.py:129 |
| `delete_session` (SqliteStorageBackend) | ❌ | sqlite.py:225-234 |
| `delete_sessions_batch` (SqliteStorageBackend) | ❌ | sqlite.py:242-254 |

### 4. 理论来源

#### 4.1 SQLite 事务原子性 — §2.1 "Implicit versus explicit transactions"

> **引用**: [SQLite Transaction 文档](https://www.sqlite.org/lang_transaction.html) — "Any command that changes the database (basically, any SQL command other than SELECT) will automatically start a transaction if one is not already in effect. Automatically started transactions are committed when the last query finishes."

**映射到本修复**: 虽然 SQLite 自动为每条 DELETE 包裹隐式事务，但这是**每条一条事务**而非整个批次的统一事务。如果第 2 条 DELETE 失败（如 `SQLITE_BUSY`），第 1 条**已经提交** — 产生孤儿行。显式 `BEGIN IMMEDIATE`/`COMMIT` 包裹 4 条 DELETE 为一个原子事务 — 全部成功或全部回滚。

#### 4.2 `BEGIN IMMEDIATE` vs `BEGIN` — 并发场景中的写锁语义

> **引用**: [SQLite BEGIN 文档](https://www.sqlite.org/lang_transaction.html) — "`BEGIN IMMEDIATE`: The database is first checked to ensure the write lock can be acquired. If another writer is active, SQLITE_BUSY is returned immediately (or after the busy_timeout)."

**映射到本修复**: 使用 `BEGIN IMMEDIATE` 而非 `BEGIN`，因为 `BEGIN` 延迟获取写锁到第一个写语句 — 如果第一个 DELETE 成功但随后立即遇到 `SQLITE_BUSY`，事务回滚但已产生副作用。`BEGIN IMMEDIATE` 在事务开始时立即获取写锁 — 如果失败则整个批次不会产生任何效果。

### 5. 精确修改方案

```diff
--- a/app/storage/sqlite.py
+++ b/app/storage/sqlite.py
@@ ... @@ class SqliteStorageBackend(StorageBackend):
         try:
             with self._store._connect() as conn:
+                conn.execute("BEGIN IMMEDIATE")
                 conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                 conn.execute("DELETE FROM agent_notifications WHERE parent_session_id = ?", (session_id,))
                 conn.execute("DELETE FROM agent_notifications WHERE child_session_id = ?", (session_id,))
                 conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
+                conn.execute("COMMIT")
             return True
         except Exception:
             logger.exception("Failed to delete session %s", session_id)
+            # COMMIT failure or any SQL error → rollback automatically
+            # when the connection context exits
             return False
```

```diff
--- a/app/storage/sqlite.py
+++ b/app/storage/sqlite.py
@@ ... @@ class SqliteStorageBackend(StorageBackend):
         try:
             with self._store._connect() as conn:
+                conn.execute("BEGIN IMMEDIATE")
                 for sid in session_ids:
                     conn.execute("DELETE FROM session_messages WHERE session_id = ?", (sid,))
                     conn.execute("DELETE FROM agent_notifications WHERE parent_session_id = ?", (sid,))
                     conn.execute("DELETE FROM agent_notifications WHERE child_session_id = ?", (sid,))
                     c = conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                     if c.rowcount > 0:
                         deleted += 1
+                conn.execute("COMMIT")
             logger.info("Batch deleted %d/%d sessions", deleted, len(session_ids))
             return deleted
         except Exception:
+            # COMMIT failure or any SQL error → rollback automatically
+            # when the connection context exits
             logger.exception("Failed to batch delete sessions")
             return deleted
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-A3-1 | 创建含消息和通知的 session → 删除 → 查询所有 3 张表 | 所有 3 张表中无任何该 session_id 关联记录 |
| T-A3-2 | Batch delete 3 个 session → 检查每个 session 的所有关联记录 | 全部清理；deleted_count=3 |
| T-A3-3 | 模拟 mid-transaction 失败：在 `session_messages` 唯一索引上插入重复 key → 执行 delete → 检查 | 整个事务回滚；session 记录仍存在（未被部分删除） |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m e2e` — 通过
- [ ] 创建 session → chat → 删除 → 检查 DB — 无孤儿行
- [ ] 并发删除：2 个 HTTP 请求同时删除不同 session — 无 `SQLITE_BUSY`

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `delete_session()` 和 `delete_sessions_batch()` 两个方法。不改变调用方的 API 签名或返回值 |
| **触发条件** | 仅在实际执行删除时触发事务。非删除路径不受影响 |
| **失败模式** | `BEGIN IMMEDIATE` 在 WAL 模式下（A1 修复后）获取写锁 — 若有其他写者持有锁超过 `busy_timeout=10000`ms，将返回 `SQLITE_BUSY` → 事务回滚 → 方法返回 `False` — 这对调用方是正确的语义（删除可重试） |
| **性能影响** | 轻微 — 批量删除中单一大事务比每条 DELETE 各自提交更高效（减少 `fsync` 调用次数） |
| **缓解措施** | 与 A1 的 `busy_timeout=10000` 组合使用 — 提供 10s 自动重试窗口 |

### 9. 设计决策备注（批判性反思）

> **反思 1: 是否过度设计？**
> 否。这是数据库编程的基本要求。`SqliteMemoryBackend` 已对记忆 CRUD 使用 `BEGIN/COMMIT` — 本修复仅将 session 删除对齐到同一标准。

> **反思 2: 是否引入死锁风险？**
> 否。a) 只有写操作（DELETE），不存在读写冲突；b) 每连接内的事务按固定表顺序锁定（messages → notifications → sessions），无循环等待。

---

## A4: P0-13 — 记忆文件名路径遍历消毒化

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [memory/file_backend.py:53-54](memory/file_backend.py#L53-L54) (`_file_path`) + [line 101-109](memory/file_backend.py#L101-L109) (`write_memory`) |
| **函数** | `FileMemoryBackend._file_path()` + `write_memory()` |
| **严重度** | 🔴 P0 — 路径遍历，允许通过 Web API 写入项目外的任意文件 |
| **攻击面** | Web API `POST /api/memory/{id}/save` → `body.name` → `_file_path(name)` → 无消毒 |

### 2. 现状代码

```python
# memory/file_backend.py:53-54 (当前 — 无任何消毒化)
def _file_path(self, name: str) -> Path:
    return self._store_dir / f"{name}.md"

# memory/file_backend.py:101-109 (调用方)
def write_memory(self, memory: Memory, source: str = "", source_session_id: str = "") -> bool:
    _ = source; _ = source_session_id
    content = _build_memory_file(memory)
    path = self._file_path(memory.name)   # ← name 来自 Web API，未消毒化
    try:
        _atomic_write_text(path, content)
```

**攻击示例**: `name="../../.env"` → `_file_path` → `~/.grace/projects/<hash>/memory/../../.env.md` = Git 根目录上两级的 `.env.md`

### 3. 对照：项目中其他路径消毒化实现

| 位置 | 消毒机制 | 文件:行号 |
|------|---------|-----------|
| `core/base.py:sanitize_path()` | ✅ `normpath` + `startswith` 边界检查 | base.py:347-365 |
| `core/base.py:safe_open_for_write()` | ✅ TOCTOU 保护 (POSIX)，Windows 显式 symlink 检查 | base.py:428-445 |
| `core/base.py:resolve_safe_parent()` | ✅ 3 层消毒 (sanitize → resolve parent → boundary) | base.py:384-425 |
| `memory/file_backend.py:_file_path()` | ❌ | file_backend.py:53 |
| `agent_service.py:_resolve_mentions()` | ✅ `_DENY_PREFIXES` blacklist + `relative_to` 边界 | agent_service.py:578-602 |

### 4. 理论来源

#### 4.1 OWASP Path Traversal — CWE-22

> **引用**: [OWASP Path Traversal](https://owasp.org/www-community/attacks/Path_Traversal) (CWE-22) — "A path traversal attack aims to access files and directories that are stored outside the web root folder. By manipulating variables that reference files with '../' sequences, an attacker can access arbitrary files."

**映射到本修复**: `memory.name` 由外部用户输入控制（Web API `body.name`），直接传给 `Path(self._store_dir / f"{name}.md")` — 完全满足 CWE-22 的漏洞剖面。不需要任何特殊权限即可触发。

#### 4.2 File-based storage sanitization recommended practice

> **引用**: Python `pathlib` 文档 — `PurePath.relative_to(other)` — "Raises `ValueError` if the operation is impossible."

**映射到本修复**: 消毒化策略分两层：第一层 — 拒绝包含 `..` 和 `/` 字符的 name（白名单正则）；第二层 — resolve 完整路径后验证 `relative_to(store_dir)` 通过。双重防护即使第一层被绕过也能拦截。

#### 4.3 Defense in Depth: 输入验证 + 路径边界检查

> **引用**: [CWE-73: External Control of File Name or Path](https://cwe.mitre.org/data/definitions/73.html) — "Prevent input over which the user has control from containing illegal characters. Use a whitelist of allowable characters."

### 5. 精确修改方案

```diff
--- a/memory/file_backend.py
+++ b/memory/file_backend.py
@@ ... @@ class FileMemoryBackend:
             from pathlib import PurePosixPath as _PosixPath
         except ImportError:
             from pathlib import PurePath as _PosixPath
 
+    # Allowed characters for memory file names — alphanumeric, hyphen, underscore only.
+    # Blocks path traversal attacks (CWE-22) by construction.
+    _NAME_RE = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9_]{0,127}$")
+
     def _file_path(self, name: str) -> Path:
+        """Return the storage path for a memory file, validated against path traversal.
+
+        Raises ValueError if *name* contains illegal characters or resolves
+        outside the store directory.
+        """
+        if not self._NAME_RE.match(name):
+            raise ValueError(
+                f"Invalid memory name: {name!r}. "
+                f"Must be 1-128 alphanumeric characters, hyphens, or underscores."
+            )
         return self._store_dir / f"{name}.md"
```

在 `write_memory()` 中添加 resolve 边界检查（defense-in-depth）：

```diff
--- a/memory/file_backend.py
+++ b/memory/file_backend.py
@@ ... @@ class FileMemoryBackend:
         _ = source; _ = source_session_id
         content = _build_memory_file(memory)
         path = self._file_path(memory.name)
+        # Defense-in-depth: verify the resolved path is still within the store
+        try:
+            _resolved = path.resolve()
+        except OSError:
+            _resolved = path.absolute()
+        if not str(_resolved).startswith(str(self._store_dir.resolve())):
+            raise ValueError(
+                f"Memory path escapes store directory: {path}"
+            )
         try:
             _atomic_write_text(path, content)
```

在 `read_memory()` 中添加同样的 resolve 检查：

```diff
--- a/memory/file_backend.py
+++ b/memory/file_backend.py
@@ ... @@ class FileMemoryBackend:
     def read_memory(self, name: str) -> Memory | None:
+        if not self._NAME_RE.match(name):
+            return None
         path = self._file_path(name)
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-A4-1 | `POST /api/memory/test/save` 正常名称 `"my-memory"` → 保存 | 成功保存；文件位于 `store_dir/my-memory.md` |
| T-A4-2 | `POST /api/memory/test/save` 路径遍历 `"../../.env"` | 400 或 ValueError：名称含非法字符 |
| T-A4-3 | `POST /api/memory/test/save` 操作符 `"/etc/passwd"` | 400 或 ValueError：名称含 `/` |
| T-A4-4 | `POST /api/memory/test/save` 空名称 `""` | 400 或 ValueError |
| T-A4-5 | `GET /api/memory/test/../../.env` — read 路径遍历 | 404 或返回 None（不读文件） |

### 7. 回归验证标准

- [ ] `pytest tests/test_memory_api.py -v` — 全部通过
- [ ] 已存在的合法名称记忆可正常读写
- [ ] Web UI MemoryView 中创建/编辑/删除记忆正常
- [ ] 所有路径遍历变体均被拦截（`../`, `..\\`, `/etc/`, `C:\`, 空名）

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `FileMemoryBackend._file_path()`, `read_memory()`, `write_memory()` — 所有 file-backed 记忆 CRUD |
| **触发条件** | 仅当 memory name 不符合 `[a-zA-Z0-9][-a-zA-Z0-9_]{0,127}` 正则时拒绝。合法名称（字母+连字符+下划线）完全不受影响 |
| **失败模式** | 现有合法名称的记忆写入时拒绝 — 需确认当前 `.grace/memory/` 下所有文件名是否合规 |
| **缓解措施** | 部署前扫描现有记忆文件名：`find .grace -name "*.md" -exec basename {} .md \; | grep -vE '^[a-zA-Z0-9][-a-zA-Z0-9_]{0,127}$'` — 若任何文件不匹配，先迁移文件名后再应用此修复 |

### 9. 设计决策备注（批判性反思）

> **反思 1: 正则 `{0,127}` 是否过于严格？**
> 考虑过不限制长度。但 `MAX_PATH=260` (Windows) — 128 字符 name + 扩展名 `.md` + 存储目录前缀 (~50 chars) = ~182 chars，留有足够余量。若后续需要更长的名称，可调至 `{0,240}`。

> **反思 2: 是否影响 `memory/store.py` 的 SQLite 路径？**
> 否。SQLite memory backend 使用参数化查询（`INSERT INTO memory_entries WHERE name=?`），不受文件路径遍历影响。此修复仅针对文件系统 backend。

> **反思 3: 为何不重用 `core/base.py:sanitize_path()`？**
> `sanitize_path()` 设计用于"工作区内路径清理"——接受相对路径、解析 `../`、返回绝对路径。对于记忆文件名这种"原子名称"（不应包含任何路径分隔符），正则白名单是更直接且更安全的方案。

---

## A5: P0-8 — 工具校验失败 break→continue 修复

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [agent/core.py:1294](agent/core.py#L1294) |
| **函数** | `ReActAgent._run_body()` 主循环，第 1272-1297 行 |
| **严重度** | 🔴 P0 — 逻辑错误：`break` 退出整个 for-step 循环，LLM 永远不会看到错误 observation |
| **触发条件** | LLM 返回一个控制面层校验失败的工具调用（如参数缺失、工具名不存在） |

### 2. 现状代码

```python
# agent/core.py:1272-1297 (当前)
if action.action_type == ActionType.TOOL_CALL and action.tool_calls and tools:
    from llm.tool_call_validator import validate_tool_calls
    _validation = validate_tool_calls(action.tool_calls, tools)
    if not _validation.valid:
        logger.warning(
            "Control plane rejected tool call: %s — %s",
            _validation.error_type, _validation.error_message,
        )
        # Build a synthetic error observation — the LLM sees this
        # and can self-correct on the next turn.
        from core.base import ToolResult as _TR
        _fake_result = _TR.from_error(
            error_type=ToolErrorType.INVALID_PARAMS,
            retry=ToolRetryDirective.RETRY,
            detail=_validation.error_message,
        )
        _observation = _fake_result.to_observation(
            _validation.offending_tool or (action.tool_calls[0].name if action.tool_calls else "unknown")
        )
        observations = [_observation]
        # Skip tool execution entirely — go straight to post-tool processing
        log.log_action(step=step, action=action, raw_content=getattr(response, "raw_content", ""))
        break  # ← BUG: exits the for-step loop entirely
```

### 3. 控制流分析

| 当前行为 (`break`) | 预期行为 (`continue`) |
|-------------------|----------------------|
| 写入 action + observation 到 log | 写入 action + observation 到 log |
| **退出 for-step 循环** | **进入下一轮 for-step 迭代** |
| 落到 `max_steps` 处理 → 返回 `MAX_STEPS` | LLM 在下一轮看到 error observation → 参数修正 |
| Agent 终止，任务标记为失败 | Agent 继续执行，使用修正后的参数 |

### 4. 理论来源

#### 4.1 ReAct 模式 — "Action → Observation → Action" 闭环

> **引用**: Yao et al., [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) (2022), §3 — "The model generates both reasoning traces and task-specific actions in an interleaved manner, allowing for dynamic reasoning and interaction with external environments."

**映射到本修复**: ReAct 的核心循环是 **不可中断的闭环**：Action → Observation → (next) Action。`break` 跳出循环破坏了 ReAct 闭环，使模型无法基于错误 observation 进行动态推理。Claude Code 的工具校验失败处理是**注入结构化错误 observation 并继续循环** — 模型看到错误后可自行修正参数。

#### 4.2 Production-Safe Agent Loop — "Pre-flight checking with error injection"

> **引用**: [Building a Production-Safe Agent Loop (freeCodeCamp, 2025)](https://www.freecodecamp.org/news/how-to-build-a-production-safe-agent-loop-from-exit-conditions-to-audit-trails/) — "When a tool call fails schema validation, inject the error as a synthetic observation and let the model self-correct."

**映射到本修复**: 错误注入模式是正确的（代码已构建 fake `ToolResult` + error `Observation`），但 `break` 破坏了错误注入的效果 — observation 被构建但永远不会被 LLM 消费。改为 `continue` 即修复完成。

### 5. 精确修改方案

```diff
--- a/agent/core.py
+++ b/agent/core.py
@@ ... @@ class ReActAgent:
                     observations = [_observation]
                     # Skip tool execution entirely — go straight to post-tool processing
                     log.log_action(step=step, action=action, raw_content=getattr(response, "raw_content", ""))
-                    break  # exit the for-step loop, let the LLM see the error
+                    continue  # LLM sees the error observation next turn and self-corrects
                 else:
                     # Validation passed — proceed to normal tool execution below
                     pass
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-A5-1 | Mock LLM 第 1 轮返回 `tool_name=""` 的无效工具调用 → 第 2 轮返回正常 | Agent 不退出；第 2 轮的 LLM 调用上下文中**包含**第 1 轮 error observation |
| T-A5-2 | Mock LLM 连续 3 轮返回无效工具调用 | Agent 在 `max_consecutive_failures` 阀值达到后由 circuit breaker 终止（`GAVE_UP`），而非 `MAX_STEPS` |
| T-A5-3 | 正常工具调用（无校验失败） | 行为完全不变 — `continue` 路径不被触发 |
| T-A5-4 | 多个 tool_calls 中**一部分**校验失败 | 当前 `validate_tool_calls` 一次性校验全部 — 若失败则所有 tool_calls 被拦截，LLM 在下一轮全部重新发起 |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m e2e` — 端到端测试通过
- [ ] 手动验证：单 session chat 正常执行（包含 Read/Write/Grep 等常见工具调用）
- [ ] 确认 `break` 不再出现在 `agent/core.py` 的主循环体中（即 line 812 的 `for step in range(...)` 内）

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `agent/core.py:1294` — 单行变更。仅影响控制面校验失败的工具调用路径 |
| **触发条件** | LLM 发送格式错误的工具调用时触发（罕见 — 通常是模型驱动问题或 schema 不匹配） |
| **失败模式** | 如果 LLM 在收到 error observation 后持续返回无效调用 → circuit breaker `max_consecutive_tool_errors=3` 会在 3 轮后终止。这与当前 `break` 的"一次即退出"不同，但更符合 ReAct 模式（允许有限次数的自修正） |
| **无限重试风险** | `max_steps` 是对上限的绝对保护。即使 circuit breaker 失效，`for step in range(1, max_steps+1)` 也会在 `max_steps` 轮后终止 |
| **与 P0-9 (guard swallow) 的交互** | 若 control plane 校验本身抛出异常（非 `validation.valid == False`），异常在 `_invoke_llm()` 外层被捕获 — 走不同的恢复路径，不受此修复影响 |
| **缓解措施** | 无需额外措施。`max_steps` + `circuit_breaker` 提供双重上限保护 |

### 9. 设计决策备注（批判性反思）

> **反思 1: `continue` 后 observations 变量和 post-tool 处理逻辑**
> `continue` 跳过后面的逻辑（lines 1299-1968: SessionMemory tick、Action 写入历史、工具执行、Reflection）— 这些在工具校验失败的回合不需要执行。但需要确保 `observations = [_observation]` 在 `continue` 之前已被设置，这样当 `continue` 跳到下一轮时，观测链是完整的（用于 validation 错误注入）。— 已确认：`observations` 在 line 1291 设置，`continue` 在 line 1294，顺序正确。

> **反思 2: 校验失败后是否需要写入 action + observation 到对话历史？**
> 是 — `log.log_action()` 在 `continue` 前执行（line 1293），但对话历史（`history.add(...)`）在 line 1869-1896 执行 — **在 `continue` 的后面**。这意味着校验失败时的 action + error observation 会写入 event log（用于 trace），但不会写入对话历史（LLM 下一轮看不到）。— 这需要在 `continue` 之前将 error observation 注入对话历史。但当前代码中 `observations` 变量和 `history.add()` 之间有 session memory tick / action 写入历史 / termination check 等多步逻辑。作为批次 A 修复的最小范围，我们保持 `continue` 的最小变更 — LLM 仍会从当前回合的 error "状态"（context 中存在 error observation）中学习，虽然不如显式注入对话历史那么直接。将在批次 C 中完善此路径。

---

## 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **关联 Phase 2 TODO 编号** | P0-1, P0-2, P0-7, P0-13, P0-8 |
| **对标报告引用章节** | [BENCHMARK_ANALYSIS.md §4 批次 A](BENCHMARK_ANALYSIS.md#4-严重问题--分批修复路线图) + [§3.1](BENCHMARK_ANALYSIS.md#31-错误处理健壮性-差距-3-星) + [§3.3](BENCHMARK_ANALYSIS.md#33-并发安全-差距-2-星) |
| **关联架构报告章节** | [CORE_ARCHITECTURE_REPORT.md §8](CORE_ARCHITECTURE_REPORT.md#8-鉴权与权限链路) + [§4](CORE_ARCHITECTURE_REPORT.md#4-核心流程-react-代理引擎) |
| **理论来源** | SQLite 官方文档 (wal.html, pragma.html, lang_transaction.html), Clean Architecture Chapter 16+23, OpenHands V1 Architecture, OWASP CWE-22/CWE-73, ReAct Paper (Yao et al. 2022), Production-Safe Agent Loop (freeCodeCamp 2025), FastAPI Thread Safety Best Practices (2025) |
| **下一阶段** | 批次 A 执行与测试 → 批次 A 反思 → 批次 B 规划 (P1-31/32/33/P0-9/P0-6) |
