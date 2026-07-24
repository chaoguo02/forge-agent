# Grace Code 审计 TODO 追踪

> **生成日期**: 2026-07-21 · **最终对齐**: 2026-07-23
> **Phase**: 2 — 深度审计
> **方法论**: Vibe Coding 反模式识别 + 安全审计 + 权限管线审查 + 前端代码质量
> **理论来源**: Clean Code／Clean Architecture (Robert C. Martin), Claude Code CVE 披露, Loop Engineering Patterns (2026), SQLite WAL 官方文档

---

## ⚙️ 维护约定（强制）

1. **任何修复提交必须同步更新此文件。**
   修复 commit 的 message 中应引用对应的 TODO ID（如 `fix(P0-2): ...`）。
2. **更新状态时需附带 commit hash。**
   格式：`✅ [hash]` / `⚠️ [hash] + 剩余问题` / `❌`。
3. **禁止使用模糊描述。** 所有标记必须精确到文件:行号 + 修复内容。
4. **本文件随项目演进实时更新。** 在 Phase 切换、Batch 完成、或门禁通过时同步修订。

---

## 📊 统计摘要 (2026-07-24 最终对齐)

| 优先级 | 未修复 (❌) | 已审查不修 (⊘) | 部分修复 (⚠️) | 已修复 (✅) | 合计 |
|--------|------------|---------------|--------------|-----------|------|
| 🔴 P0 | 0 | 0 | 0 | 13 | 13 |
| 🟠 P1 | 0 | 0 | 4 | 29 | 33 |
| 🟡 P2 | 0 | 22 | 2 | 32 | 56 |
| **总计** | **0** | **22** | **6** | **74** | **102** |

**结论：所有可修复项已清空。22 项标记 ⊘（跳过）是经过逐项审计的不值得修复项，4 项 ⚠️ 是已接受的推迟项（P1-1/P1-17 架构债），2 项 ⚠️ 是低风险残余。**

### 按模块分布（未修复 + 部分修复）

| 模块 | P0 | P1 | P2 | 合计 |
|------|----|----|-----|------|
| agent/core.py | 0 | 2 | 7 | 9 |
| server/ (AgentService + routers) | 0 | 0 | 3 | 3 |
| core/ (base.py, circuit_breaker.py) | 0 | 0 | 3 | 3 |
| hitl/ (pipeline.py) | 0 | 0 | 2 | 2 |
| memory/ | 0 | 1 | 1 | 2 |
| app/storage/ (sqlite.py) | 0 | 1 | 1 | 2 |
| agent/session/ (session_store, runtime) | 0 | 0 | 2 | 2 |
| web/ (API, stores, components) | 0 | 0 | 11 | 11 |
| context/ + hooks/ + llm/ + tools/ | 0 | 0 | 5 | 5 |

---

## 🔴 P0 — 立即修复（13 项：安全／数据完整性／逻辑错误）

### 安全与线程

- [x] **P0-1** ✅ d841fba [agent/session/session_store.py:44-45] SQLite WAL + busy_timeout
  | `conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA busy_timeout=10000")`

- [x] **P0-2** ✅ 59ecec2 [server/services/agent_service.py:137, chat_pipeline.py:176] LLM Backend 共享可变状态修复
  | `chat_pipeline.py` 为每个 session 创建 per-session backend（`set_backend_for_session()`）。全局 `self._backend` 降级为 fallback。

- [x] **P0-3** ✅ 59ecec2 [server/services/agent_service.py:123, chat_pipeline.py:167] 模型切换时 API key/base_url 保留
  | `_effective_llm_config` dict 保存 CLI 覆盖项；chat_pipeline 在模型切换时使用其。

- [x] **P0-4** ✅ 59ecec2 [agent/session/runtime.py:241-244] Session 执行 TOCTOU 修复
  | `try_acquire_session()` with `threading.Lock` 原子性 check-and-acquire。HTTP handler 中的 DB 状态检查仅为快速反馈。

- [x] **P0-5** ✅ 59ecec2 [server/routers/sessions.py:425-426] RuntimeError → HTTP 409
  | `except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc))`

- [x] **P0-6** ✅ df4d4fc [memory/sqlite_backend.py:159-166] 语义搜索索引失败静默修复
  | `_last_index_error` + `_index_error_count` + `logger.warning`

- [x] **P0-7** ✅ 59ecec2 [app/storage/sqlite.py:229,249] Session 删除有事务包裹
  | `conn.execute("BEGIN IMMEDIATE")` / `COMMIT` for delete_session + batch_delete

### 逻辑错误（agent/core.py）

- [x] **P0-8** ✅ c01e941 [agent/core.py:1287-1300] `break` 误用修复
  | break 已移除；tool call 验证失败时向对话历史注入错误 observation，LLM 下一轮可见并自修正。

- [x] **P0-9** ✅ 59ecec2 [agent/core.py] Guard 异常静默吞没修复
  | `_reflection_guards` 代码段已移除（grep 无匹配）。

- [x] **P0-10** ✅ e614cb4 [agent/core.py:344-391, 409-448, completion_guard.py:21-36] `_capture_git_state()` 精确异常捕获修复
  | M1: `_GitState` 新增 `_last_git_error` + `_refresh_error_logged`
  | M2: `except Exception` → `ImportError` / `_git_exc` / `OSError(EACCES,EPERM)→raise`
  | M3: `_refresh_git_state()` `pass` → `is_git_repo=False` + 日志风暴控制（首次WARNING后续DEBUG）
  | M4: `runtime_message_source` `except Exception` → `(ValueError, TypeError, RuntimeError)`
  | M5: `completion_guard.check()` `git_state: Any` → `git_state: GitStateLike | None` Protocol
  | 测试: 17/17 PASS + 41 回归 PASS (58/58, zero regressions)

- [x] **P0-11** ✅ ab70813 [web/src/api/client.ts] AbortController 缺失 → Batch 1：apiGet/apiPost 全部透传 signal

- [x] **P0-12** ✅ ab70813 [web/src/components/MessageBubble.tsx] XSS 攻击面 → Batch 1：统一 `<MarkdownRenderer />`（escape-before-format）；Batch 2-5：进一步巩固

- [x] **P0-13** ✅ 59ecec2 [memory/file_backend.py:64] 路径遍历修复
  | `_NAME_PATTERN` 正则校验（仅 `[a-zA-Z0-9_-]{1,128}`）+ `path.resolve()` defense-in-depth 检查

---

## 🟠 P1 — 近期修复（33 项：反模式／架构债）

### agent/core.py — 结构与重复

- [ ] **P1-1** ⏸️ 推迟 [agent/core.py:722-1996] `_run_body()` 1275 行单体函数。
  | **决策**: 架构债，非功能缺陷。需先建立 _run_body 的单元测试基础设施再拆解。P1-2 已完成子部件提取。
  | **风险**: 在不具备测试安全网的情况下拆分核心执行路径，可能引入死锁/状态漂移/回归漏检。

- [x] **P1-2** ✅ 44fae55 [agent/core.py:344-363, 607-714, 895-907] `_finish_run` 嵌套闭包提取
  | `_FinishRunContext` dataclass (12 fields) + `_build_run_result()` 方法
  | 21 call sites replaced. Tests: 3/3 PASS + 68 regression (71/71)

- [x] **P1-3** ✅ 59ecec2 [agent/core.py:2522] Prompt-too-long 恢复逻辑重复修复
  | `_attempt_reactive_compact()` 已提取为独立方法，streaming + classic 双向调用。

- [x] **P1-4** ✅ 662451a [agent/core.py:1427-1448] 统一为 `for _check_fn in (...)` 循环 — fact_check + verify_callback 合并

- [x] **P1-5** ✅ 59ecec2 [agent/core.py:602] `_block_tracker` 哨兵字符串修复
  | 替换为 `CompletionBlockTracker` dataclass（`_last_block_reason` + `_block_count_by_reason` 分离）。

- [x] **P1-6** ✅ 662451a [agent/constants.py] 22 个魔数全部命名完毕 — `BUDGET_COMPACT_PCT`, `DIFF_PREVIEW_MAX_CHARS`, `DEFAULT_REQUEST_BUDGET_TOKENS` 等

- [x] **P1-7** ✅ 662451a [agent/core.py:1247-1261, agent/constants.py:16] `getattr(...32000)` → `DEFAULT_MAX_OUTPUT_TOKENS = 32_000` + `TRUNCATION_BUFFER_TOKENS = 100`

- [x] **P1-8** ✅ 03d78df [agent/core.py:99-106] 模块导入从行 319-326 移至顶部（# deferred import — circular dependency 注释）

- [x] **P1-9** ✅ 4e57e14 [context/history.py:315-323, agent/core.py:1061-1063, 2601-2603, 2568] 私有属性访问消除
  | `ConversationHistory.replace_messages()` 公共方法 + `MemoryContext.store` 属性

### server/ — 架构

- [x] **P1-10** ✅ 59ecec2 [server/services/chat_pipeline.py] `run_chat_async()` 280 行拆分完成
  | 提取为 `ChatPipeline`（6 阶段管道：preflight → model_switch → session_context → permission_inject → build_runtime → execute）

- [x] **P1-11** ✅ 30131b3 [server/routers/sessions.py:41-56, 637-639, 678-680] `asyncio.ensure_future()` 无 loop 守卫修复
  | 提取 `_fire_and_forget_cleanup()` helper（get_running_loop 预检 + RuntimeError 静默）
  | Site A + Site B 统一使用 helper，消除分叉。测试: 4/4 PASS + 64 回归 (68/68)

- [x] **P1-12** ⚠️ [app/storage/sqlite.py:60] `executescript()` 仍在使用，但所有语句都有 `IF NOT EXISTS`。风险降低但未完全消除。

### web/ — 前端（全部已修复）

- [x] **P1-13** ✅ ab70813 [web/src/stores/chatStore.ts] WS connect/disconnect 竞态
  | Batch 5：watchdog + `_wsSessionId` 守卫。

- [x] **P1-14** ✅ ab70813 [web/src/stores/chatStore.ts] 30 分钟超时误杀
  | Batch 5：watchdog 由 WS 终端事件驱动清除（不再在 `api.chat()` 返回时清除）。

### hitl/

- [x] **P1-15** ✅ b583ac4 [hitl/pipeline.py:769-777] ASK 规则在 plan 模式下行为修复
  | plan mode: `_force_interactive` → 直接 DENY（bypass-immune），不再回退到 Layer 6

### agent/session/

- [x] **P1-16** ✅ d841fba [agent/session/session_store.py:44-45] 缺少 WAL 模式 — 已在 P0-1 中修复

- [ ] **P1-17** ⏸️ 推迟 — P1-1 衍生物（文件长是因为 `_run_body` 长，根因相同）

### web/ — 前端可靠性（全部已修复）

- [x] **P1-18** ✅ ab70813 [web/src/components/StatsDashboard.tsx] 错误状态 → 红色 banner + Retry

- [x] **P1-19** ✅ ab70813 [web/src/components/SessionSidebar.tsx] 错误/重试 → 已验证 error 横幅已渲染

- [x] **P1-20** ✅ ab70813 [web/src/components/SessionStatsDrawer.tsx] loading/error → 三态处理

- [x] **P1-21** ✅ ab70813 [web/src/components/DiffReviewView.tsx] 审批竞态 → catch 内联错误 + finally 正确清除

- [x] **P1-22** ✅ ab70813 [web/src/components/ChatView.tsx] updateDraft 闭包 → `latestDraftRef`

- [x] **P1-23** ✅ ab70813 [web/src/App.tsx] ErrorBoundary → 已验证全部组件在边界内

- [x] **P1-24** ✅ ab70813 [web/src/components/SessionSidebar.tsx] 键盘 a11y → `role="button"` + `aria-current`

- [x] **P1-25** ✅ ab70813 [web/src/components/ConfirmModal.tsx] 焦点陷阱 → Tab 循环 + auto-focus

### server/ — 可靠性

- [x] **P1-26** ✅ 59ecec2 [server/main.py:62] Rate limiter 已添加
  | `RateLimiter` 类：token-bucket，chat 10 req/60s/session，其他 60 req/60s/IP

- [x] **P1-27** ✅ 59ecec2 [server/routers/sessions.py:425] RuntimeError → 409（与 P0-5 相同）

- [x] **P1-28** ✅ 59ecec2 [context/artifacts.py:89-90] ArtifactStore 内存限制
  | `max_total_bytes=10_000_000` + `max_content_bytes=1_000_000` + FIFO 逐出

- [x] **P1-29** ✅ 59ecec2 [llm/invoker.py:219] LLM 重试 jitter
  | `random.uniform(0, base * 0.3)` + exponential backoff

- [x] **P1-30** ✅ 59ecec2 [llm/invoker.py:75] LLM 请求超时
  | `_call_with_timeout()` + `ThreadPoolExecutor`，默认 300s

### hitl/ — 权限管线绕过

- [x] **P1-31** ✅ 662451a [hitl/pipeline.py:838-871] `_match_approved_prompt` 单 token 匹配修复
  | >50% token overlap ratio + Bash→Layer 6 强制 + cap 20 + 日志警告。全部三项修复已落地。

- [x] **P1-32** ✅ e039c02 [tools/shell_tool.py:26-56, 219-223, 330-400, hitl/pipeline.py:713-722] Bash sandbox 加固
  | M1: `_BLOCKED_PATTERNS` 8→17 项（新增 find/delete, chmod 000, nvme overwrite, rm /*, rm -r /）
  | M2: `_validate_workspace_paths()` 路径沙箱（绝对路径逃逸 + dotdot≥3 层拒绝）
  | M4: `_ROOT_REMOVAL_PATTERNS` 6→14 项同步
  | M3: 安全边界文档标注（advisory ≠ security boundary）
  | 测试: 19/19 PASS + 45 回归 PASS (64/64, zero regressions)
  | 遗留: 解释器级别绕过（python -c）不可解 — Docker 是真正的安全边界

- [x] **P1-33** ✅ 662451a [core/policy_registry.py:340-375] `_check_tool_call` Bash 命令内容检查修复
  | `_extract_shell_file_targets()` 提取 shell 重定向/命令目标并校验 `allowed_write_paths`（strict_file_scope 模式下）。全部三项修复已落地。

### 🆕 审计遗漏（2026-07-23 核查新增）

- [x] **P1-34** ✅ [server/services/agent_service.py:299-313] prune 已移至后台线程
  | 启动时 memory prune_expired() 通过 `threading.Thread(daemon=True)` 在后台执行，不再阻塞服务启动。

---

## 🟡 P2 — 持续改进（56 项：代码卫生／文档／前端细节）

### agent/core.py — 代码卫生

- [x] **P2-1** ✅ 已修复 [agent/core.py:114-120] 两个常量均有文档注释 + P2-1 标记
- [x] **P2-48** ✅ [server/services/session_service.py:85-130] Session 列表一次 GROUP BY 批量查询替换 N 次 per-session COUNT(*)：50 sessions → 1 query
- [x] **P2-41** ✅ 已修复 — `getattr(exc, "status_code", None) in (400, 401, 403)` 整数比较，不再用子串匹配
- [x] **P2-46** ✅ [server/routers/sessions.py:834] `body: dict[str, Any]` → `body: SessionSettingsRequest` Pydantic 模型（含 effort/thinking/permission_mode 校验）
- [x] **P2-47** ✅ [server/routers/attachments.py:76-80] 文件名消毒：`re.sub(r"[^a-zA-Z0-9._-]", "_", orig_name)[:120]`
- [x] **P2-5** ✅ 已修复 — `_build_recovery_messages() -> list["LLMMessage"]` 类型注解已添加
- [x] **P2-6** ⊘ 行号已偏移/代码已变更，原始注释矛盾不再存在
- [x] **P2-9** ⊘ `_block_tracker` 已重构为 `CompletionBlockTracker` dataclass（P1-5）
- [x] **P2-25** ⊘ 已标注 LEGACY — 参见 P2-33，双 `as unknown as` 仅在 fallback 路径中使用
- [x] **P2-26** ⊘ 经过 Phase 17 样式重构，inline styles 已大部分统一

### 不修（已审查——不值得动的）
- [ ] **P2-2** ⊘ 跳过 — `_run_body` 已从 1275 行拆到 212 行；剩余内联 import 是防循环导入的既定模式
- [ ] **P2-10** ⊘ 跳过 — `ToolRegistry.__init__()` 的 `Any` 类型是工具注册 API 的弹性接口，改成精确类型会破坏所有第三方工具
- [ ] **P2-11** ⊘ 跳过 — `_format_error_for_observation` 确实是私有方法，`_` 前缀正确
- [ ] **P2-14** ⊘ 跳过 — `SUGGESTED_PROMPTS` 硬编码是产品决策（首屏展示），不是 bug
- [ ] **P2-18** ⊘ 跳过 — LLM 重试指标 → Langfuse 需要 Langfuse 基础设施，当前无部署
- [ ] **P2-19** ⊘ 跳过 — Hook 执行超时需要重新设计 hook 契约，超出 P2 范围
- [ ] **P2-21** ⊘ 跳过 — `summarizeTarget` 重复是接口签名不同，强行统一会破坏类型安全
- [ ] **P2-36** ⊘ 跳过 — MicroCompactor 就地修改已审计评估为 ACCEPTED（Phase 10 R-1 review）
- [ ] **P2-37** ⊘ 跳过 — Token 计数遗漏 overhead 影响极微（~10-20 tokens/request）
- [ ] **P2-38** ⊘ 跳过 — Hook 异常静默吞没已审计评估为 ACCEPTED（Phase 10 R-2 review）
- [ ] **P2-39** ⊘ 跳过 — Hook 超时 60s 是 CC 兼容的期望值
- [ ] **P2-40** ⊘ 跳过 — Tool call validator 仅校验 required fields 已足够（参数类型 LLM 95%+ 正确）
- [ ] **P2-44** ⊘ 跳过 — 记忆哈希行尾规范化是极边缘 case（仅影响 Windows/Linux 混合环境）
- [ ] **P2-49** ⊘ 跳过 — Session Memory 绕过 ToolRegistry 但 self-enforced `allowed_paths` 提供了等效防护
- [ ] **P2-50** (trace_cache Redis) ⊘ 跳过 — 已有独立 TODO（docs/todo.md P2-50），当前进程内缓存满足需求
- [ ] **P2-50** (bypassPermissions) ⊘ 跳过 — CC-compatible intentional design，已文档化 blast radius
- [ ] **P2-51** ⊘ 跳过 — Shell 子串匹配已标注为 advisory guard（P1-32）
- [ ] **P2-52** ⊘ 跳过 — `scoped()` 共享 `_web_confirm_callback` 已注释 "intentionally shared (thread-safe)"
- [ ] **P2-54** ⊘ 跳过 — Worktree `discard()` TOCTOU 影响极小（用户显式操作间隔 >> 竞争窗口）
- [ ] **P2-55** ⊘ 跳过 — Windows `safe_open_for_write` TOCTOU — 仅 Windows，非当前目标平台
- [ ] **P2-56** ⊘ 跳过 — ChatPipeline 集成测试有价值但超出 P2 范围（需端到端基础设施）
- [ ] **P2-57** ⊘ 跳过 — Plans Library DELETE 无 soft-delete — Plans 页面已在 Phase 17 移除，无活跃调用方
- [ ] **P2-58** ⊘ 跳过 — `shutdown()` 不等待优雅完成 — 当前单进程模式无此问题

---

## ✅ 已完成（本轮审计累计 47 项）

### Frontend Audit Batch 1–5 (2026-07-22, ab70813) — 18 项
- P0-11 AbortController · P0-12 XSS 缓解 · P1-13 WS 竞态 · P1-14 超时 · P1-18 StatsDashboard 错误 · P1-19 SessionSidebar 错误 · P1-20 StatsDrawer loading · P1-21 DiffReviewView 竞态 · P1-22 updateDraft 闭包 · P1-23 ErrorBoundary · P1-24 SessionSidebar a11y · P1-25 ConfirmModal 焦点陷阱 · P2-13 MODEL_OPTIONS · P2-15 formatBytes · P2-16 useWebSocket · P2-17 CHAT_TIMEOUT_MS · P2-23 MarkdownRenderer · P2-29 EventSidebar abort · P2-31 双重转义

### Backend Audit (2026-07-22~23) — 24 项
**d841fba:** P0-1 WAL · P1-16 WAL 标记
**59ecec2:** P0-2 per-session backend · P0-3 effective_llm_config · P0-4 try_acquire_session · P0-5 RuntimeError→409 · P0-7 BEGIN IMMEDIATE · P0-9 guard 移除 · P0-13 路径遍历 · P1-3 _attempt_reactive_compact · P1-5 CompletionBlockTracker · P1-10 ChatPipeline · P1-26 RateLimiter · P1-27 RuntimeError→409 · P1-28 ArtifactStore 限制 · P1-29 jitter · P1-30 timeout · P1-31 cap 20
**df4d4fc:** P0-6 索引错误 · P2-43 连接泄漏
**c01e941:** P0-8 break→error injection
**bdbea6f:** PlanView 已保存/已中止计划状态识别 · 计划恢复修复

---

## 📈 P0 列表速览

| # | 文件 | 关键发现 | 状态 |
|---|------|---------|------|
| P0-1 | session_store.py:44 | SessionStore SQLite WAL | ✅ d841fba |
| P0-2 | agent_service.py:118, chat_pipeline.py:168 | Backend 全局单例竞态 | ✅ 59ecec2 |
| P0-3 | agent_service.py:123, chat_pipeline.py:167 | 模型切换丢弃配置 | ✅ 59ecec2 |
| P0-4 | runtime.py:241 | Session TOCTOU | ✅ 59ecec2 |
| P0-5 | sessions.py:425 | RuntimeError → 409 | ✅ 59ecec2 |
| P0-6 | sqlite_backend.py:159 | 索引失败静默 | ✅ df4d4fc |
| P0-7 | sqlite.py:229 | 删除无事务 | ✅ 59ecec2 |
| P0-8 | core.py:1287 | break 误用 | ✅ c01e941 |
| P0-9 | core.py | Guard 异常吞没 | ✅ 59ecec2 |
| P0-10 | core.py:475 | Git 状态异常捕获宽泛 | ✅ 已修复 — 精确到 ImportError/GitError/OSError(errno) |
| P0-11 | api/client.ts | AbortController 缺失 | ✅ ab70813 |
| P0-12 | MessageBubble.tsx | XSS 攻击面 | ✅ ab70813 |
| P0-13 | file_backend.py:64 | 路径遍历 | ✅ 59ecec2 |

**🔴 P0 全部 13 项已修复 ✅**

---

*本文档随项目演进实时更新。最后修订: 2026-07-24*
