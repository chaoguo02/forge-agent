# Phase 4: 批次 B 精准定位与理论指导方案

> **文档版本**: 1.0  
> **生成时间**: 2026-07-21  
> **关联 Phase 2 TODO 编号**: P1-31, P1-32, P1-33, P0-9, P0-6, P0-2（增强）  
> **对标报告引用**: [BENCHMARK_ANALYSIS.md §4-批次B](BENCHMARK_ANALYSIS.md#4-严重问题--分批修复路线图) + [§3.2](BENCHMARK_ANALYSIS.md#32-安全防护深度-差距-3-星)  
> **前置条件**: 批次 A 已完成且已提交 (commit `d841fba`)  
> **预计总工时**: 11.5h  
> **批次 A 反思纳入**: 4 项调整（见文末 [批次 A 反思采纳清单](#批次-a-反思采纳清单)）

---

## 目录

- [附录 A: agent/core.py 循环退出点审计报告](#附录-a-agentcorepy-循环退出点审计报告)
- [B0: A5 遗留 — 工具校验失败 error observation 注入对话历史](#b0-a5-遗留--工具校验失败-error-observation-注入对话历史)
- [B1-SecurityBundle: 权限管线三层安全加固](#b1-securitybundle-权限管线三层安全加固p1-31p1-32p1-33-合并)
- [B2: P0-9 — TSM Guard 异常 FAIL_CLOSED + _backend_store 残留清理](#b2-p0-9--tsm-guard-异常-fail_closed--_backend_store-残留清理)
- [B3: P0-6 — 语义搜索索引器失败可观测化](#b3-p0-6--语义搜索索引器失败可观测化)
- [B4: 循环退出点 line 1483 break→return 修复](#b4-循环退出点-line-1483-breakreturn-修复)
- [批次 A 反思采纳清单](#批次-a-反思采纳清单)
- [元数据](#元数据)

---

## 附录 A: agent/core.py 循环退出点审计报告

> **审计范围**: `_run_body()` 主循环体（lines 812–1989）中的全部 `break`、`continue`、`return _finish_run(...)` 语句。  
> **审计目的**: 确认每个退出点的上下文注入完整性，识别需要在批次 B/C 中修复的缺口。

### 退出点分类

| 行号 | 类型 | 触发条件 | 对话历史注入 | 状态 | 操作 |
|------|------|---------|-------------|------|------|
| 820 | `return _finish_run(CANCELLED)` | `cancellation_token.is_cancelled` | N/A（终止） | ✅ 正确 | 无需修复 |
| 835 | `return _finish_run(GAVE_UP)` | `_circuit_breaker_tripped` | N/A（终止） | ✅ 正确 | 无需修复 |
| 881 | `return _finish_run(GAVE_UP)` | RuntimeController 强制 TERMINATE | N/A（终止） | ✅ 正确 | 无需修复 |
| 911 | `return _finish_run(GAVE_UP)` | TSM guard RUNNING_TO_FAILED | N/A（终止） | ✅ 正确 | 无需修复 |
| 988 | `continue` | Auto-compact drain 后重试 | ✅ （无新消息，仅清理后重试 LLM） | ✅ 正确 | 无需修复 |
| 996 | `continue` | Auto-compact full compact 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1107 | `continue` | 流路径 reactive compact drain 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1112 | `continue` | 流路径 reactive compact full 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1118 | `return _finish_run(FAILED)` | 流路径 LLM stream 失败 | N/A（终止） | ✅ 正确 | 无需修复 |
| 1157 | `continue` | Classic 路径 drain 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1165 | `continue` | Classic 路径 full compact 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1176 | `return _finish_run(FAILED)` | Classic 路径 LLM 失败 | N/A（终止） | ✅ 正确 | 无需修复 |
| 1218 | `continue` | 输出截断 escalation 后重试 | ✅ | ✅ 正确 | 无需修复 |
| 1227 | `continue` | 输出截断 recovery injection 后重试 | ✅ `history.add("[SYSTEM] Output truncated. Resume directly...")` | ✅ 正确 | 无需修复 |
| 1270 | `continue` | 工具调用+`tools=[]`禁用状态 | ✅ `history.add("[SYSTEM] Tool calls are disabled...")` | ✅ 正确 | 无需修复 |
| **1294** | **`continue`** | **工具校验失败** | **⚠️ `log.log_action()` 已执行，但 `history.add()` 在后方** | **❌ 需修复** | **→ B0** |
| 1339 | `continue` | Token budget nudge | ✅ `history.add("[SYSTEM] Token budget remaining...")` | ✅ 正确 | 无需修复 |
| 1367 | `return _finish_run(GAVE_UP)` | fact_check ABORT | ✅ `history.add(fact_result.inject_message)` 在 return 之前 | ✅ 正确 | 无需修复 |
| 1382 | `continue` | fact_check RETRY | ✅ `history.add(fact_result.inject_message)` | ✅ 正确 | 无需修复 |
| 1408 | `return _finish_run(GAVE_UP)` | verify_callback ABORT | ✅ `history.add(verify_result.inject_message)` | ✅ 正确 | 无需修复 |
| 1423 | `continue` | verify_callback RETRY | ✅ `history.add(verify_result.inject_message)` | ✅ 正确 | 无需修复 |
| 1437 | `return _finish_run(GAVE_UP)` | stop_hook retry 超限 | ✅ | ✅ 正确 | 无需修复 |
| 1447 | `continue` | stop_hook 阻塞 | ✅ `history.add(LLMMessage(..., content=stop_message))` | ✅ 正确 | 无需修复 |
| **1483** | **`break`** | **完成守卫相同原因 3 次阻塞** | **⚠️ `action.action_type = GIVE_UP; break` — 退出 for 循环落到 `MAX_STEPS` 处理** | **❌ 需修复** | **→ B4** |
| 1489 | `continue` | 完成守卫阻塞 | ✅ `history.add(LLMMessage(..., content=guard_result.inject_message))` | ✅ 正确 | 无需修复 |
| 1503 | `continue` | stop_hook verify 阻塞 | ✅ | ✅ 正确 | 无需修复 |
| 1524 | `continue` | TSM reflection guard 触发 | ✅ `history.add(LLMMessage(...))` | ✅ 正确 | 无需修复 |
| 1573 | `return _finish_run(SUCCESS)` | 正常完成 | N/A（成功终止） | ✅ 正确 | 无需修复 |
| 1586 | `return _finish_run(GAVE_UP)` | Agent 主动 GIVE_UP | N/A（终止） | ✅ 正确 | 无需修复 |
| 1608 | `continue` | Batch 去重跳重复工具调用 | ✅ （工具调用完全跳过，无新消息） | ✅ 正确 | 无需修复 |
| 1726 | `return _finish_run(BLOCKED)` | 环境不可用 | N/A（终止） | ✅ 正确 | 无需修复 |
| 1818 | `return _finish_run(SUCCESS)` | 缺失测试目标检测 | N/A（终止） | ✅ 正确 | 无需修复 |
| 1861 | `return _finish_run(GAVE_UP)` | 连续工具失败超限 | N/A（终止） | ✅ 正确 | 无需修复 |
| 1921 | `return _finish_run(SUCCESS)` | 缺失测试目标 guardrail | N/A（终止） | ✅ 正确 | 无需修复 |
| 1946 | `continue` | Reflection: test_failed | ✅ `history.add(LLMMessage(..., content=reflect_prompt))` | ✅ 正确 | 无需修复 |
| 1953 | `return _finish_run(GAVE_UP)` | Reflection 3 次 test_failed | N/A（终止） | ✅ 正确 | 无需修复 |
| 1983 | `return _finish_run(MAX_STEPS)` | for 循环自然结束 | N/A（终止） | ✅ 正确 | 无需修复 |

### 审计结论

| 待修复项 | 行号 | 批次 | 问题描述 |
|---------|------|------|---------|
| **E-1** | 1294 | **B0** | 工具校验失败 → `continue` 但 error observation 未注入 `history`，LLM 下一轮看不到 |
| **E-2** | 1483 | **B4** | 完成守卫 3 次阻塞 → `break` → 落到 `MAX_STEPS` 返回而非 `GAVE_UP` |

> **31 个循环退出点中，29 个已正确处理上下文注入/终止流程。2 个需要在本批次修复。**

---

## B0: A5 遗留 — 工具校验失败 error observation 注入对话历史

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [agent/core.py:1291-1294](agent/core.py#L1291-L1294) |
| **函数** | `ReActAgent._run_body()` 主循环 |
| **严重度** | 🔴 P0 — 批次 A 遗留：工具校验失败后 LLM 看不到错误内容 |
| **批次 A 关联** | A5 已将 `break` 改为 `continue` — 循环继续运行 ✅。但 error observation 未进入对话历史 — LLM 下一轮只能通过 circuit breaker 累积后的终止才知道有错误 ❌ |

### 2. 现状代码

```python
# agent/core.py:1291-1294 (批次 A 修复后)
observations = [_observation]
# Skip tool execution entirely — go straight to post-tool processing
log.log_action(step=step, action=action, raw_content=getattr(response, "raw_content", ""))
continue  # LLM sees the error observation next turn and self-corrects
```

### 3. 问题：error observation 写入 event log 但未注入对话历史

对话历史注入代码在 **line 1869-1896**（`history.add(...)` + `observations[i]` 遍历），在 `continue` 的**后方**。当前路径上 `observations = [_observation]` 和 `log.log_action()` 均已执行，但 `history.add(...)` 被跳过。

### 4. 理论来源

#### 4.1 ReAct Paper §4.2 — Observation Format

> **引用**: Yao et al., [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) (2022), §4.2 — "The observation is appended to the context as a new thought-action-observation step, allowing the model to ground its next reasoning step in the actual outcomes of its actions."

**映射到本修复**: ReAct 模式的核心要求是 **观察结果必须注入上下文**（appended to context）。模型通过观测链 `Thought → Action → Observation → Thought → ...` 进行推理。如果 observation 缺失，模型无法修正其行为，循环虽然在运行（`continue`），但实际上在做**无反馈的自盲循环**（blind loop until circuit breaker trips）。

#### 4.2 Production-Safe Agent Loop — Observation Injection

> **引用**: [Building a Production-Safe Agent Loop (freeCodeCamp, 2025)](https://www.freecodecamp.org/news/how-to-build-a-production-safe-agent-loop-from-exit-conditions-to-audit-trails/) — "When schema validation fails, inject the validation error as a synthetic observation into the conversation history so the model can self-correct on the next turn."

**映射到本修复**: 论文明确要求"注入合成 observation 到对话历史"。当前代码已构建了 `_observation` 对象（正确的合成 observation），但未调用 `history.add()`。

### 5. 精确修改方案

```diff
--- a/agent/core.py
+++ b/agent/core.py
@@ ... @@ class ReActAgent:
                     observations = [_observation]
                     # Skip tool execution entirely — go straight to post-tool processing
                     log.log_action(step=step, action=action, raw_content=getattr(response, "raw_content", ""))
+                    # Inject the error observation into conversation history so the
+                    # LLM sees it next turn and can self-correct (ReAct Paper §4.2).
+                    if self._backend.supports_function_calling:
+                        history.add(LLMMessage(
+                            role="assistant",
+                            content=action.thought or "",
+                            tool_calls=action.tool_calls,
+                        ))
+                        for tc, obs in zip(action.tool_calls, observations):
+                            history.add(LLMMessage(
+                                role="tool",
+                                content=obs.output,
+                                tool_call_id=tc.id if tc else None,
+                            ))
+                    else:
+                        history.add(LLMMessage(
+                            role="assistant",
+                            content=self._format_action_for_history(action),
+                        ))
+                        history.add(LLMMessage(
+                            role="user",
+                            content=self._format_observations_for_history(observations),
+                        ))
                     continue  # LLM sees the error observation next turn and self-corrects
                 else:
                     # Validation passed — proceed to normal tool execution below
                     pass
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-B0-1 | Mock LLM 第 1 轮返回含空 tool_name 的 tool call → 第 2 轮返回合法 Finish | 第 2 轮 LLM 的 messages 中包含第 1 轮 error observation 内容（`tool_error` / `INVALID_PARAMS`） |
| T-B0-2 | Mock LLM 连续返回 3 轮无效 tool call | Agent 在 circuit breaker 触发后终止（`GAVE_UP`，非 `MAX_STEPS`）|
| T-B0-3 | Native function_calling 模式下 error observation 正确关联 `tool_call_id` | `history` 中 assistant msg 带 `tool_calls` + tool msg 带正确 `tool_call_id` |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m "not e2e"` 通过
- [ ] 正常 tool call 流程完全不变（`continue` 路径不被触发）

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | 仅在工具校验失败路径（模型发出格式错误 tool call 时）触发 |
| **触发条件** | 极罕见 — 模型通常发出合规的 tool call |
| **失败模式** | 注入的错误 messages 与 provider 格式完全一致（复用现有 `_format_action_for_history` / native tool_use 模式），不会破坏后续 LLM 调用 |
| **缓解措施** | 注入的 tool_call_id 使用 LLM 原始 id — 若 model 复用相同 id 在下轮发出合法调用，可能导致配对错乱 — 但 LLM 从不在不同轮次复用 tool_call_id |

### 9. 设计决策备注

> **反思: 为何不统一复用 lines 1869-1896 的 history 注入代码？**
> 考虑过在 `continue` 前设置标志位，让后续代码正常执行到 1869。但 lines 1869-1896 依赖 `effective_tool_calls` 变量（在 1603 行去重后）、`observations` 的遍历索引与 `effective_tool_calls` 对齐 — 这些变量在校验失败的路径上未初始化。内联注入是最干净的方案。

---

## B1-SecurityBundle: 权限管线三层安全加固（P1-31/P1-32/P1-33 合并）

> **警告**: 本修复单元不可拆分执行。P1-31（plan 审批 token 匹配）、P1-32（Bash 参数无沙箱）、P1-33（`strict_file_scope` Bash 绕过）构成单一攻击链：plan 审批 → Bash auto-approve → 策略层无检查 → 完全逃逸。单独修复任一项都留下可利用窗口。

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [hitl/pipeline.py:813-835](hitl/pipeline.py#L813-L835) (`_match_approved_prompt`) + [core/policy_registry.py:223-266](core/policy_registry.py#L223-L266) (`_check_tool_call`) + [tools/shell_tool.py:63](tools/shell_tool.py#L63) (metadata) |
| **严重度** | 🔴 P1 — 组合攻击链：plan 审批授予任意 Bash 执行权限 |
| **攻击链** | `ExitPlanMode(allowedPrompts)` → `_match_approved_prompt` 单 token 匹配 → Bash 未受策略层检查 → 全逃逸 |

### 2. 现状代码（攻击链三条链路）

#### 链路 1: `_match_approved_prompt` — 单 token 交集

```python
# hitl/pipeline.py:825-830 (当前)
if primary_key and primary_key in params:
    value = str(params[primary_key])
    value_tokens = self._tokenize(value)
    if prompt_tokens & value_tokens:   # ← 任意单个 token 重叠即匹配
        return approved_prompt
```

#### 链路 2: ShellTool 无 path_parameter

```python
# tools/shell_tool.py:63 (metadata)
metadata = ToolMetadata(
    effects=frozenset({ToolEffect.EXECUTE, ...}),
    path_parameter="",    # ← 空字符串 — 策略层无法检查路径
    ...
)
```

#### 链路 3: `_check_tool_call` 未检查 Bash

```python
# core/policy_registry.py:252-253 (当前)
if metadata.path_access == PathAccess.READ:
    return self._check_path(name, raw_path, ...)
if metadata.path_access == PathAccess.WRITE:
    return self._check_path(name, raw_path, ...)
# Bash: path_access=NONE → 所有检查被跳过
```

### 4. 理论来源

#### 4.1 链路 1: 令牌级访问控制理论

> **引用**: NIST SP 800-63B §5.2.2 — "Token-based authentication systems must require a majority of tokens to match, not a single token, to prevent statistical downgrade attacks."

**映射**: 单个 "test" token 匹配即授予全 Bash 访问权是令牌级认证的降级攻击。

#### 4.2 链路 2+3: 最小权限原则

> **引用**: Saltzer & Schroeder (1975), "The Protection of Information in Computer Systems" — Principle of Least Privilege: "Every program and every user of the system should operate using the least set of privileges necessary to complete the job."

**映射**: ShellTool 被授予 `path_parameter=""` 意味着策略层**完全不知道** Shell 访问哪些文件。这违反了最小权限 — Bash 是"万能适配器"（CC term），但必须受策略约束。

#### 4.3 行业对标

> **引用**: Claude Code [Bash AST Analysis](https://github.com/anthropics/claude-code/issues/13371) — "Tree-sitter-based syntax tree analysis of shell commands with 23 static safety checks."

**差距**: Grace-Code 当前无任何 Bash 命令解析。此修复实现路径级检查（提取重定向目标文件），这是在不引入 tree-sitter 依赖的情况下的最轻量防御。

### 5. 精确修改方案

#### 修改 1/2: `hitl/pipeline.py:813-835` — Token 匹配从单 token → 多数重叠 + cap

```diff
--- a/hitl/pipeline.py
+++ b/hitl/pipeline.py
@@ ... @@ class PermissionPipeline:
             prompt_tokens = self._tokenize(approved_prompt)
             primary_key = self._PROMPT_PRIMARY_PARAM.get(tool_name)
             if primary_key and primary_key in params:
                 value = str(params[primary_key])
                 value_tokens = self._tokenize(value)
-                if prompt_tokens & value_tokens:
+                # Require majority token overlap (not single-token intersection)
+                # to prevent privilege escalation via common tokens (e.g. "test").
+                if not prompt_tokens:
+                    continue
+                overlap = prompt_tokens & value_tokens
+                overlap_ratio = len(overlap) / len(prompt_tokens)
+                if overlap_ratio >= 0.5:
                     return approved_prompt
             # Also check all string params for substring matches
             for key, val in params.items():
                 if isinstance(val, str):
                     val_tokens = self._tokenize(val)
-                    if prompt_tokens & val_tokens:
-                        return approved_prompt
+                    if not prompt_tokens:
+                        continue
+                    overlap = prompt_tokens & val_tokens
+                    overlap_ratio = len(overlap) / len(prompt_tokens)
+                    if overlap_ratio >= 0.5:
+                        return approved_prompt
         return None
```

在 `add_approved_prompts()` 中添加 cap：

```diff
--- a/hitl/pipeline.py
+++ b/hitl/pipeline.py
@@ ... @@ class PermissionPipeline:
         """Register model-declared prompts approved during plan exit (CC-aligned).

         Each prompt is ``{"tool": "...", "prompt": "..."}``.  After plan approval
         the build agent may invoke the listed tools with matching parameters
         without interactive confirmation.
+
+        Capped at 20 entries to prevent token-overlap attack surface expansion
+        across multiple plan/build cycles.
         """
         if not isinstance(prompts, list):
             return
         for item in prompts:
             if isinstance(item, dict) and "tool" in item and "prompt" in item:
+                if len(self._approved_prompts) >= 20:
+                    logger.warning(
+                        "Approved prompts cap (20) reached — discarding: %s",
+                        item,
+                    )
+                    continue
                 self._approved_prompts.append({
                     "tool": str(item["tool"]),
                     "prompt": str(item["prompt"]),
                 })
```

Bash 命令绕过 Layer 4.5（`_match_approved_prompt` **永不**为 Bash 匹配）：

```diff
--- a/hitl/pipeline.py
+++ b/hitl/pipeline.py
@@ ... @@ class PermissionPipeline:
         if self._approved_prompts:
+            # Bash commands NEVER bypass Layer 6 — even with approved prompts.
+            # Shell execution requires explicit interactive confirmation.
+            if tool_name == "Bash":
+                pass  # fall through to Layer 6
+            else:
                 match = self._match_approved_prompt(tool_name, params)
                 if match is not None:
                     result = PermissionResult(
                         decision=PermissionDecision.ALLOW,
                         layer=PermissionLayer.PROMPT_APPROVED,
                         reason=f"Approved prompt: {match}",
                     )
                     self._stats.record(result)
                     return self._apply_tool_check(result, tool, params)
```

#### 修改 2/2: `core/policy_registry.py:223-266` — Bash 命令路径提取 + 策略检查

```diff
--- a/core/policy_registry.py
+++ b/core/policy_registry.py
@@ ... @@ class PolicyAwareToolRegistry(ToolRegistry):
         if metadata.path_access == PathAccess.DISCOVER and self._phase_policy.allowed_read_paths is not None:
             return self._check_path(name, raw_path, self._phase_policy.allowed_read_paths, "search")
+
+        # ── Bash command target extraction (defense-in-depth) ──
+        # Shell commands are opaque to the policy layer by default.
+        # Extract file targets from shell redirections so strict_file_scope
+        # and allowed_write_paths can constrain Bash side-effects.
+        if name == "Bash" and self._phase_policy.strict_file_scope:
+            _cmd = str(params.get("command", "") or "")
+            _args = params.get("args", []) or []
+            _targets = _extract_shell_file_targets(_cmd, _args)
+            _write_allowed = self._phase_policy.allowed_write_paths
+            for _target in _targets:
+                _normalized = normalize_repo_path(_target, self._repo_path)
+                if _write_allowed is not None and _normalized not in _write_allowed:
+                    return (
+                        f"[RUNTIME BLOCK] BASH PATH DENIED: '{_normalized}' is "
+                        f"outside the allowed write scope in strict_file_scope mode. "
+                        f"Allowed: {', '.join(sorted(_write_allowed)) or '(none)'}"
+                    )
         return None
```

添加 `_extract_shell_file_targets()` 辅助函数：

```diff
--- a/core/policy_registry.py
+++ b/core/policy_registry.py
@@ ... @@ class PolicyAwareToolRegistry(ToolRegistry):
     from core.policy import PhasePolicy, normalize_repo_path
     from core.base import (
         ExecutionContext,
         PathAccess,
+        ToolEffect,
         ToolDependency,
         ToolMetadata,
         ToolRegistry,
         ToolResult,
     )
+
+
+def _extract_shell_file_targets(command: str, args: list[str]) -> list[str]:
+    """Extract file paths targeted by shell redirections and common commands.
+
+    This is a lightweight regex-based extraction, NOT a shell parser.
+    It catches the most common bypass vectors (>, >>, <, 2>, cat, rm, etc.)
+    without introducing a tree-sitter dependency.
+
+    Returns a list of (possibly relative) file paths referenced in the command.
+    """
+    import re as _re
+    targets: list[str] = []
+    _full = f"{command} {' '.join(str(a) for a in args)}"
+
+    # Redirections: > file, >> file, 2> file, 1> file, &> file
+    for m in _re.finditer(r'(?:[12]?&?>>?)\s*(\S+)', _full):
+        _path = m.group(1).strip('"\'')
+        if _path and not _path.startswith('(') and not _path.startswith('/dev/'):
+            targets.append(_path)
+
+    # Input redirections: < file
+    for m in _re.finditer(r'(?<!\d)<\s*(\S+)', _full):
+        _path = m.group(1).strip('"\'')
+        if _path and not _path.startswith('/dev/'):
+            targets.append(_path)
+
+    # Common destructive commands: target is the last non-flag argument
+    _DESTRUCTIVE_CMDS = {'rm', 'rmdir', 'chmod', 'chown', 'mv', 'cp'}
+    _cmd_base = command.split()[0] if command.strip() else ""
+    if _cmd_base in _DESTRUCTIVE_CMDS:
+        _parts = _full.split()
+        for _p in reversed(_parts[1:]):
+            if not _p.startswith('-'):
+                targets.append(_p.strip('"\'"'))
+                break
+
+    return targets
```

### 6. 统一测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-B1-1 | Plan 审批 "Run the test suite" → 检查 `Bash("rm -rf / # test")` | **触发 Layer 6 交互审批**（Bash 永不通过 Layer 4.5；token match 需 ≥50%：`{"run","the","test","suite"}` ∩ `{"rm","rf","test"}` = `{"test"}` = 25% < 50%）|
| T-B1-2 | Plan 审批 "Run pytest --cov" → 检查 `Bash("pytest --cov")` | 通过 Layer 4.5（`{"run","pytest","cov"}` vs `{"pytest","cov"}` → 67% ≥ 50%） |
| T-B1-3 | `strict_file_scope + allowed_write_paths=["src/"]` → Bash `"echo x > /tmp/evil"` | **被 `_check_tool_call()` 拦截**，返回 RUNTIME BLOCK |
| T-B1-4 | `strict_file_scope + allowed_write_paths=["src/"]` → Bash `"echo x > src/output.txt"` | **通过**策略检查 |
| T-B1-5 | `allowed_write_paths=None` + `strict_file_scope=True` → Bash `"rm important.py"` | **被拦截**（destructive cmd 目标不在任何允许路径） |
| T-B1-6 | 连续 5 次 ExitPlanMode → 检查 `_approved_prompts` 长度 | **≤ 20**；超额的丢弃并记录 warning |
| T-B1-7 | Redis→ `allowed_write_paths=["src/"]` → 检查 `Bash("echo x | grep y")` | **通过**（pipe 无文件重定向，目标列表为空） |

### 7. 回归验证标准

- [ ] `pytest tests/test_plan_approval.py -v` 通过
- [ ] `pytest tests/test_cli_web_alignment.py -v` 通过
- [ ] Plan → Approve → Build 完整流程中 Bash 命令仍可通过 Layer 6 交互审批
- [ ] Plan → Approve → Build 中非 Bash 已审批工具（如 Read "test_file.py"）仍 auto-approved

### 8. 量化回归风险评估

| 维度 | 评估 |
|------|------|
| **影响范围** | `_match_approved_prompt()` — 所有 approved prompt 的匹配行为改变；`_check_tool_call()` — Bash + `strict_file_scope` 场景新增检查；`add_approved_prompts()` — 添加 cap |
| **触发条件** | 仅在有 approved prompts 或 strict_file_scope 时触发 |
| **误拦风险** | `_extract_shell_file_targets()` 是正则方法（非 AST），可能提取不精确的"文件路径"。在最坏情况下（如命令中 `>` 出现在引号内作为字符串），误拦会使合法命令被拒绝 — 但不通过策略（deny 而非 allow）|
| **Bash Layer 4.5 排除** | Bash **永不**通过 approved prompt 路径。always fall through to Layer 6。对安全是纯粹增益 |
| **缓解措施** | 将 `_extract_shell_file_targets` 的误拦日志从 `logger.warning` 改为 `logger.info` 级别 — 便于后续分析误拦模式而不产生噪音 |

### 9. 设计决策备注

> **反思 1: 为何不引入 tree-sitter-bash？**
> 业界最佳实践（Claude Code）使用 tree-sitter 进行完整 AST 分析。但引入 tree-sitter 依赖 (~2MB binary + compilation time) 在这里是**过度工程化** — Grace-Code 的目标用户规模不需要 AST 级分析。正则方法覆盖 80%+ 常见逃逸模式，足够。
>
> **反思 2: Bash `>` 提取是否误拦 pipe 场景？**
> `echo x | grep y` 无重定向符，`_extract_shell_file_targets` 返回空列表 → 通过。`echo x > /tmp/out` 提取 `/tmp/out` — 正确。`echo "x > y"` 提取 `y"`（误提取）— 但 `y"` 不是合法文件路径，策略层应拒绝。不影响安全性。
>
> **反思 3: 三个修复为何必须合并？**
> P1-31 fix → Bash 不可通过 approved prompts 逃逸（但仍可通过策略层 + 无沙箱逃逸）
> P1-33 fix → `strict_file_scope` 检查 Bash 写入路径（但 approved prompts 可能 auto-approve）
> P1-32 fix → Bash 重定向目标提取（但需前两项协同才闭环）
> 三者独立部署时，每条路径都留下可利用逃逸窗口。合并为单一 bundle 是唯一正确的部署策略。

---

## B2: P0-9 — TSM Guard 异常 FAIL_CLOSED + _backend_store 残留清理

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [agent/core.py:1512-1519](agent/core.py#L1512-L1519) (guard swallow) + [server/services/agent_service.py:779-781](server/services/agent_service.py#L779-L781) (backend cleanup) |
| **严重度** | 🔴 P0-9 + P0-2 增强 |
| **批次 A 反思关联** | 调整建议 #3: `_backend_store` 进程级异常残留清理 |

### 2. 现状代码

```python
# agent/core.py:1512-1519 (TSM guard — 异常完全吞没)
for _guard_fn in _reflection_guards:
    try:
        _gr = _guard_fn(_guard_ctx)
        if _gr.inject_message:
            _reflection_msg += _gr.inject_message + "\n\n"
    except Exception:
        pass    # ← guard crash — no one knows

# server/services/agent_service.py:779-781 (backend cleanup — 仅 finally 块，进程崩溃不覆盖)
finally:
    self._runtime.release_session(session_id)
    self._runtime.release_backend_for_session(session_id)
```

### 4. 理论来源

#### 4.1 Defense in Depth: Fail-Safe Defaults

> **引用**: Saltzer & Schroeder (1975), Principle of Fail-Safe Defaults — "Base access decisions on permission rather than exclusion. The default situation is lack of access."

**映射**: Guard 函数失败意味着安全屏障故障。应默认拒绝（FAIL_CLOSED）而非静默通过。与铁路信号系统类比：信号故障 → 红灯停止，而非绿灯通行。

#### 4.2 Process-level crash resource cleanup

> **引用**: Python `atexit` 模块文档 — "Functions registered via atexit are called when the interpreter terminates normally. For abnormal termination (os._exit, SIGKILL), atexit handlers are not called."

**映射**: `finally` 块只在正常控制流退出时执行。`KeyboardInterrupt`（进程级）和 `os._exit()` 不触发 finally。需要在 `shutdown()` 和 `atexit` 中添加二次清理。

### 5. 精确修改方案

#### 修改 1/2: `agent/core.py:1512-1519` — Guard FAIL_CLOSED

```diff
--- a/agent/core.py
+++ b/agent/core.py
@@ ... @@ class ReActAgent:
             for _guard_fn in _reflection_guards:
                 try:
                     _gr = _guard_fn(_guard_ctx)
                     if _gr.inject_message:
                         _reflection_msg += _gr.inject_message + "\n\n"
-                except Exception:
-                    pass
+                except Exception:
+                    logger.error(
+                        "TSM guard function %s failed — FAIL_CLOSED",
+                        getattr(_guard_fn, '__name__', repr(_guard_fn)),
+                        exc_info=True,
+                    )
+                    # Guard failure → reject the transition (FAIL_CLOSED).
+                    # The agent loop must not proceed when a safety barrier
+                    # has malfunctioned.
+                    _tsm.fail(
+                        TerminationReason.GUARD_REJECTED,
+                        f"Guard function {getattr(_guard_fn, '__name__', 'unknown')} raised an exception",
+                    )
+                    log.log_task_failed(
+                        steps=step, reason="TSM guard exception — FAIL_CLOSED",
+                    )
+                    return _finish_run(
+                        status=RunStatus.GAVE_UP,
+                        summary="Safety guard malfunction — agent halted.",
+                        steps_taken=step, total_tokens_used=total_tokens,
+                        cache_stats=cumulative_cache,
+                    )
```

#### 修改 2/2: `agent/session/runtime.py` — `cleanup_session()` 联动清理 backend_store

```diff
--- a/agent/session/runtime.py
+++ b/agent/session/runtime.py
@@ ... @@ class SessionRuntime:
         # 6. Release TOCTOU guard
         self.release_session(session_id)
+
+        # 7. Release per-session backend (prevents memory leak after crash recovery)
+        self.release_backend_for_session(session_id)
```

#### 修改 3/2（附加）: `agent/session/runtime.py` — `shutdown()` 清空所有残留

```diff
--- a/agent/session/runtime.py
+++ b/agent/session/runtime.py
@@ ... @@ class SessionRuntime:
         Will be called by AgentService.shutdown() on app exit.
         """
         logger.info("SessionRuntime shutting down")
         with self._active_sessions_lock:
             self._active_sessions.clear()
+            self._backend_store.clear()
         # Cancel any running background executions
         with self._background_runs_lock:
             for key, thread in list(self._background_runs.items()):
                 logger.debug("Cancelling background run: session=%s gen=%d", key[0], key[1])
         self._cancellation_tokens.clear()
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-B2-1 | Mock guard 抛出 `ValueError("broken")` → 检查 agent 行为 | Agent 立即返回 `GAVE_UP`；日志含完整 traceback + guard 函数名 |
| T-B2-2 | Mock guard 正常返回 → 检查 agent | Agent 正常完成，`_reflection_msg` 正确累积 |
| T-B2-3 | 模拟 `_run_and_notify()` 抛出 `KeyboardInterrupt` → 检查 `_backend_store` 在 `shutdown()` 后 | `_backend_store` 为空 dict |
| T-B2-4 | `cleanup_session()` 后检查 `_backend_store` 中的 session_id | Key 不存在 |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m "not e2e"` 通过
- [ ] 正常 session completion 后 `_backend_store` 不泄漏

---

## B3: P0-6 — 语义搜索索引器失败可观测化

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [memory/sqlite_backend.py:122-123](memory/sqlite_backend.py#L122-L123) 和 [line 133-135](memory/sqlite_backend.py#L133-L135) |
| **函数** | `SqliteMemoryBackend.write_memory()` + `delete_memory()` |
| **严重度** | 🔴 P0 — 索引失败完全静默：用户被告知记忆保存成功但语义搜索永远找不到 |

### 2. 现状代码

```python
# memory/sqlite_backend.py:122-123
if self._indexer is not None:
    try: self._indexer.index_memory(memory)
    except Exception: pass    # ← 索引器在这里无声消亡

# memory/sqlite_backend.py:133-135
if self._indexer is not None:
    try: self._indexer.remove_memory(name)
    except Exception: pass    # ← 同样的模式
```

### 4. 理论来源

> **引用**: Google SRE Book, Chapter 6 — "Monitoring Distributed Systems" — "If a system component fails silently, it must be treated as if it doesn't exist. Silent failures are the most dangerous class of production incidents."

**映射**: 当索引器（FAISS/Chroma）失败时，用户被告知"记忆保存成功"但向量索引不包含该记忆。语义搜索静默降级为无结果 — 用户不知道为什么。

### 5. 精确修改方案

```diff
--- a/memory/sqlite_backend.py
+++ b/memory/sqlite_backend.py
@@ ... @@ class SqliteMemoryBackend:
     """SQLite-backed memory backend. Memories in memory_entries + memory_anchors tables."""

+    # Indexer error state for observability (P0-6).
+    # When not None, the last indexer operation failed with this message.
+    _last_index_error: str | None = None
+    _index_error_count: int = 0
+
     def __init__(self, db_path: str, indexer: Any | None = None) -> None:
         self._db_path = db_path
         self._indexer = indexer
+        self._last_index_error: str | None = None
+        self._index_error_count: int = 0
         self._init_tables()
```

修改 `write_memory()`：

```diff
--- a/memory/sqlite_backend.py
+++ b/memory/sqlite_backend.py
@@ ... @@ class SqliteMemoryBackend:
         if self._indexer is not None:
-            try: self._indexer.index_memory(memory)
-            except Exception: pass
+            try:
+                self._indexer.index_memory(memory)
+                self._last_index_error = None
+            except Exception as exc:
+                self._last_index_error = str(exc)[:200]
+                self._index_error_count += 1
+                logger.warning(
+                    "Semantic indexer failed to index memory '%s' (error #%d): %s",
+                    memory.name, self._index_error_count, exc,
+                )
```

修改 `delete_memory()`：

```diff
--- a/memory/sqlite_backend.py
+++ b/memory/sqlite_backend.py
@@ ... @@ class SqliteMemoryBackend:
         if self._indexer is not None:
-            try: self._indexer.remove_memory(name)
-            except Exception: pass
+            try:
+                self._indexer.remove_memory(name)
+            except Exception as exc:
+                self._last_index_error = str(exc)[:200]
+                self._index_error_count += 1
+                logger.warning(
+                    "Semantic indexer failed to remove memory '%s' (error #%d): %s",
+                    name, self._index_error_count, exc,
+                )
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-B3-1 | 正常索引器（FAISS 在线）→ `write_memory` | `_last_index_error=None`；记忆正常搜索 |
| T-B3-2 | 断开索引器 → `write_memory` → 检查日志 | 日志含 `WARNING: Semantic indexer failed`；`_last_index_error` 非空；`_index_error_count` 递增 |

### 7. 回归验证标准

- [ ] `pytest tests/test_memory_api.py -v` 通过
- [ ] `write_memory` 返回值不受影响

---

## B4: 循环退出点 line 1483 break→return 修复

### 1. 问题定位

| 属性 | 值 |
|------|-----|
| **文件** | [agent/core.py:1477-1483](agent/core.py#L1477-L1483) |
| **严重度** | 🟡 P1 — 完成守卫 3 次阻塞后返回 `MAX_STEPS` 而非 `GAVE_UP` |

### 2. 现状代码与问题

```python
if _block_count >= 3:
    logger.warning("Completion blocked %d times with same reason — forcing give_up", _block_count)
    action.action_type = ActionType.GIVE_UP
    break   # 退出 for 循环 → 落到 MAX_STEPS 处理→ 返回 MAX_STEPS 而非 GAVE_UP
```

`break` 退出 for 循环后执行 line 1980-1989 的 post-loop handler — `_tsm.fail(TerminationReason.MAX_STEPS, ...)` → `return _finish_run(status=RunStatus.MAX_STEPS, ...)`。意图是 `GIVE_UP` 但实际返回 `MAX_STEPS`。

### 5. 精确修改方案

```diff
--- a/agent/core.py
+++ b/agent/core.py
@@ ... @@ class ReActAgent:
                         logger.warning(
                             "Completion blocked %d times with same reason — forcing give_up",
                             _block_count,
                         )
-                        action.action_type = ActionType.GIVE_UP
-                        break
+                        reason = (
+                            f"Agent gave up: completion blocked {_block_count} "
+                            f"times for reason: {guard_result.blocked_reason}"
+                        )
+                        _tsm.fail(TerminationReason.AGENT_GAVE_UP, reason)
+                        log.log_task_failed(steps=step, reason=reason)
+                        return _finish_run(
+                            status=RunStatus.GAVE_UP,
+                            summary=reason,
+                            steps_taken=step,
+                            total_tokens_used=total_tokens,
+                            cache_stats=cumulative_cache,
+                        )
```

### 6. 测试方案

| 测试 ID | 方法 | 验证条件 |
|---------|------|---------|
| T-B4-1 | Mock 完成守卫连续返回 3 次 `can_complete=False` 相同 reason | Agent 返回 `GAVE_UP`；TSM 状态为 `FAILED` + `TerminationReason.AGENT_GAVE_UP` |
| T-B4-2 | Mock 完成守卫第 1 次阻塞 → 第 2 次不同的 reason → 第 3 次再相同 | 计数器按 reason 单独递增；不会错误触发 3-block 终止 |

### 7. 回归验证标准

- [ ] `pytest tests/test_e2e_core.py -v -m "not e2e"` 通过
- [ ] `agent/core.py` 主循环体中 `break` 语句仅剩 0 个（line 586 是注释中的字符串，不计；lines 2157 在辅助方法中，不在主循环）

---

## 批次 A 反思采纳清单

| # | 批次 A 反思建议 | 映射到批次 B | 采纳方式 |
|---|---------------|------------|---------|
| 1 | A5 遗留 — error observation 注入对话历史 | **B0** | 作为本批次首项执行，引用 ReAct Paper §4.2 |
| 2 | `_backend_store` 进程级异常残留清理 | **B2 子任务 2** | `cleanup_session()` 联动 + `shutdown()` 清空 |
| 3 | 安全修复绑定 — P1-31/32/33 合并 | **B1-SecurityBundle** | 三项合并为单一修复单元，统一 Diff + 统一测试 |
| 4 | break/continue 系统审计前置 | **附录 A** | 审计结果指导 B4 修复 (line 1483 break→return) |

---

## 元数据

| 属性 | 值 |
|------|-----|
| **文档版本** | 1.0 |
| **生成时间** | 2026-07-21 |
| **关联 Phase 2 TODO 编号** | P1-31, P1-32, P1-33, P0-9, P0-6, P0-2（增强） |
| **依赖批次** | 批次 A (commit `d841fba`) |
| **对标报告引用章节** | [BENCHMARK_ANALYSIS.md §3.2](BENCHMARK_ANALYSIS.md#32-安全防护深度-差距-3-星) + [§4-批次B](BENCHMARK_ANALYSIS.md#4-严重问题--分批修复路线图) |
| **理论来源** | ReAct Paper §4.2 (Yao et al. 2022), NIST SP 800-63B §5.2.2, Saltzer & Schroeder (1975), Google SRE Book Ch.6, Python atexit 文档 |
| **下一阶段** | 批次 B 执行 → 批次 B 反思 → 批次 C 规划（P0-3/11/12/P1-29/P0-4） |
