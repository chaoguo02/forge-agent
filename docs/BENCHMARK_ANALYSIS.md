# Grace-Code 对标分析报告

> **生成日期**: 2026-07-21  
> **Phase**: 3 — 对标分析  
> **对标项目**: Claude Code (Anthropic), Cursor Agent, Aider, OpenHands (All-Hands-AI)  
> **审计基线**: Phase 2 深度审计发现的 99 项问题

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [✅ 我们的优势](#2-我们的优势)
3. [⚠️ 关键不足与改进路线图](#3-关键不足与改进路线图)
4. [🚨 严重问题 — 分批修复路线图](#4-严重问题--分批修复路线图)
5. [批次规划](#5-批次规划)
6. [附录：对标准确性声明](#附录对标准确性声明)

---

## 1. 执行摘要

Grace-Code 在 **ReAct 引擎架构**、**5 层上下文压缩**、和 **V2 子代理编排**三个子系统上已达到或接近 Claude Code 级别。但在 **错误处理健壮性**、**安全防护深度**、和 **并发隔离**三个关键维度上与业界标杆存在显著差距。

本报告将 13 项 P0 问题编组为 **3 个优先级递减的批次**（每批 ≤5 项），每批包含：修复内容 → 测试方案 → 回归验证标准 → Commit 规范 → 批次反思。

### 量化结论

| 维度 | Grace-Code | Claude Code | Cursor | OpenHands | Aider |
|------|-----------|-------------|--------|-----------|-------|
| ReAct Loop 健壮性 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 权限管线深度 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| 上下文压缩 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| 子代理隔离 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | N/A |
| 并发安全 | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 错误处理 | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## 2. ✅ 我们的优势

以下子系统在架构设计上**持平或优于**对标项目。这些是我们的核心竞争力，应继续强化。

### 2.1 V2 子代理编排 (Fork/Worktree/Background)

**业界定标**:
- Claude Code 子代理: 深度=1 限制，fork + background 执行，worktree 隔离
- OpenHands 子代理: 独立 Docker 容器，`AgentDelegateAction` → `AgentDelegateObservation`
- Cursor: Planner-Worker-Judge 层级架构，子代理共享环境但新鲜上下文

**Grace-Code 优势**:

1. **三种执行模式覆盖全场景**: Fork (worktree 隔离) / Fresh Context (轻量级) / Background (异步)，比 Claude Code 的 "depth=1 Fork only" 更灵活
2. **_ChildTurnPhase 生命周期**: 独创 SYNTHESIS → RESOLUTION_PENDING → NONE 状态机，显式管理子代理结果处理和 worktree 清理 — 这是 **OpenHands 和 Cursor 均未实现**的精细化子代理生命周期管理
3. **继承式权限管线**: 子代理继承父级 deny/allow 规则 + permission_mode 传播（[P2-50](docs/TODO.md#p2) 的 bypassPermissions 继承问题已识别，修复后即接近 CC 标准）
4. **Worktree 工具化**: `subagent_worktree_apply/discard/retain` 三个显式操作 + WS 实时推送 `worktree_resolved` — **独有设计**，OpenHands 和 Aider 均无等价机制

**结论**: 此子系统是 Grace-Code 的最强项。V2 的 `_ChildTurnPhase` + 显式 worktree 操作已超出业界定标。

---

### 2.2 5 层上下文压缩管道

**业界定标**:
- Claude Code: 4-5 层 (Budget → Snip → Microcompact → ContextCollapse → AutoCompact)，核心设计是 Layer 4 的 **只读投影** + 可回退到任意检查点
- Aider: RepoMap（tree-sitter 符号图）+ 选择性文件加载 — 仅在"文件级"操作
- OpenHands: `LLMSummarizingCondenser` — 单层 LLM 摘要
- Cursor: 推测解码 + 上下文压缩 — 侧重延迟优化

**Grace-Code 优势**:

1. **全覆盖的 5 层管道**: 对标 Claude Code 的完整层级（Budget → Snip → MicroCompact → Collapse → AutoCompact），每层独立可测
2. **CollapseStore 只读投影**: 与 Claude Code Layer 4 的"不修改底层 JSONL"设计意图一致 — `projectView()` 生成压缩视图而不修改原始历史
3. **Zero-cost 前置层**: Budget/Snip/Micro 三层在 LLM 调用前执行，零额外 API 消耗 — 与 Claude Code 的"cheapest first"原则一致
4. **CompactionRecovery 后处理恢复**: 自动重新注入最近文件、CLAUDE.md、记忆 — 与 Claude Code Post-AutoCompact 恢复完全对齐

**对比 OpenHands**: OpenHands 的 `LLMSummarizingCondenser` 仅为单层 LLM 摘要（成本高、无渐进式策略），Grace-Code 的 5 层管道明显更优。

**对比 Aider**: Aider 的 RepoMap 是优秀的"代码库认知"工具，Grace-Code 也有 `context/repo_map.py`，但 Aider 缺少完整的对话历史压缩管道。

**结论**: 此子系统是 Grace-Code 与 Claude Code 对齐度最高的领域。唯一的差距是 Layer 4 的持久化格式（CC 用 JSONL、我们用内存 `CollapseStore`），但这不影响功能性。

---

### 2.3 ReAct 核心架构

**业界定标**:
- Claude Code: 单一 `while(tool_call)` 循环，模型自行决定何时调用工具和何时结束
- OpenHands: 事件溯源架构 — Agent 是"从事件历史到下一个事件的纯函数"
- Cursor: Planner-Worker-Judge 层级化多代理架构
- Aider: `Coder` 工厂模式 + 12 种可互换编辑格式

**Grace-Code 优势**:

1. **StreamingToolExecutor**: 与 Claude Code 的"tool pre-execution"对齐 — 在 LLM 流式生成时同步 dispatch 工具调用，隐藏工具延迟
2. **不可变 AgentTurnState**: 每次 turn 创建新实例，与 OpenHands V1 的"immutable Agent"设计原则一致
3. **Circuit Breaker**: 4 类计数器（consecutive_denial/session_denial/subagent_failure/tool_error）+ 独立检测，接近 Claude Code 的业界最佳实践
4. **RuntimeController 强制门**: 在每步 LLM 调用前执行检查，模型无法覆盖 — 与 `Production-Safe Agent Loop` 的 "pre-flight not post-flight" 原则一致

**对比 Cursor**: Cursor 的 Planner-Worker-Judge 更适用于超大规模任务（1M+ LOC），Grace-Code 的单一 ReAct + 子代理 Fork 更适用于中大型项目。两者定位不同，非高下之分。

**结论**: 架构设计方向正确且稳健。

---

## 3. ⚠️ 关键不足与改进路线图

### 3.1 错误处理健壮性 (差距: 3 星)

**对标**: Claude Code 使用 7 种 "continue strategies" 处理 LLM 失败、`max_tokens` 截断、上下文溢出。OpenHands 使用"stage-gated pipeline"禁止非法状态转换。Cursor 对每个 per-tool per-model 错误创建 baseline + anomaly detection。

**Grace-Code 问题**:

| Phase 2 发现 | 问题 | 业界定标 | 差距分析 |
|-------------|------|---------|---------|
| **P0-8** | `break` 误用 — 工具校验失败直接退出循环 | CC: 工具校验失败 → 注入结构化错误 observation → 模型自修正 | 逻辑 bug，非设计局限。修复为 `continue` 即解决 |
| **P0-9** | TSM guard 异常完全吞没 | 工业界共识: guard 失败应默认 FAIL_CLOSED | 违反 defense-in-depth |
| **P0-10** | Git 状态捕获过于宽泛的 except | CC: 区分 `ImportError`/`InvalidGitRepositoryError` | 低风险但不符合 production 标准 |
| **P1-29** | LLM 重试无 jitter | CC: 7 种 continue strategies + backoff jitter | 多 session 场景雷群效应风险 |

**改进路线图**:

| 改进 | 估时 | 依赖 | 对应 TODO |
|------|------|------|----------|
| 工具校验失败 → 注入 error observation (改 `continue`) | 小 (1h) | 无 | P0-8 |
| Guard 异常 → FAIL_CLOSED + `logger.error` | 小 (0.5h) | 无 | P0-9 |
| Git except → 具体异常类型 | 小 (0.5h) | 无 | P0-10 |
| Retry jitter + structured error taxonomy | 中 (4h) | 无 | P1-29 |

---

### 3.2 安全防护深度 (差距: 3 星)

**对标**: Claude Code 的 7 层防御体系包括 **Bash AST 分析**（23 项静态安全检查）、macOS Seatbelt/Linux namespace 进程沙箱。OpenHands 的 Docker 容器化 `cap-drop ALL, no-new-privileges`。Cursor 的自定义沙箱基础设施。

**Grace-Code 问题**:

| Phase 2 发现 | 问题 | 业界定标 | 差距分析 |
|-------------|------|---------|---------|
| **P1-31** | `_match_approved_prompt` 单 token 交集 | CC: Bash AST 分析 + 23 项检查 | **最大安全差距** — plan 审批 → Bash 逃逸 |
| **P1-32** | Bash 命令参数不受路径沙箱限制 | OpenHands: Docker `cap-drop ALL` + overlay FS | Worktree 隔离仅为工作目录级，非文件系统级 |
| **P1-33** | `strict_file_scope` 对 Bash 无约束 | CC: Bash 被视为 "universal adapter" 但受 7 层防御约束 | 策略层从未检查 Bash 命令内容 |
| **P2-51** | `_ROOT_REMOVAL_PATTERNS` 仅为子串匹配 | CC: AST 级分析 — 等价命令检测 | 黑名单方法固有缺陷 |
| **P0-13** | 路径遍历 — 记忆文件名未消毒化 | 通用 Web 安全: `sanitize_path()` 应在文件写前执行 | 严重安全漏洞 |

**改进路线图**:

| 改进 | 估时 | 依赖 | 对应 TODO |
|------|------|------|----------|
| `_match_approved_prompt` → 多数 token 交集 (>50%) + cap 20 条目 | 中 (3h) | 无 | P1-31 |
| Bash 重定向目标路径提取 + 应用 `allowed_write_paths` | 中 (6h) | P1-33 | P1-32 |
| `_check_tool_call` → 对 Bash 执行路径级策略检查 | 中 (4h) | P1-32 | P1-33 |
| 记忆文件名消毒化 + resolve 验证 | 小 (1h) | 无 | P0-13 |
| Docker/容器沙箱 (长期) | 大 (40h+) | P1-32 | — |

---

### 3.3 并发安全 (差距: 2 星)

**对标**: OpenHands 的 "stateless components, immutable events" 设计保证无竞态。Cursor 使用 Temporal 工作流引擎，活动成功率 99%+。Claude Code 本身也遇到 [Issue #14124](https://github.com/anthropics/claude-code/issues/14124) — 并行 Explore 子代理因 SQLite 锁冻结 — 修复方案为 **WAL 模式 + `busy_timeout`**。

**Grace-Code 问题**:

| Phase 2 发现 | 问题 | 业界定标 | 差距分析 |
|-------------|------|---------|---------|
| **P0-1** | SessionStore SQLite 无 WAL | 社区修复 CC Bug #14124 的方案: `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=10000` | **完全相同的 bug** — Claude Code 已验证修复 |
| **P0-2** | LLM Backend 全局单例在多 daemon 线程中竞态 | OpenHands: immutable `Agent` + per-invocation `LLM` 实例 | 根本性架构缺陷 |
| **P0-3** | 模型切换丢弃自定义 api_key/base_url | Cursor: mid-chat 模型切换由 harness 层管理状态 | 状态管理缺陷 |
| **P0-4** | Session 创建 TOCTOU | OpenHands: "The only mutable thing is ConversationState" | 需原子化 test-and-set |
| **P0-7** | Session 删除非事务性 | 数据库常识: `BEGIN IMMEDIATE` | 简单修复 |

**改进路线图**:

| 改进 | 估时 | 依赖 | 对应 TODO |
|------|------|------|----------|
| SessionStore WAL + busy_timeout | 小 (0.5h) | 需测试并发 session 场景 | P0-1 |
| Backend per-session 实例化 (不共享全局单例) | 中 (6h) | 影响 SessionRuntime API | P0-2 |
| Save effective LLM config fields independently | 小 (2h) | P0-2 | P0-3 |
| `BEGIN IMMEDIATE` 事务包裹 session 删除 | 小 (1h) | 无 | P0-7 |
| Session TOCTOU: in-DB atomic state check | 中 (3h) | P0-1 (需 WAL 支持) | P0-4 |

---

### 3.4 Web 前端质量 (差距: 3 星)

**对标**: Claude Code 内置 144 个 React 组件 + 85 个 hooks，完整的 React Compiler 优化。Cursor 有专门的 harness 层管理前后端交互。

**Grace-Code 问题** (汇总 Phase 2 Web 发现):

| 类别 | 数量 | 关键项 |
|------|------|--------|
| Missing error states | 3 | StatsDashboard, SessionSidebar, SessionStatsDrawer |
| Accessibility gaps | 4 | Session list, ToolCallCard, Modal focus trap, ThemeToggle |
| Race conditions | 3 | DiffReview double-submit, updateDraft stale closure, WS connection |
| Duplicated utilities | 5 | summarizeTarget (3x), formatValue (2x), renderMarkdown (2x) |
| XSS surface | 1 | dangerouslySetInnerHTML + regex markdown |
| Missing AbortController | 1 | All API calls leak on unmount |

**改进路线图**: 在 Phase 4 精准定位中详细展开。

---

## 4. 🚨 严重问题 — 分批修复路线图

> **原则**: 每批 ≤5 项，按依赖关系和风险等级分组。每批包含：修复内容 → 测试方案 → 回归验证标准 → Commit 规范 → 批次后反思要点。

---

### 🔴 批次 A（立即修复 — 并发与数据安全）

**选择理由**: P0-1/P0-2 是整个系统的基础 — 数据库不可靠和 backend 竞态会影响所有其他功能。P0-7/P0-13 是数据完整性和安全漏洞。P0-8 是逻辑 bug。

| # | TODO | 修复内容 | 估时 |
|---|------|---------|------|
| A1 | **P0-1** session_store.py SQLite 无 WAL | `_connect()` 添加 `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=10000; PRAGMA synchronous=NORMAL` | 0.5h |
| A2 | **P0-2** Backend 全局单例竞态 | 将 `self._backend` 从 AgentService 移至 SessionRuntime，每次 `run_session()` 创建 scope-local backend | 6h |
| A3 | **P0-7** Session 删除非事务性 | `delete_session()` 和 `batch_delete()` 包裹在 `BEGIN IMMEDIATE`/`COMMIT` 中 | 1h |
| A4 | **P0-13** 记忆文件路径遍历 | `FileMemoryBackend._file_path()` 校验 name 仅含 `[a-zA-Z0-9_-]` 且 resolve 后 `relative_to(store_dir)` 通过 | 1h |
| A5 | **P0-8** `break` 误用 → `continue` | `agent/core.py:1294` 改 `break` 为 `continue`，使工具校验失败后 LLM 能看到 error observation 并自修正 | 0.5h |

#### 批次 A 测试方案

| # | 测试方法 | 预期结果 |
|---|---------|---------|
| A1 | 启动 3+ 并发 session 对同一 repo 执行 `chat` 操作 | 所有 session 完成无 `SQLITE_BUSY` 错误；WAL 文件 (<hash>-wal) 出现在 `.grace/v2/` 目录 |
| A2 | Session A 运行中 → Session B 切换模型 → 检查 Session A 的 LLM 调用是否受影响 | Session A 继续使用原始 model/api_key；Session B 使用新 model |
| A3 | 删除含子代理通知的 session → 检查 DB `agent_notifications` 表 | 所有关联记录被清理，无孤儿行 |
| A4 | POST `/api/memory/{id}/save` 中 `name="../../.env"` → 检查是否被拒绝 | 400 Bad Request 或文件名被消毒化（仅保留字母数字） |
| A5 | Mock LLM 返回"参数缺失"的 invalid tool call → 检查下一轮 LLM 是否收到 error observation | Agent 继续运行（不退出），LLM 在下一轮修正参数 |

#### 回归验证标准

- [ ] 所有现有 `pytest tests/` 通过
- [ ] `tests/test_e2e_core.py` 通过
- [ ] `python -m server.main` 启动无错误
- [ ] Web UI 并发 2 个 session 正常工作

#### Commit 规范

```
fix(P0): batch A — concurrency safety & data integrity

P0-1: SessionStore enable WAL mode + busy_timeout
P0-2: Backend per-session instantiation (no shared singleton)
P0-7: Transactional session deletion (BEGIN IMMEDIATE)
P0-13: Sanitize memory file names (path traversal fix)
P0-8: Fix break→continue for tool validation error recovery

Fixes: #P0-1 #P0-2 #P0-7 #P0-13 #P0-8
```

#### 批次 A 反思要点

1. **P0-2 是否过度设计？** 如果当前仅单用户使用，per-session backend 可能过重。评估方案: 先用 `threading.Lock()` 保护 backend 访问作为短期对策，per-session backend 作为 Phase 4 架构优化。
2. **WAL 模式是否影响现有功能？** 需确认所有 SQLite 连接源（SessionStore, SqliteMemoryBackend, SqliteStorageBackend）都统一启用 WAL。验证 `memory/sqlite_backend.py:54` 已设置——但 `app/storage/sqlite.py:57` 使用的 `_store._connect()` 将继承新设置。
3. **P0-8 的 break→continue 是否引入无限循环？** 验证有 `max_steps` 上限。确认 runtime_controller 在每步前检查 step 计数。

---

### 🟠 批次 B（本周修复 — 权限与安全深度）

**选择理由**: P1 中 3 个权限绕过发现（P1-31/32/33）构成最大安全差距；P0-9/P0-6 是 defense-in-depth 基本要求。

| # | TODO | 修复内容 | 估时 |
|---|------|---------|------|
| B1 | **P1-31** Plan 审批 token 匹配太弱 | `_match_approved_prompt()` → 要求 >50% approved tokens 出现在 params 中（而非单个）；添加 `_approved_prompts` cap=20；Bash 命令强制 Layer 6 | 3h |
| B2 | **P1-32** Bash 不受路径沙箱约束 | 添加 `_extract_bash_file_targets(command: str) -> list[str]` 工具函数；在 `_check_tool_call()` 中对 Bash 提取目标文件并验证 `allowed_write_paths` | 6h |
| B3 | **P1-33** `strict_file_scope` Bash 绕过 | 在 `_check_tool_call()` 中添加 Bash 命令路径提取（与 B2 共享），对写入目标文件应用策略限制 | 并入 B2 |
| B4 | **P0-9** TSM guard 异常吞没 | Guard 函数异常 → `logger.error(exc_info=True)` + FAIL_CLOSED（拒绝转换） | 0.5h |
| B5 | **P0-6** 语义搜索索引失败静默 | `SqliteMemoryBackend` 添加 `_index_error: str | None` 字段；`write_memory()` 返回中包含 indexer 状态；至少 `logger.warning()` | 1h |

#### 批次 B 测试方案

| # | 测试方法 | 预期结果 |
|---|---------|---------|
| B1 | Plan 审批 "Run tests" → 检查 `Bash("rm -rf / # test")` 是否仍触发交互审批 | `_match_approved_prompt()` 返回 None；Layer 6 触发审批卡片 |
| B2 | 配置 `allowed_write_paths=["src/"]` → 代理执行 `Bash("echo x > /tmp/out")` | 被 `_check_tool_call()` 拦截，返回 `[RUNTIME BLOCK] PATH ACCESS DENIED` |
| B3 | `strict_file_scope=True` → 代理执行 `Bash("rm /important/file")` | 被拦截，错误消息指出路径不在允许范围 |
| B4 | Mock guard 抛出 `Exception` → 检查 TSM 转换是否被拒绝 | Guard 转换返回 `passed=False`，日志包含完整 traceback |
| B5 | 断开语义搜索索引（FAISS/Chroma）→ 写入记忆 → 检查响应 | 返回成功但标记 `indexed: false`；warning 日志记录关闭原因 |

#### 回归验证标准

- [ ] 现有 Plan 模式测试通过（`tests/test_plan_approval.py`）
- [ ] 手动测试: Plan → Approve → Build 流程中 Bash 命令仍可被审批/拒绝
- [ ] 手动测试: `strict_file_scope` 代理无法通过 Bash 写入 `/tmp`

#### Commit 规范

```
fix(P1): batch B — permission pipeline depth hardening

P1-31: Require majority token overlap in plan prompt matching
P1-32: Extract and validate Bash file targets against path policy
P1-33: Apply strict_file_scope to Bash commands
P0-9:  Guard exceptions → FAIL_CLOSED with full error logging
P0-6:  Surface semantic indexer failures in memory write response

Fixes: #P1-31 #P1-32 #P1-33 #P0-9 #P0-6
```

#### 批次 B 反思要点

1. **Bash 路径提取的精确性** — `_extract_bash_file_targets()` 的正则方法不具备 Shell AST 级别的准确性。与 Claude Code 的 tree-sitter 对比有精度差距。应在 Phase 4 记录为长期改进。
2. **P1-31 的 token 匹配阈值** — ">50% tokens 重叠" 是否足够严格？应监控审批模式，准备调高至 70%。
3. **B2+B3 是否造成过多误拦？** 初始阶段仅记录 warning 级别的拦截日志（不硬 block），运行一周后分析模式再启用严格模式。

---

### 🟡 批次 C（2 周内 — 可靠性加固）

**选择理由**: 前端可靠性（error states, race conditions, accessibility）+ 后端重试健壮性 + model 切换数据完整性。

| # | TODO | 修复内容 | 估时 |
|---|------|---------|------|
| C1 | **P0-3** 模型切换丢弃 api_key/base_url | 保存有效 LLM 配置为 `_effective_llm_config` 独立字段；切换时从此读取而非静态 config | 2h |
| C2 | **P0-11** API client 缺少 AbortController | `web/src/api/client.ts` 添加 `signal` 参数；所有 fetch 组件在 useEffect cleanup 中 abort | 4h |
| C3 | **P0-12** dangerouslySetInnerHTML XSS | 替换 `renderMarkdown` 为正则→JSX 转换器（无 raw HTML）或集成 DOMPurify | 3h |
| C4 | **P1-29** LLM 重试无 jitter | `delay *= 2; delay += random.uniform(0, delay * 0.3)` | 0.5h |
| C5 | **P0-4** Session TOCTOU | `try_acquire_session()` 使用 `BEGIN IMMEDIATE` 事务原子化状态检查+获取 | 3h |

#### 批次 C 测试方案

| # | 测试方法 | 预期结果 |
|---|---------|---------|
| C1 | CLI `--base-url=http://custom` → 启动 → 切换 model → 检查 base_url 是否保持 | base_url 不变；`_effective_llm_config` 反映当前有效值 |
| C2 | 快速切换 tab 3 次 → 检查 Network 面板暂停的请求数 | 上一个 tab 的 pending requests 显示 `(canceled)` |
| C3 | 向 chat 发送恶意 markdown: `<img src=x onerror=alert(1)>` → 检查渲染 | 渲染为文本而非 HTML；`onerror` 不执行 |
| C4 | 模拟 3 次 LLM 超时 → 检查重试间隔 | 间隔为 ~1s, ~2.3s, ~5.1s（非精确 1s, 2s, 4s） |
| C5 | 并发 10 个请求创建同一 session → 检查只有 1 个成功 | 9 个返回 409，1 个正常执行 |

#### Commit 规范

```
fix(P0/P1): batch C — reliability hardening (frontend + retry)

P0-3:  Preserve custom LLM config across model switches
P0-11: AbortController for all API fetch calls
P0-12: Replace dangerouslySetInnerHTML with safe markdown→JSX
P1-29: Add jitter to LLM retry backoff
P0-4:  Atomic session acquisition with BEGIN IMMEDIATE

Fixes: #P0-3 #P0-11 #P0-12 #P1-29 #P0-4
```

---

## 5. 批次规划

```
Week 1 ──── 批次 A (并发与数据安全)          5 项 P0   ─── 立即部署
Week 1-2 ── 批次 B (权限与安全深度)            5 项 P1+P0 ─── 部署前审批
Week 2-3 ── 批次 C (可靠性加固)                5 项 P0+P1 ─── 逐步 rollout
Week 3-4 ── P1 扫尾: 前端 error states、    剩余的 P1   ─── 按模块分配
            accessibility、ArtifactStore、
            限流
Week 4+ ─── P2 持续改进: 重复代码提取、       剩余的 P2   ─── 日常工程节奏
            类型修复、magic numbers 消除
长期 ───── Docker 沙箱、Bash AST 分析、      架构级     ─── Phase 4 设计
           agent/core.py 拆分、Plugin 系统
```

---

## 附录：对标准确性声明

1. **Claude Code 信息**来自官方文档 [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) + 源码分析仓库 [how-claude-code-works](https://github.com/Windy3f3f3f3f/how-claude-code-works) + CVE 数据库 + GitHub Issues。截止 2026-07，CC 处于 v2.1.x 版本。

2. **OpenHands 信息**来自 [OpenHands V1 SDK](https://dev.to/pickuma/openhands-review-the-open-source-autonomous-coding-agent-in-2026-5gcj) + [sandbox architecture](https://blog.elest.io/openhands-give-your-coding-agent-its-own-sandbox-not-your-laptop/) + 架构分析文档。

3. **Cursor 信息**来自 [Cursor 官方博客](https://cursor.com/en-US/blog/continually-improving-agent-harness) + [ZenML LLMOps 数据库](https://www.zenml.io/llmops-database/optimizing-agent-harness-for-openai-codex-models-in-production)。

4. **Aider 信息**来自 [DeepWiki 架构分析](https://deepwiki.com/helloandworlder/aider/1.2-architecture-overview) + [technical architecture 文档](https://github.com/lperry65/Aider-Chat/blob/main/docs/technical-architecture.md)。

5. **错误处理最佳实践**来自 [VIGIL paper (Dec 2025)](https://arxiv.org/abs/2512.07094) + [Agent Circuit Breaker pattern](https://github.com/nibzard/awesome-agentic-patterns/blob/main/patterns/agent-circuit-breaker.md) + [Production-Safe Agent Loop](https://www.freecodecamp.org/news/how-to-build-a-production-safe-agent-loop-from-exit-conditions-to-audit-trails/)。

6. **SQLite WAL 信息**来自 [Claude Code Issue #14124](https://github.com/anthropics/claude-code/issues/14124) + [Fixing Claude Code's Concurrent Session Problem](https://dev.to/daichikudo/fixing-claude-codes-concurrent-session-problem-implementing-memory-mcp-with-sqlite-wal-mode-o7k)。

---

*本文档随项目演进实时更新。最后修订: 2026-07-21*
