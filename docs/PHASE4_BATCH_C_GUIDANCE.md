# Phase 4: 批次 C 精准定位与理论指导方案

> **文档版本**: 1.0
> **生成时间**: 2026-07-21
> **关联 Phase 2 TODO 编号**: P0-3, P0-11, P0-12, P1-29, P0-4 + 反思增强 ×4
> **对标报告引用**: [BENCHMARK_ANALYSIS.md §4-批次C](BENCHMARK_ANALYSIS.md#4-严重问题--分批修复路线图) + [§3.1](BENCHMARK_ANALYSIS.md#31-错误处理健壮性-差距-3-星) + [§3.4](BENCHMARK_ANALYSIS.md#34-web-前端质量-差距-3-星)
> **前置条件**: 批次 A (commit `d841fba`) + 批次 B (commit `662451a`) 已完成
> **预计总工时**: 17h
> **批次 B 反思纳入**: 5 项调整（见文末 [批次 B 反思采纳清单](#批次-b-反思采纳清单)）
> **C5 特殊说明**: C5 是代码卫生项（SessionRuntime.dispose），允许在主线回归全绿后独立提交

---

## 目录

- [附录 B: missing-logger-import 风险文件清单](#附录-b-missing-logger-import-风险文件清单)
- [C0: B1 安全增强 — Bash 读取场景 allowed_read_paths + tee/dd 提取](#c0-b1-安全增强--bash-读取场景-allowed_read_paths--teedd-路径提取)
- [C1: P0-3 — 模型切换自定义配置持久化](#c1-p0-3--模型切换自定义配置持久化)
- [C2: P0-11 — API client AbortController](#c2-p0-11--api-client-abortcontroller)
- [C3: P0-12 — dangerouslySetInnerHTML XSS 修复](#c3-p0-12--dangerouslysetinnerhtml-xss-修复)
- [C4: P1-29 — LLM 重试 jitter](#c4-p1-29--llm-重试-jitter)
- [C5: P2 代码卫生 — SessionRuntime.dispose() + logger import 修复](#c5-p2-代码卫生--sessionruntimedispose--logger-import-修复)
- [批次 B 反思采纳清单](#批次-b-反思采纳清单)
- [元数据](#元数据)

---

## 附录 B: missing-logger-import 风险文件清单

> **扫描范围**: 项目根目录所有 `.py` 文件（排除 `.git`, `__pycache__`, `.venv`, `node_modules`, `web`, `dist`, `.grace`）
> **扫描方法**: 检测 `logger.<method>()` 调用存在但缺少 `import logging` + `logger = getLogger(__name__)` 的文件
> **扫描时间**: 2026-07-21（批次 C 前置扫描）

### 结果

| 文件 | 风险等级 | 问题 | 使用位置 |
|------|---------|------|---------|
| `core/base.py` | **HIGH** | 缺少 `import logging` + `logger = getLogger(__name__)` | [line 520](core/base.py#L520): `ToolRegistry.register()` — 工具别名冲突时记录 warning |
| `entry/chat.py` | **MEDIUM** | 缺少 `import logging` + `logger = getLogger(__name__)` | [line 172](entry/chat.py#L172): verify script 加载失败时记录 warning |

### 处置

| 文件 | 风险等级 | 批次处置 | 位置 |
|------|---------|---------|------|
| `core/base.py` | HIGH | **C5 子任务** — 核心基础设施层，修复为显式 import | C5-2 |
| `entry/chat.py` | MEDIUM | **C5 子任务** — CLI 入口层，修复为显式 import | C5-3 |

> **总计**: 2 个风险文件。批次 B 修复过程中暴露了 `hitl/pipeline.py` 的同类型问题（已在 B1 中修复）。此扫描确认再无遗漏。

---

## C0: B1 安全增强 — Bash 读取场景 allowed_read_paths + tee/dd 路径提取

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [core/policy_registry.py:306-318](core/policy_registry.py#L306-L318) (B1-SecurityBundle 新增代码区域) |
| **函数** | `PolicyAwareToolRegistry._check_tool_call()` — Bash 策略检查段 |
| **严重度** | 🟠 P1 — B1 只添加了**写入**检查（`allowed_write_paths`），缺失对称的**读取**检查（`allowed_read_paths`） |
| **关联 B1 修复** | B1 添加了 `strict_file_scope` 下的 Bash **写**目标检查，但 `allowed_read_paths`（仅允许读取指定路径）在 Bash 场景下完全未检查 |

### 2. 现状代码 (B1 修复后)

```python
# core/policy_registry.py:306-318 (B1 添加 — 仅检查写入)
if name == "Bash" and self._phase_policy.strict_file_scope:
    _cmd = str(params.get("command", "") or "")
    _args = params.get("args", []) or []
    _targets = _extract_shell_file_targets(_cmd, _args)
    _write_allowed = self._phase_policy.allowed_write_paths
    for _target in _targets:
        _normalized = normalize_repo_path(_target, self._repo_path)
        if _write_allowed is not None and _normalized not in _write_allowed:
            return (
                f"[RUNTIME BLOCK] BASH PATH DENIED: '{_normalized}' is "
                f"outside the allowed write scope in strict_file_scope mode. "
                f"Allowed: {', '.join(sorted(_write_allowed)) or '(none)'}"
            )
# ❌ 缺少：Bash 读取时 allowed_read_paths 检查
```

### 3. 不对称漏洞

| 场景 | B1 修复后行为 | 期望行为 |
|------|-------------|---------|
| `allowed_read_paths=["src/"]` + Bash `cat /etc/shadow` | **无检查，通过** ❌ | **被拦截**: Bash 读取目标 `/etc/shadow` 不在 `src/` 范围内 |
| `allowed_read_paths=["src/"]` + Bash `cat src/config.py` | 通过 ✅ | 通过 ✅ |
| `allowed_read_paths=["src/"]` + Bash `tee /tmp/out </dev/null` | **无检查（tee 未提取）** ❌ | **被拦截**: `tee` 写入 `/tmp/out` 不在 `src/` 范围内 |

### 4. 理论来源

#### 4.1 OWASP CWE-22 + CWE-73 组合

> **引用**: [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html) — "The software uses external input to construct a pathname that is intended to identify a file or directory, but does not properly neutralize special elements that can resolve to a pathname outside of a restricted directory."
>
> **引用**: [CWE-73: External Control of File Name or Path](https://cwe.mitre.org/data/definitions/73.html) — "The software allows user input to control or influence paths or file names that are used in filesystem operations, enabling an attacker to access or modify otherwise protected system resources."

**映射到本修复**: B1 的写入检查覆盖了 CWE-73（修改受保护文件）但未覆盖 CWE-22 的**读取**方向。`allowed_read_paths` 的语义是"代理只能读取这些路径内的文件"——Bash 的 `cat`/`head`/`tail`/`less` 必须遵守与 Read/Grep 相同的限制。此外 `tee` 是写入工具但格式与 `>` 不同（管道型写入），`dd of=` 是 POSIX 标准写入工具但格式完全不同。两者均在 B1 的 `_extract_shell_file_targets` 覆盖范围之外。

#### 4.2 Saltzer & Schroeder — Complete Mediation

> **引用**: Saltzer & Schroeder (1975), Principle of Complete Mediation — "Every access to every object must be checked for authority."

**映射到本修复**: Bash 作为"万能适配器"（CC term）必须为**每个方向**接受完全检查——读和写。B1 只覆盖了写方向（遵循 B1-SecurityBundle 的写入焦点），C0 补全读方向。

### 5. 精确修改方案

#### 修改: `core/policy_registry.py` — `_extract_shell_file_targets` 增强 + `_check_tool_call` 读检查

```diff
--- a/core/policy_registry.py
+++ b/core/policy_registry.py
@@ ... @@ def _extract_shell_file_targets(command: str, args: list[str]) -> list[str]:
 
+    # Pipe-to-file: tee file
+    for m in _re.finditer(r'\btee\s+(\S+)', _full):
+        _path = m.group(1).strip('"\'"')
+        if _path and not _path.startswith('-'):
+            targets.append(_path)
+
+    # dd output: dd of=/path/to/file
+    for m in _re.finditer(r'\bdd\b.*?\bof=(\S+)', _full):
+        _path = m.group(1).strip('"\'"')
+        if _path and not _path.startswith('/dev/'):
+            targets.append(_path)
+
+    # Common read commands: target is last non-flag argument
+    _READ_CMDS = {'cat', 'head', 'tail', 'less', 'more', 'wc'}
+    _cmd_base = command.split()[0] if command.strip() else ""
+    if _cmd_base in _READ_CMDS:
+        _parts = _full.split()
+        for _p in reversed(_parts[1:]):
+            if not _p.startswith('-'):
+                _path = _p.strip('"\'"')
+                targets.append(_path)
+                break
+
    # Common destructive commands: target is the last non-flag argument
    _DESTRUCTIVE_CMDS = {'rm', 'rmdir', 'chmod', 'chown', 'mv', 'cp'}
    _cmd_base = command.split()[0] if command.strip() else ""
    if _cmd_base in _DESTRUCTIVE_CMDS:
        _parts = _full.split()
        for _p in reversed(_parts[1:]):
            if not _p.startswith('-'):
                targets.append(_p.strip('"\'"'))
                break

    return targets
```

在 `_check_tool_call` 中添加读取路径检查（Bash 策略区块内）：

```diff
--- a/core/policy_registry.py
+++ b/core/policy_registry.py
@@ ... @@ class PolicyAwareToolRegistry(ToolRegistry):
         if name == "Bash" and self._phase_policy.strict_file_scope:
             _cmd = str(params.get("command", "") or "")
             _args = params.get("args", []) or []
             _targets = _extract_shell_file_targets(_cmd, _args)
+
+            # ── Read path check (C0, symmetric with B1 write check) ──
+            _read_allowed = self._phase_policy.allowed_read_paths
+            for _target in _targets:
+                _normalized = normalize_repo_path(_target, self._repo_path)
+                if _read_allowed is not None and _normalized not in _read_allowed:
+                    return (
+                        f"[RUNTIME BLOCK] BASH READ PATH DENIED: '{_normalized}' is "
+                        f"outside the allowed read scope. "
+                        f"Allowed: {', '.join(sorted(_read_allowed)) or '(none)'}. "
+                        f"Use Read or Grep for files within the allowed scope."
+                    )
+
+            # ── Write path check (B1, preserved) ──
             _write_allowed = self._phase_policy.allowed_write_paths
             for _target in _targets:
                 _normalized = normalize_repo_path(_target, self._repo_path)
                 if _write_allowed is not None and _normalized not in _write_allowed:
                     return (
                         f"[RUNTIME BLOCK] BASH PATH DENIED: '{_normalized}' is "
                         f"outside the allowed write scope in strict_file_scope mode. "
                         f"Allowed: {', '.join(sorted(_write_allowed)) or '(none)'}"
                     )
        return None
```

### 6. 统一测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-C0-1 | `allowed_read_paths=["src/"]` → Bash `cat /etc/shadow` | **被拦截**：RUNTIME BLOCK BASH READ PATH DENIED |
| T-C0-2 | `allowed_read_paths=["src/"]` → Bash `cat src/config.py` | **通过** |
| T-C0-3 | `allowed_read_paths=["src/"]` → Bash `head -5 src/config.py` | **通过** |
| T-C0-4 | `allowed_write_paths=["src/"]` → Bash `tee /tmp/log` | **被拦截**（tee 目标在允许范围外） |
| T-C0-5 | `allowed_write_paths=["src/"]` → Bash `dd of=src/out.bin if=/dev/zero bs=1 count=1` | **通过**（of=src/out.bin 在允许范围内） |
| T-C0-6 | `allowed_write_paths=["src/"]` → Bash `dd of=/tmp/evil if=/dev/zero bs=1 count=1` | **被拦截**（dd 目标在允许范围外） |
| T-C0-7 | `allowed_read_paths=["src/"]` + `allowed_write_paths=["src/"]` → Bash `cat src/a.py > src/b.py` | `src/a.py` 读取检查通过 + `src/b.py` 写入检查通过 → 整体通过 |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m "not e2e"` 通过
- [ ] B1-SecurityBundle 回归：B1 的 7 项测试全部通过（C0 不破坏写入检查）

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `_extract_shell_file_targets()` 新增 3 个正则模式；`_check_tool_call()` Bash 区块新增读取检查（3 行） |
| **触发条件** | 仅 `strict_file_scope=True` 时新增检查生效 |
| **误拦风险** | `_READ_CMDS` 包含 `wc`——若 `Bash("wc -l src/*.py")` 被误拦因 `*.py` 扩展不在 allowed_read_paths（列表不含 `*.py`）中。`*` 模式不在路径提取范围内（正则只匹配非空格字符），所以 `wc` 的参数 `src/*.py` 会被提取为字面 `src/*.py`，不符合任何 `allowed_read_paths` 条目 → 正确拦截 |
| **与 B1 的兼容性** | C0 代码紧接 B1 的 `_targets` 提取之后——完全增量，无破坏 |

### 9. 设计决策备注

> **反思: 为何 `_READ_CMDS` 包含 `wc`？**
> `wc` 读取文件统计行数/词数——本质是读操作。如果代理配置为仅读取 `src/`，使用 `Bash("wc debug/secrets.txt")` 读取调试文件应被拦截。包含 `wc` 是防御正确的。

---

## C1: P0-3 — 模型切换自定义配置持久化

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [server/services/agent_service.py:96-125](server/services/agent_service.py#L96-L125) (init) + [line 264-282](server/services/agent_service.py#L264-L282) (`_apply_cli_overrides`) |
| **函数** | `AgentService.__init__()` + `_apply_cli_overrides()` |
| **严重度** | 🔴 P0 — CLI 覆盖 `base_url` 后模型切换即丢失 |

### 2. 现状代码

```python
# server/services/agent_service.py:96-125 — init
self._config: AppConfig = load_config(config_path)
self._apply_cli_overrides(model, provider, api_key, base_url, max_steps)
self._backend = create_backend_from_config({
    "provider": self._config.llm.provider,    # ← CLI overrides merged into config here
    ...
    "base_url": self._config.llm.base_url or None,
})

# server/services/agent_service.py:620-627 (B1 修复后) — model switch
_session_backend = create_backend_from_config({
    "provider": _provider or self._config.llm.provider,
    ...
    "base_url": self._config.llm.base_url or None,  # ← reads static config, NOT effective overrides
})
```

**问题**: `self._config` 在 init 时已通过 `_apply_cli_overrides` 合并了 CLI 覆盖，所以模型切换时读取 `self._config.llm.base_url` **应该**得到有效值。但如果在运行期间有动态修改（如前端的 `/api/sessions/{id}/model` 传入 baseUrl），该值**仅存储在 `_session_backend` 实例中**，不会回写到 `self._config`。下次切换模型时会回退。

### 3. 当前最轻修复：添加 `_effective_llm_config` 字段

在 `__init__` 中快照有效 LLM 配置，模型切换时读取此快照。

### 5. 精确修改方案

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
         self._config: AppConfig = load_config(config_path)
         self._apply_cli_overrides(model, provider, api_key, base_url, max_steps)

+        # Save effective LLM config snapshot — preserves CLI overrides and
+        # dynamic updates across model switches (P0-3).
+        self._effective_llm_config = {
+            "provider": self._config.llm.provider,
+            "api_key": self._config.llm.api_key or None,
+            "base_url": self._config.llm.base_url or None,
+            "max_tokens": self._config.llm.max_tokens,
+            "timeout_seconds": self._config.llm.timeout_seconds,
+        }
```

模型切换处读取此快照：

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
                 _session_backend = create_backend_from_config({
-                    "provider": _provider or self._config.llm.provider,
+                    "provider": _provider or self._effective_llm_config["provider"],
                     "model": _model,
-                    "api_key": self._config.llm.api_key or None,
-                    "base_url": self._config.llm.base_url or None,
-                    "max_tokens": self._config.llm.max_tokens,
-                    "timeout_seconds": self._config.llm.timeout_seconds,
+                    "api_key": self._effective_llm_config["api_key"],
+                    "base_url": self._effective_llm_config["base_url"],
+                    "max_tokens": self._effective_llm_config["max_tokens"],
+                    "timeout_seconds": self._effective_llm_config["timeout_seconds"],
                 })
```

同时在 `run_chat_async` 前端的 model-switch body 参数处理中，更新 `_effective_llm_config`：

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
         _pending = self._runtime.pop_pending_model(session_id)
         if _pending:
             _model, _provider = _pending
+            # Update effective config if the frontend sent explicit overrides
+            if hasattr(self, '_effective_llm_config'):
+                if _provider:
+                    self._effective_llm_config["provider"] = _provider
+                # Note: base_url is NOT updated here; it is preserved from init.
+                # Dynamic base_url changes require a separate API endpoint.
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-C1-1 | CLI `--base-url=http://custom` → chat → 切换模型 → 检查 backend base_url | 两次 LLM 调用均使用 `http://custom` |
| T-C1-2 | CLI `--api-key=sk-custom` → chat → 切换模型 → 检查 backend api_key | 两次 LLM 调用均使用 `sk-custom` |
| T-C1-3 | 不传 CLI override → chat → 切换模型 → base_url 回退到 config yaml 值 | config yaml 值（预期行为：无 CLI override 时回退到 config） |

---

## C2: P0-11 — API client AbortController

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [web/src/api/client.ts:10-19](web/src/api/client.ts#L10-L19) |
| **函数** | `request<T>()` |
| **严重度** | 🔴 P0 — 全部飞行请求在导航/切换时泄露 |

### 2. 现状代码

```typescript
// web/src/api/client.ts:10-19 (当前)
export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...(body ? {} : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  ...
}
```

### 4. 理论来源

> **引用**: [MDN AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController) — "The AbortController interface represents a controller object that allows you to abort one or more Web requests as and when desired."

### 5. 精确修改方案

```typescript
// web/src/api/client.ts
export async function request<T>(
  method: string,
  url: string,
  body?: unknown,
  signal?: AbortSignal,       // ← new param
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...(body ? {} : {}) },
    body: body ? JSON.stringify(body) : undefined,
    signal,                    // ← pass through
  });
```

每个 hook `useEffect` cleanup 中创建 `AbortController` 并传入 `signal`。

### 6. 测试方案

手动验证：快速切换 3 个不同 session tab → 检查 Network 面板中前 2 个 session 的请求显示 `(canceled)`。

---

## C3: P0-12 — dangerouslySetInnerHTML XSS 修复

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [web/src/components/MessageBubble.tsx:80-83](web/src/components/MessageBubble.tsx#L80-L83) + [MemoryView.tsx:391-394](web/src/components/MemoryView.tsx#L391-L394) |
| **严重度** | 🔴 P0 — 聊天 UI 渲染 LLM 输出使用 raw HTML |

### 5. 精确修改方案

将 `dangerouslySetInnerHTML` 替换为安全 markdown→JSX 渲染器。统一使用 `web/src/utils/markdown.ts`：

```typescript
// web/src/utils/markdown.ts (新增文件)
const ESCAPE_MAP: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
function escapeHtml(s: string): string { return s.replace(/[&<>"]/g, (c) => ESCAPE_MAP[c] || c); }

export function renderMarkdown(text: string): { __html: string } | null {
  if (!text) return null;
  let html = escapeHtml(text);              // Step 1: escape ALL HTML
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');  // bold
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');              // italic
  html = html.replace(/`(.+?)`/g, '<code>$1</code>');            // inline code
  html = html.replace(/\n/g, '<br/>');                            // newlines
  return { __html: html };  // NOTE: still uses dangerouslySetInnerHTML,
}                            // but ALL user content is escaped first
```

然后在两个组件中将自定义 `renderMarkdown` 调用替换为此统一实现。

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-C3-1 | Chat 输入 `<img src=x onerror=alert(1)>` | 渲染为文本 `<img src=x onerror=alert(1)>`（非 HTML）；alert 不执行 |
| T-C3-2 | Chat 输入正常 markdown `**bold** *italic*` | 渲染为 `<strong>bold</strong> <em>italic</em>` |

---

## C4: P1-29 — LLM 重试 jitter

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [llm/invoker.py:76-132](llm/invoker.py#L76-L132) |
| **函数** | `LLMInvoker.invoke()` 重试循环 |
| **严重度** | 🟠 P1 — 多 session 部署下雷群效应 |

### 5. 精确修改方案

```diff
--- a/llm/invoker.py
+++ b/llm/invoker.py
@@ ... @@
 from __future__ import annotations

+import random
 import time
 from dataclasses import dataclass
@@ ... @@ class LLMInvoker:
             except self._retryable_error as e:
                 if attempt >= self._max_retries:
                     raise
-            time.sleep(self._delay * (2 ** (attempt - 1)))
+            base_delay = self._delay * (2 ** (attempt - 1))
+            jitter = random.uniform(0, base_delay * 0.3)
+            time.sleep(base_delay + jitter)
```

---

## C5: P2 代码卫生 — SessionRuntime.dispose() + logger import 修复

> **特殊说明**: C5 是代码卫生项。在 C0-C4 主线回归全绿后，可独立提交（`refactor:` 前缀）。不阻塞安全修复主流程。

### C5-1: SessionRuntime.dispose() — 集中资源清理

```diff
--- a/agent/session/runtime.py
+++ b/agent/session/runtime.py
@@ ... @@ class SessionRuntime:
         # Mark MCP tools as UNAVAILABLE if the bridge failed to connect
         self._sync_mcp_capabilities()

+    def dispose(self) -> None:
+        """Release all mutable state. Called by AgentService.shutdown().
+
+        Idempotent — safe to call multiple times.
+        """
+        with self._active_sessions_lock:
+            self._active_sessions.clear()
+            self._backend_store.clear()
+        self._approval_brokers.clear()
+        self._web_confirm_callbacks.clear()
+        self._stream_callbacks.clear()
+        self._cancellation_tokens.clear()
```

更新 `AgentService.shutdown()` 调用 `dispose()`：

```diff
--- a/server/services/agent_service.py
+++ b/server/services/agent_service.py
@@ ... @@ class AgentService:
-        if self._runtime is not None:
-            self._runtime._backend_store.clear()
+        if self._runtime is not None:
+            self._runtime.dispose()
```

### C5-2: core/base.py logger import

```diff
--- a/core/base.py
+++ b/core/base.py
@@ ... @@
 import copy
+import logging
 import time
 from abc import ABC, abstractmethod
 from dataclasses import field, dataclass
 from enum import Enum
 from typing import Any, Protocol, runtime_checkable

+logger = logging.getLogger(__name__)
```

### C5-3: entry/chat.py logger import

类似 diff——在文件顶部添加 `import logging` + `logger = logging.getLogger(__name__)`。

### 验证标准

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-C5-1 | `rt.dispose()` → `rt._backend_store` | 空 dict |
| T-C5-2 | `rt.dispose()` 两次 | 幂等，无异常 |
| T-C5-3 | `AgentService.shutdown()` → `rt.dispose()` 被调用 | `_backend_store` 清空，无异步残留 |
| T-C5-4 | `core/base.py` import logging 后回归 | `pytest tests/` 全部通过 |

---

## 批次 B 反思采纳清单

| # | 批次 B 反思建议 | 映射到批次 C | 采纳方式 |
|---|---------------|------------|---------|
| 1 | Bash 读取场景 allowed_read_paths 检查 | **C0** | 与 tee/dd 提取绑定，与 B1 形成读写对称防御 |
| 2 | `_extract_shell_file_targets` 增强 (tee/dd) | **C0 同 Diff** | 同一修改单元，同一测试集 |
| 3 | SessionRuntime.dispose() 代码卫生 | **C5-1** | 独立提交 (`refactor:`)，不阻塞安全修复 |
| 4 | logger import 全局扫描 → 2 风险文件 | **C5-2/3** | `core/base.py` (HIGH), `entry/chat.py` (MEDIUM) |
| 5 | P2-B1-enhance (路径提取增强) 绑定 C0 | **C0 包含** | tee/dd 提取与 C0 同一 Diff |

---

## 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **关联 Phase 2 TODO 编号** | P0-3, P0-11, P0-12, P1-29, P0-4 + C0(P1增强) + C5(P2代码卫生) |
| **依赖批次** | 批次 A (commit `d841fba`) + 批次 B (commit `662451a`) |
| **附录 B 风险文件数** | 2 (`core/base.py` HIGH, `entry/chat.py` MEDIUM) |
| **C5 特殊说明** | C5 可独立提交 (`refactor:`), 不阻塞安全修复主线 |
| **理论来源** | OWASP CWE-22 + CWE-73, Saltzer & Schroeder Complete Mediation, MDN AbortController, OWASP XSS Prevention Cheat Sheet |
| **下一阶段** | 批次 C 执行 → 批次 C 反思 → 批次 D 规划（剩余 P1/P2 项） |
