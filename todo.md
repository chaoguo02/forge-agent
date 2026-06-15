# forge-agent 开发任务清单

对照 PaiCLI 第 1-21 期路线图，逐期分析 forge-agent 的完成度与后续任务。

---

## 逐期对照总览

| 期数 | PaiCLI 主题 | forge-agent 状态 | 对应任务 |
|------|------------|------------------|---------|
| 1 | 基础 ReAct + Tool Call | ✅ 完成 | — |
| 2 | Plan-and-Execute | ✅ 完成 | — |
| 3 | Memory + 上下文工程 | ✅ 完成 | — |
| 4 | RAG + 代码库理解 | ✅ 完成 | — |
| 5 | Multi-Agent 协作 | ❌ 未开始 | 任务 15 |
| 6 | HITL + 审批流 | 🟡 部分 | 任务 5 |
| 7 | 异步 + 并行工具 | ✅ 完成 | — |
| 8 | 多模型适配 + 运行时切换 | ✅ 完成 | — |
| 9 | 联网能力 + Web 工具 | ✅ 完成 | — |
| 10 | MCP 协议核心 | ✅ 完成 | — |
| 11 | MCP 高级能力 | ❌ 未开始 | 任务 10 |
| 12 | 长上下文工程 + Prompt Caching | 🟡 部分 | 任务 7 |
| 13 | Chrome DevTools MCP | ❌ 未开始 | 任务 11 |
| 14 | CDP 会话复用 + 登录态 | ❌ 未开始 | 任务 12 |
| 15 | Skill 系统 | ❌ 未开始 | 任务 13 |
| 16 | TUI 界面 + 产品化 | ✅ 完成 | — |
| 17 | LSP 诊断注入 | ❌ 未开始 | 任务 16 |
| 18 | Git Side-History 快照回滚 | ❌ 未开始 | 任务 17 |
| 19 | Prompt 分层架构 | ❌ 未开始 | 任务 18 |
| 20 | 后台任务 + Runtime API | ❌ 未开始 | 任务 19 |
| 21 | 图片复制粘贴输入 | ❌ 未开始 | 任务 20 |

---

## 现状说明 v1.0-rc

> forge-agent 已达到 **v1.0-rc** 里程碑，核心能力（ReAct、Plan-and-Execute、Memory、RAG、并行工具、MCP、TUI、Web 工具）已全部完成。后续任务集中在高级能力和产品化方向。
>
> - 全量测试：**677 passed, 7 skipped**
> - 三层记忆系统（短期/长期/向量语义检索）+ 主动记忆
> - 多模型支持（Claude / DeepSeek / OpenAI / Groq / Ollama）
> - 运行时 `/model` `/mode` 动态切换
> - Docker 沙箱隔离执行

---

## ✅ 已完成能力一览

### 第 2 期：Plan-and-Execute ✅

- `agent/plan.py` — PlanExecuteConfig + Plan/SubTask 数据结构
- `agent/core.py` — PlanExecuteAgent（先规划 DAG 再逐步执行）
- `agent/factory.py` — react / plan / auto 三种模式，`/mode plan` 切换
- 复杂任务自动拆解为多步计划（SimpleTaskClassifier）

### 第 3 期：Memory 系统 ✅

- **短期记忆**：`ConversationHistory` — 滑动窗口 + 首条不丢弃
- **长期记忆**：`memory/store.py` — 文件型持久化（YAML frontmatter .md）
- **上下文摘要**：`context/compaction.py` — LLM 压缩 + regex fallback，8 轮压缩保护
- **Token 预算**：`context/token_budget.py` — tiktoken 精确计数 + 字符 fallback
- **主动记忆保存**：`memory/proactive.py` — 模式检测（修正/偏好/命令）自动触发
- **记忆上下文注入**：`memory/context.py` — 每轮自动注入相关记忆

### 第 4 期：RAG 检索 ✅

- `memory/external_store.py` — SQLite + fastembed（BGE-small-zh-v1.5）向量语义搜索
- `memory/chunker.py` — 语义分块（段落/标题边界 + 滑动窗口）
- `memory/indexer.py` — 写入时自动向量索引
- `memory/retriever.py` — ProactiveRetriever（每轮自动按用户消息语义搜索）
- `RepoMap` — tree-sitter AST 提取函数/类定义，9 种语言 + 正则 fallback（互补而非替代 RAG）

### 第 6 期：HITL + 安全机制（部分）

**已有**：
- Shell 三层安全（硬拦截黑名单 → 白名单免确认 → confirm_callback 确认）
- `terminal_confirm()` 交互式确认
- Docker 沙箱（`DockerRuntime`：懒启动 + 网络隔离 + bind mount）
- Web 工具 SSRF 防护（URL 白名单 + DNS 解析 + 内网 IP 拦截）

**缺失**（见任务 5）：
- 操作审计日志（`AuditLog`），路径围栏（`PathGuard`），CLI `/policy` 命令

### 第 7 期：异步 + 并行工具 ✅

- 原生 OpenAI/Anthropic multi-tool-call 支持
- `test_chat.py` 有 `test_multiple_tool_calls_in_one_round` 测试用例
- 并行执行多个 tool_calls，统一结果收集

### 第 8 期：多模型运行时切换 ✅

- `llm/router.py` — 5 个 Provider + 自动选择
- `.env` 统一配置（`FORGE_LLM_PROVIDER` / `FORGE_LLM_MODEL` / `FORGE_LLM_BASE_URL`）
- 运行时 `/model <name>` 命令动态切换，历史保留
- CLI `--model` 参数优先级最高

### 第 9 期：联网能力 ✅

- `tools/web_tool.py` — `WebSearchTool`（DuckDuckGo）+ `WebFetchTool`（readability）
- `tools/web_utils.py` — URL 校验、SSRF 防护（内网拦截 + DNS 验证）、重试、大小限制
- `mcp_servers/web_search_server.py` — MCP web search server
- 安全：scheme 白名单、响应体限制（100KB）、可配置超时

### 第 10 期：MCP 协议核心 ✅

- `tools/mcp_client.py` — 完整 MCP 客户端
  - `stdio_client` 子进程通信（JSON-RPC 2.0 via mcp Python SDK）
  - 自动发现远程工具 → 包装为 `BaseTool` 注册到 `ToolRegistry`
  - `MCPToolProxy` 对 agent core 完全透明
- 支持 Claude Desktop 兼容的 MCP Server 配置
- 扩展点：支持 Brave Search、Postgres 等第三方 MCP Server

### 第 16 期：TUI 产品化 ✅

- `entry/renderer.py` — `RendererBase` 接口 + `InlineRenderer`（完整 TUI）+ `PlainRenderer`（降级）
- InlineRenderer 特性：
  - 底部状态栏（模型名、token 用量、耗时）
  - 工具调用黄色可折叠面板
  - diff 语法高亮（ANSI 着色）
  - 诊断块红/黄 ANSI 渲染
  - 流式 Markdown 渲染（thought + message 分离）
- `entry/chat.py` — 使用 Renderer
- `entry/cli.py` — `--renderer inline|plain` 参数
- `entry/history_viewer.py` — 历史记录查看器

---

## 🟡 已部分完成 — 需补齐的缺口

### 第 6 期缺口：HITL 增强

**已有**：
- Shell 四层安全（黑名单硬拦截 → 白名单免确认 → confirm_callback 确认 → 输出截断）
- `terminal_confirm()` 交互式确认
- `always_allow()` / `always_deny()` 可注入回调
- Docker 沙箱（`DockerRuntime`）
- Web 工具 SSRF 防护

**缺失**：
- 操作审计日志（`AuditLog`）：危险工具调用按天写 JSONL
- 路径围栏（`PathGuard`）：file_read / file_write 限制在项目根目录内
- `write_file` 单文件大小上限
- CLI `/policy` 查看安全策略状态

### 第 12 期缺口：长上下文工程

**已有**：
- `context/token_budget.py` — 动态预算（按模型 max_context_window 的 80% 计算）
- `context/compaction.py` — ConversationCompactor（LLM 摘要 + regex fallback）
- `llm/anthropic_backend.py` — 支持 Anthropic prompt caching

**缺失**：
- 模型能力声明（`maxContextWindow` / `supportsPromptCaching`）
- Short / Balanced / Long 三种上下文模式
- OpenAI/DeepSeek prompt caching（解析 `cached_tokens` 字段）
- 上下文成本可见化（每轮展示 token 用量 + 缓存节省比例）
- 检索策略自适应（长窗口提高 topK）

---

## 🔴 Tier 1 — 基础能力补齐（预计 3-5 周）

---

### 任务 5：操作审计 + 路径围栏（PaiCLI 第 6 期增强）

**目标**：补齐安全体系中的审计和路径保护。

**子任务**：
- [ ] 新建 `tools/audit.py` — AuditLog，按天分文件 JSONL
  - 字段：`timestamp, tool, params_summary, outcome(allow|deny|error), approver(hitl|policy|none)`
- [ ] 新建 `tools/path_guard.py` — PathGuard
  - `validate(repo_root, file_path)` — 拦截绝对路径、`..` 穿越、符号链接逃逸
- [ ] `tools/file_tool.py` — FileReadTool / FileWriteTool 接入 PathGuard
- [ ] `tools/base.py` — ToolRegistry.execute 接入 AuditLog
- [ ] `config/default.yaml` — `safety:` 配置段（`max_file_size_mb`、`audit_enabled`）
- [ ] 编写测试：路径越界、符号链接、审计落盘验证
- [ ] CLI：`/policy` 查看安全策略、`/audit [N]` 查看审计记录

**改动文件**：
- 新建 `tools/audit.py`
- 新建 `tools/path_guard.py`
- `tools/file_tool.py` — PathGuard 接入
- `tools/base.py` — AuditLog hook
- `config/default.yaml` — `safety:` 段

---

### 任务 7：长上下文工程 + Prompt Caching（PaiCLI 第 12 期）

**目标**：补齐 200K+ 长上下文模型适配，开启 Prompt Caching 降低成本。

**调研**：
- Anthropic `cache_control`：在 system prompt 最后一行加 breakpoint，后续相同 prompt 命中缓存
- OpenAI/DeepSeek automatic prefix cache：自动匹配，API 返回 `cached_tokens` 字段
- 成本模型：cached input 通常为原价的 10%

**子任务**：
- [ ] `llm/base.py` — `LLMBackend` 新增 `max_context_window` 和 `supports_prompt_caching` 属性
- [ ] `context/token_budget.py` — 新增 short / balanced / long 三种 `ContextProfile`
- [ ] `llm/anthropic_backend.py` — system prompt 末尾注入 cache_control breakpoint（已有部分）
- [ ] `llm/openai_backend.py` — 解析 usage 中的 `cached_tokens`
- [ ] `agent/core.py` — 每轮打印 token 用量 + 缓存命中统计
- [ ] 编写测试
- [ ] 评测：对比 cache ON vs OFF 的 token 消耗和延迟

**改动文件**：
- `llm/base.py`
- `context/token_budget.py`
- `llm/anthropic_backend.py`
- `llm/openai_backend.py`
- `agent/core.py`

---

## 🟢 Tier 2 — 架构重构 + 可维护性（预计 3-5 周）

---

### 任务 10：MCP 高级能力（PaiCLI 第 11 期）

**前置依赖**：MCP 协议核心（已完成）

**目标**：补齐 MCP resources、prompts 查看、被动通知、运行中取消。

**子任务**：
- [ ] resources 双轨：
  - 工具层：注册 `mcp__{server}__list_resources` / `mcp__{server}__read_resource` 虚拟工具
  - 用户 @-mention 层：`@server:protocol://path` 语法
- [ ] `/mcp prompts <server>` — 展示 server 暴露的 prompt 模板
- [ ] 被动通知处理：
  - `tools/list_changed` → 重拉工具列表 → 全量替换
  - `resources/list_changed` → cache 失效
  - **不做 health ping**
- [ ] 运行中取消：`/cancel` 在所有执行边界检查取消信号
- [ ] 编写测试

**改动文件**：
- `mcp/manager.py` — resources + prompts + 通知处理（需新建目录结构）
- `agent/core.py` — 取消信号检查
- `entry/chat.py` — `/cancel`、`/mcp resources`、`/mcp prompts` 命令

---

### 任务 11：Chrome DevTools MCP（PaiCLI 第 13 期）

**前置依赖**：MCP 框架（已完成）

**目标**：让 Agent 操控浏览器，处理需要 JS 渲染的页面。

**调研**：
- Google 官方 `chrome-devtools-mcp@latest`（Node.js，28 个工具）
- 与 forge-agent 的集成方式：通过 MCP stdio 协议驱动 Node.js server
- 需要用户本地安装 Chrome + Node.js

**子任务**：
- [ ] 对接 `chrome-devtools-mcp` 的 MCP 配置（`npx chrome-devtools-mcp@latest`）
- [ ] `image` content 处理：引导 LLM 优先用 `take_snapshot`（DOM 文本）而非 `take_screenshot`
- [ ] HITL server 维度全放行（对浏览器 MCP 只需确认一次）
- [ ] 初始化超时 30s→60s（首次启动 npx 拉包 + Chrome 冷启）
- [ ] system prompt 加「web_fetch vs 浏览器 MCP」决策表
- [ ] 端到端测试：验证 web_fetch 失败 → 自动 fallback 到浏览器
- [ ] 编写测试（mock MCP server）

**改动文件**：
- `mcp/manager.py` — server 维度 HITL、超时配置（需新建目录结构）
- `agent/prompt.py` — 浏览器决策表

---

### 任务 12：CDP 会话复用 + 登录态（PaiCLI 第 14 期）

**前置依赖**：任务 11（Chrome DevTools）

**目标**：复用带登录态的 Chrome 实例，访问需要认证的页面。

**子任务**：
- [ ] `/browser connect` — 切换到 `--autoConnect`，复用已有调试 Chrome
- [ ] `/browser status` / `/browser tabs` / `/browser disconnect`
- [ ] 登录态访问安全约束：敏感页面识别、改写型工具单步 HITL
- [ ] AuditLog 为浏览器工具追加 metadata
- [ ] 编写测试

**改动文件**：
- 新建 `tools/browser.py` — 浏览器会话管理
- `entry/chat.py` — `/browser` 命令组

---

### 任务 13：Skill 系统（PaiCLI 第 15 期）

**目标**：把工具选择策略打包成可复用「专家手册」。

**调研**：
- Skill = `SKILL.md`（YAML frontmatter + Markdown body）
- 加载方式：LLM 调用 `load_skill(name)` 工具时注入上下文
- Claude Code 的 skill 系统为参考

**子任务**：
- [ ] 新建 `skills/` 包 — loader、context buffer
- [ ] Skill 加载：三层目录扫描（内置 → `~/.forge-agent/skills/` → `.forge-agent/skills/`）
- [ ] `load_skill(name)` 工具：LLM 调用后把 SKILL.md 注入下一轮上下文
- [ ] `SkillContextBuffer`：一次性消费、最多保留 3 个 skill body
- [ ] 内置 `web-access` skill：浏览策略 + 工具选择表 + 站点经验
- [ ] CLI：`/skill list`、`/skill show <name>`、`/skill reload`
- [ ] 编写测试

**改动文件**：
- 新建 `skills/` 包
- `agent/core.py` — 注册 `load_skill` 工具
- `entry/chat.py` — `/skill` 命令

---

## 🔵 Tier 3 — 进阶能力（预计 5-7 周）

---

### 任务 15：Multi-Agent 协作（PaiCLI 第 5 期）

**目标**：多个 Agent 分工协作完成复杂任务。

**设计思路**（参考 README 中规划）：
- Coordinator（主力模型，全部工具）→ Explorer（轻量模型，只读）→ Coder（主力模型，读写）→ Reviewer（主力模型，只读）→ Tester（主力模型，Shell）
- 星型拓扑：子 Agent 只向 Coordinator 报告，互不通信
- 上下文隔离：每个子 Agent 独立 context window
- 与 `react` / `plan` 平级，通过 `/mode multi-agent` 切换

**子任务**：
- [ ] 新建 `agent/multi_agent.py` — SubAgent 数据模型 + 执行器
- [ ] 子 Agent 结果序列化（最终消息作为工具返回值）
- [ ] Coordinator 任务分解策略
- [ ] 结果汇总 + 冲突解决
- [ ] 注册为 `/mode multi-agent`
- [ ] 并行执行：多个子 Agent 并发（asyncio / threading）
- [ ] Git worktree 隔离（并行文件修改不冲突）
- [ ] Token 预算在子 Agent 间分配
- [ ] 编写测试

**改动文件**：
- 新建 `agent/multi_agent.py`
- `agent/prompt.py` — 新增角色 prompt 模板
- `entry/cli.py` — `--mode multi-agent`
- `entry/chat.py` — `/mode multi-agent`

---

### 任务 16：LSP 诊断注入（PaiCLI 第 17 期）

**目标**：Agent 改完代码后立即注入编译诊断。

**调研**：
- Python 生态：`pyright`（最活跃）、`ruff`（最快）、`mypy`（类型）
- 与现有 `PytestTool` 形成互补：LSP 提供实时诊断，pytest 提供运行时验证
- `pyright --outputjson` 解析诊断结果

**子任务**：
- [ ] 新建 `tools/lsp_tool.py` — `LspManager`，惰性启动 pyright
- [ ] LSP 子进程通信（stdio JSON-RPC）
- [ ] `LspHooks`：`file_write` 成功后 → `textDocument/didChange` → 收集 `publishDiagnostics`
- [ ] `flushPendingLspDiagnostics()`：每轮 LLM 请求前注入诊断作为合成 user message
- [ ] TUI 展示：诊断块红色(error)/黄色(warning) ANSI 渲染（已有 renderer 支持）
- [ ] 优雅降级：LSP 不可用时跳过，不阻塞主流程
- [ ] 编写测试

**改动文件**：
- 新建 `tools/lsp_tool.py`
- `agent/core.py` — post-edit hook

---

### 任务 17：Git 快照与回滚（PaiCLI 第 18 期）

**目标**：每个 turn 自动做 workspace 快照，可一键回滚。

**调研**：
- GitPython 或直接用 `git` CLI
- Side-git 仓库：`~/.forge-agent/snapshots/<hash>/.git`，与用户 `.git` 隔离
- 对标 DeepSeek TUI 的 `pre_turn_snapshot()` / `post_turn_snapshot()`

**子任务**：
- [ ] 新建 `tools/snapshot.py` — `SideGitManager`
  - `pre_turn_snapshot()` → commit `"pre-turn <turn_id>"`
  - `post_turn_snapshot()` → commit `"post-turn <turn_id>"`（异步）
- [ ] `revert_turn` 工具：LLM 可调用的回滚工具
- [ ] `/restore <N>` 命令：用户手动回滚到 N 个 turn 之前
- [ ] 快照策略：`max_snapshots=50`、`excludes=[.git/, node_modules/, __pycache__/]`
- [ ] 编写测试

**改动文件**：
- 新建 `tools/snapshot.py`
- `agent/core.py` — 在 step 循环插入 pre/post snapshot
- `entry/chat.py` — `/restore` 命令

---

## 🟣 Tier 4 — 产品化 + 高级特性（预计 5-7 周）

---

### 任务 18：Prompt 分层架构（PaiCLI 第 19 期）

**目标**：把硬编码 prompt 重构为 Markdown 分层文件。

**调研**：
- 参考 DeepSeek TUI `crates/tui/src/prompts/*.md`
- KV prefix cache 友好布局：稳定内容在前，volatile 在后
- 优先级：内置 → 用户级 `~/.forge-agent/prompts/` → 项目级 `.forge-agent/prompts/`

**子任务**：
- [ ] 新建 `prompts/` 目录：
  ```
  prompts/
    base.md              # 核心规则（工具使用、输出格式、安全约束）
    modes/
      agent.md           # ReAct 模式
      plan.md            # Plan 模式
    tools/               # 各工具使用规范
    safety.md            # 安全约束
  ```
- [ ] 新建 `agent/prompt_assembler.py` — 按序拼接，稳定在前
- [ ] `agent/prompt.py` — 改为调用 PromptAssembler
- [ ] 启动时校验：必含 `## Language` section
- [ ] 用户级覆盖支持
- [ ] 回归全部现有测试（677 条确保行为不变）

**改动文件**：
- 新建 `prompts/` 目录 + 各 `.md` 文件
- 新建 `agent/prompt_assembler.py`
- `agent/prompt.py` — 改为调用 assembler

---

### 任务 19：后台任务 + Runtime API（PaiCLI 第 20 期）

**目标**：支持后台任务队列和 HTTP/SSE Runtime API。

**调研**：
- 任务队列：SQLite 持久化（复用现有 EventLog 模式）
- HTTP 服务：`fastapi` + `uvicorn`（Python 标准方案）或内置 `http.server`
- API 对齐：OpenAI Assistants API 兼容端点

**子任务**：
- [ ] 新建 `runtime/task_manager.py` — `DurableTaskManager`
  - SQLite 任务队列，状态：`enqueued → running → completed/failed/canceled`
  - Worker Pool（可配并发数，默认 2）
  - `/task add`、`/task list`、`/task cancel <id>`、`/task log <id>`
  - 进程重启后未完成的任务自动重入队
- [ ] 新建 `runtime/api_server.py` — `RuntimeApiServer`
  - `POST /v1/threads` — 创建对话线程
  - `POST /v1/threads/{id}/turns` — 发起一轮 Agent 交互
  - `GET /v1/threads/{id}/events` — SSE 流式事件
  - 仅监听 `127.0.0.1`，API key 校验
- [ ] 新建 `runtime/thread_store.py` — thread 持久化 + 事件时间线
- [ ] 编写测试

**改动文件**：
- 新建 `runtime/` 包
- `entry/chat.py` — `/task` 命令
- `entry/cli.py` — `serve` 子命令

---

### 任务 20：图片输入（PaiCLI 第 21 期）

**目标**：支持图片输入，让多模态模型能"看到"截图和设计稿。

**调研**：
- OpenAI 兼容协议的 `content` array（`text` + `image_url` parts）
- Anthropic `content` blocks 也支持 `base64` 图片
- 图片压缩/缩放策略

**子任务**：
- [ ] `llm/base.py` — `LLMMessage` 新增 `ContentPart` 支持（text / image_base64 / image_url）
- [ ] `llm/openai_backend.py` — 含图片时构造 content array
- [ ] `llm/anthropic_backend.py` — 含图片时构造 image content block
- [ ] MCP image content 的 `data` / `mimeType` 回灌为图片消息
- [ ] 用户输入支持 `@image:file:///path/to/img.png`
- [ ] 图片压缩：短边 ≤ 768px，长边 ≤ 2000px
- [ ] HITL 弹窗展示图片元数据（尺寸 / 大小），不展示原图
- [ ] 编写测试

**改动文件**：
- `llm/base.py`
- `llm/openai_backend.py`
- `llm/anthropic_backend.py`
- `mcp/manager.py` — image content 回灌（需新建目录结构）

---

## 📐 评测体系设计

### 层级 1：功能回归测试（已有）

现有 `tests/` 目录 **677 passed, 7 skipped** 条用例。每次改动必跑。

### 层级 2：任务完成率评测（需新建）

| 评测集 | 规模 | 指标 | 用途 |
|--------|------|------|------|
| **mini-bench** | 20 个自建任务（简单/中等/困难 6-7 个） | resolved%、avg_steps、avg_tokens、avg_time | 快速迭代 < 30min |
| **SWE-bench Lite** | 300 个真实 GitHub issue | resolve rate（pass@1） | 对标社区 |
| **专项评测** | 按功能（Plan 10 / Web 10 / MCP 10 / ...） | 专项完成率 | 验证各期增量收益 |

### 层级 3：对比评测（Ablation）

每做完一期，用同一批任务跑"有该功能 vs 无该功能"的对比：
- 指标：完成率、平均步数、平均 token、平均耗时
- 结果存 JSON，生成图表展示各期的增量收益

### 评测基础设施（基于现有代码）

- 复用 `MockBackend` — 纯逻辑评测不花钱
- 复用 `EventLog` + `summarize_run()` — 提取统计数据（已有）
- 新建 `eval/runner.py` — 批量执行 + 收集结果
- 新建 `eval/report.py` — 生成 Markdown / HTML 报告

**改动文件**：
- 新建 `eval/` 包

---

## 🔥 forge-agent 独有优势（PaiCLI 路线图未涵盖）

| 特性 | 说明 |
|------|------|
| **Docker 沙箱** | PaiCLI 第 6 期明确拒绝做沙箱，forge-agent 已实现 |
| **三层记忆系统** | 文件型长期记忆 + SQLite 向量语义搜索 + 主动检索 |
| **Proactive 主动记忆** | 模式检测（修正/偏好/命令）自动触发记忆保存 |
| **Reflection 反思** | 测试失败 / 连续无编辑两种自动触发 |
| **死循环检测** | 连续 N 步相同 (tool, params) 自动 GAVE_UP |
| **LLM 重试 + 指数退避** | 网络可恢复，认证不可恢复 |
| **GitHub Issue → PR** | 完整流水线 |
| **EventLog JSONL** | 事件日志 + replay + summarize_run |
| **推理模型思考/回答分离** | reasoning_content + message 独立流式 |
| **SSRF 防护** | URL + DNS + 重定向三层验证 |

---

## 📊 工期估算

| Tier | 任务数 | 任务 | 预估 |
|------|--------|------|------|
| Tier 1（安全 + 上下文补齐） | 2 | HITL 审计/路径围栏 / 长上下文 + Caching | 3-5 周 |
| Tier 2（架构重构） | 4 | MCP 高级 / Chrome DevTools / CDP / Skill | 3-5 周 |
| Tier 3（进阶能力） | 3 | Multi-Agent / LSP / 快照 | 5-7 周 |
| Tier 4（产品化） | 3 | Prompt 分层 / 后台任务 / 图片输入 | 5-7 周 |
| 评测体系 | — | eval runner + report + mini-bench + 专项 | 2-3 周 |

**总计**：12 个待完成任务，约 **18-27 周**（4-6 个月，单人全职）

以上估算基于单人全职开发。并行可压缩时间。


---

## 🎯 明日开发计划（2026-06-16）

**核心主题**：AST 代码分块 + 多 Agent 系统 + MCP 高级能力 + Skill 系统

---

### 📦 一、AST 代码分块（AST-Aware Code Chunking for RAG）

#### 1.1 背景

当前 `memory/chunker.py` 只做纯文本层面的语义分块（按标题/段落/滑动窗口），对 **代码文件** 不感知函数/类/方法边界。现需要基于 tree-sitter AST 做代码分块，提升 RAG 对代码的检索精度。

#### 1.2 设计思路

```
代码文件 → tree-sitter 解析 → AST 遍历
                                ↓
                    ┌─ 函数定义（function_definition）
                    ├─ 类定义（class_definition）
                    ├─ 方法定义（method_definition）
                    └─ 文件级注释（module docstring）
                                ↓
                        按结构边界分块
                        每个 chunk = 一个函数/类/方法
                                ↓
                        关联元数据
                        (file_path, start_line, end_line, symbol_name, symbol_kind)
                                ↓
                        fastembed 向量化 → SQLite 向量索引
```

#### 1.3 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `context/code_chunker.py` | 新建 | AST 代码分块器，与现有 `memory/chunker.py` 互补 |
| `context/code_indexer.py` | 新建 | 代码向量索引，扫描仓库 + 分块 + embed + 存储 |
| `context/code_retriever.py` | 新建 | 代码语义检索（区别于记忆检索） |
| `context/repo_map.py` | 扩充 | 复用已有的 tree-sitter 解析基础设施 |
| `tools/rag_tool.py` | 新建 | `search_code` 工具，自然语言搜索代码 |
| `config/default.yaml` | 修改 | `code_index:` 配置段 |

#### 1.4 子任务清单

- [ ] **调研与设计**
  - [ ] 分析现有 `context/repo_map.py` 的 tree-sitter AST 解析策略
  - [ ] 分析现有 `memory/chunker.py` 的分块策略与 `memory/external_store.py` 的向量检索
  - [ ] 确定代码分块粒度：函数级 / 类级 / 文件级 三级回退策略
  - [ ] 确定 chunk 元数据 schema：`(file_path, start_line, end_line, symbol_name, symbol_kind, docstring)`

- [ ] **基础设施**
  - [ ] 新建 `context/code_chunker.py`
    - 复用 `repo_map.py` 的 `_LANG_REGISTRY` 和 tree-sitter 解析
    - 遍历 AST 提取函数定义（`function_definition`）/ 类定义（`class_definition`）/ 方法定义（`method_definition`）
    - 每种语言有对应的 AST 节点类型映射表
    - 无 tree-sitter 支持的语言：正则 fallback（按 `def / class / function / func / fn` 等关键字切分）
    - 顶层 docstring / module comment 作为独立 chunk
    - 输出：`list[CodeChunk]`，每个 chunk 包含源码段 + 元数据
  - [ ] 新建 `context/code_indexer.py`
    - `CodeIndexer.scan_and_index(repo_path)` — 扫描全仓库代码文件
    - 对每个源码文件调用 `code_chunker.chunk_file()` → chunk 列表
    - 批量 fastembed 向量化
    - 写入 SQLite `code_chunks` 表（独立于 `memory_chunks`）
    - 增量扫描：按文件 mtime 跳过未更改文件
    - `.gitignore`/`_SKIP_DIRS` 感知
    - 并发控制：`ThreadPoolExecutor` 并行解析多文件
  - [ ] 新建 `context/code_retriever.py`
    - `CodeRetriever.search(query, top_k)` — 自然语言搜索代码
    - 向量相似度检索 → 按文件路径分组 → 返回结构化的代码段
    - 结果附带文件名 + 行号范围 + 符号名，可被 LLM 直接用于 file_read
  - [ ] 新建 `tools/rag_tool.py` — `SearchCodeTool`（`search_code` 工具）
    - 参数：`query`（自然语言查询）、`file_pattern`（可选，限定文件类型）、`top_k`
    - 与现有 `search_text`（基于正则的 grep）互补：语义搜索 vs 模式匹配
    - 与现有 `memory_search`（检索记忆）互补：检索代码 vs 检索记忆
  - [ ] `config/default.yaml` — `code_index:` 配置段
    - `enabled`: true/false
    - `model_name`: embedding 模型名（默认复用 `external_memory` 的模型）
    - `max_chunk_lines`: 单个 chunk 最大行数
    - `min_chunk_lines`: 最小行数（小于此的不索引，如空函数）

- [ ] **集成**
  - [ ] `agent/core.py` — 在构建 system prompt 时注入代码检索结果（可选）
  - [ ] `agent/prompt.py` — system prompt 告知 Agent 何时用 `search_code` 工具
  - [ ] `entry/chat.py` — `/reindex` 命令触发全量重建

- [ ] **测试**
  - [ ] 编写 `test_code_chunker.py` — 多语言 AST 分块测试
  - [ ] 编写 `test_code_indexer.py` — 索引 + 增量扫描测试
  - [ ] 编写 `test_rag_tool.py` — `search_code` 工具测试（mock embedding）
  - [ ] 端到端测试：代码索引 → 自然语言搜索 → 命中率验证

#### 1.5 评测指标

| 指标 | 目标 | 对比 baseline |
|------|------|-------------|
| chunk 边界准确率 | ≥95%（AST 分块 vs 固定窗口） | 当前固定 1500 字符滑动窗口 |
| 语义检索 Top-5 命中率 | ≥80% | 纯 grep 正则搜索 |
| 全量索引耗时（10K 行项目） | ≤10s | 无索引时期 |

---

### 👥 二、多 Agent 协作系统（Multi-Agent）

#### 2.1 为什么需要多 Agent 系统

| 问题 | 单 Agent 局限 | 多 Agent 解决 |
|------|-------------|-------------|
| **上下文窗口争用** | 探索代码 + 编写代码 + 运行测试 共用同一窗口，相互干扰 | 每个角色独立 context window，互不污染 |
| **工具权限混杂** | 所有工具有相同访问权限，读/写/执行不分层 | 按角色隔离工具（Explorer 只读，Coder 读写，Tester 仅 Shell） |
| **无独立验证** | Agent 自己改代码自己看，容易遗漏缺陷 | Reviewer 独立审查，提供第三方视角 |
| **任务串行瓶颈** | 必须一个个文件依次修改 | Executor 可并行修改多个文件（worktree 隔离） |
| **恢复成本高** | 一个步骤失败可能污染整个上下文 | 失败子 Agent 可单独重试，不影响主上下文 |
| **认知过载** | 同时做"理解问题→设计方案→写代码→测试验证" | 每个 Agent 聚焦一个角色，prompt 更简洁，更容易做对 |

#### 2.2 多 Agent 通信机制

采用 **发布-订阅式 EventLog** 作为通信中枢，而非 Agent 间直接消息传递：

```
┌─────────────────────────────────────────────────┐
│                 EventLog (JSONL)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Plan创建  │ │ 文件修改  │ │ 测试结果  │  ...  │
│  └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────────────────────────┘
          ▲               ▲               ▲
          │ 写入           │ 写入           │ 写入
    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │ Planner   │   │ Executor  │   │ Reviewer  │
    │ (只读)     │   │ (读写)     │   │ (只读)     │
    └───────────┘   └───────────┘   └───────────┘
          │                               │
          └─────────── 读取 ──────────────┘
```

**通信规则**：
1. **单向数据流**：Planner → Executor → Reviewer，不反向
2. **无同步等待**：每个 Agent 独立运行，通过 EventLog 异步消费前序产出
3. **结果聚合**：Coordinator 读取 EventLog 汇总所有子 Agent 的结果
4. **序列化格式**：子 Agent 的最终消息（文本）作为 EventLog 事件内容，不需要结构化协议

#### 2.3 任务分发与调度

采用 **Coordinator 统一调度 + 多 Worker 并行执行** 模式：

**调度流程**：

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────────┐
│  Coordinator（主 Agent / 主力模型）               │
│  职责：分析任务 → 生成 SubTask DAG → 调度执行     │
│  工具权限：全部（用作调度器，不做具体编码）         │
└──────────────────────────────────────────────────┘
    │
    ├── → spawn Explorer（轻量模型，只读工具）
    │    ├── 搜索代码库，返回文件列表和结构
    │    └── 输出：文件路径列表 + 关键代码段
    │
    ├── → spawn Planner（主力模型，只读工具）
    │    ├── 基于探索结果，制定修改计划
    │    └── 输出：Markdown 计划文档
    │
    ├── → spawn Executor（主力模型，读写工具）
    │    ├── 按计划修改文件
    │    └── 输出：修改的 diff 列表
    │        ├── 可并行多个 Executor（不同文件 worktree 隔离）
    │
    ├── → spawn Reviewer（主力模型，只读工具）
    │    ├── 审查 diff + 运行测试
    │    ├── 输出：审查意见（approve / changes-requested / 问题列表）
    │    └── 可对每个 Executor 的输出独立审查
    │
    └── Coordinator 汇总 → 决定重试或完成 → 回复用户
```

**调度策略**：
- **串行依赖**：Explorer → Planner → Executor → Reviewer（天然依赖链）
- **并行执行**：多个 Executor 可并行（不同文件），多个 Reviewer 可并行（不同 diff）
- **失败重试**：子 Agent 失败时，Coordinator 可重新 spawn 并传递已有上下文
- **收敛判断**：Reviewer 不通过时，Coordinator 决定重试 或 上报用户

#### 2.4 冲突处理与一致性

| 冲突类型 | 问题 | 解决策略 |
|---------|------|---------|
| **文件并发修改** | 两个 Executor 同时修改同一个文件 | Git worktree 隔离：每个 Executor 在独立 worktree 中修改 |
| **修改顺序依赖** | Executor B 需要 Executor A 的输出 | Coordinator 识别依赖，串行调度有依赖的子任务 |
| **审查冲突** | Reviewer 发现问题但 Executor 不认同 | Coordinator 裁决：查看两边上下文，做最终决定 |
| **变量/函数重名** | 两个 Executor 引入同名符号 | Reviewer 层检测，Coordinator 协调重命名 |
| **token 竞争** | 多个子 Agent 的总 token 超预算 | Coordinator 分配预算，每轮检查剩余，不足时降级 |

**一致性保证**：
1. **Worktree 隔离**：并行 Executor 各自在 `git worktree add` 的独立目录中工作，互不干扰
2. **有序合并**：Coordinator 按 DAG 拓扑序逐一合并 worktree 到主分支
3. **测试门禁**：每个 Executor 的修改合并前必须通过测试
4. **快照回滚**：Executor 失败时丢弃对应 worktree，不污染主分支

#### 2.5 主 Agent 与子 Agent 职责划分

| 维度 | Coordinator（主 Agent） | SubAgent（子 Agent） |
|------|----------------------|--------------------|
| **角色** | 调度者 + 裁决者 + 汇总者 | 执行者（单一职责） |
| **模型** | 主力模型（如 DeepSeek/Claude） | Explorer 用轻量模型，其余用主力模型 |
| **工具权限** | 全部工具（用于调度决策） | 按角色绑定（Explorer 只读，Executor 读写等） |
| **上下文** | 完整对话历史 + 所有子 Agent 摘要 | 独立 context window，只看自己所需 |
| **运行方式** | 主循环驱动（现有 ReAct 循环） | Coordinator spawn 运行，结果序列化返回 |
| **token 预算** | 总预算的 30% | 总预算的 70%，在子 Agent 间分配 |
| **职责** | 任务分解、子 Agent 调度、结果裁决、用户沟通 | 具体执行（搜索/编码/审查/测试） |
| **异常处理** | 检测子 Agent 失败、触发重试、上报用户 | 正常执行，遇到错误自然返回 |

#### 2.6 上下文隔离策略

**问题**：如果不做隔离，子 Agent 的庞大探索输出会污染主 Agent 的 context window。

**隔离方案 — 三层隔离**：

```
层级 1: SubAgent 独立上下文
  ┌─────────────────────┐
  │ SubAgent            │  ← 独立的 ConversationHistory
  │  prompt: 角色定义    │  ← 独立的 system prompt
  │  tools: 角色绑定     │  ← 独立的工具集
  │  history: 仅自己轮次 │  ← 不共享主 Agent 的历史
  └─────────────────────┘
  ↑ 每个 spawn 创建全新的上下文，子 Agent 退出后释放

层级 2: 结果摘要化
  子 Agent 的完整对话 → 提取摘要（关键发现/修改/结果）
  → 只有摘要被回传给 Coordinator（非原始对话）
  → 摘要格式：
    ## SubAgent: Explorer
    - 发现文件: src/api.py, src/models.py
    - 关键结构: ApiClient 类，login() 方法在 api.py:42
    - 建议: 修改 login() 增加重试逻辑

层级 3: Token 预算隔离
  Coordinator: 总预算 × 30%（用于调度 + 汇总 + 裁决）
  SubAgents:   总预算 × 70% / N（每个子 Agent 分得等额预算）
  超预算的子 Agent 被强制结束，返回已有结果
  连续超预算 → Coordinator 降级调度策略（减少并行数 / 用轻量模型）
```

**上下文压缩策略**：
- 子 Agent 结束后，调用 `ConversationCompactor` 压缩其对话历史为摘要
- Coordinator 只接收压缩后的摘要，不接收原始对话
- 摘要保留文件路径、函数名、错误信息等精确信息

#### 2.7 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/multi_agent.py` | 新建 | SubAgent 数据模型 + 执行器 + Coordinator |
| `agent/prompt.py` | 修改 | 新增 Coordinator / Explorer / Reviewer prompt |
| `agent/core.py` | 修改 | Agent 支持 mode 切换 + SubAgent 注册 |
| `agent/factory.py` | 修改 | `create_agent()` 支持 `--mode multi-agent` |
| `entry/cli.py` | 修改 | `--mode multi-agent` 参数 |
| `entry/chat.py` | 修改 | `/mode multi-agent` 命令 |
| `tools/snapshot.py` | 新建 | Worktree 创建/合并/丢弃管理（依赖） |
| `config/default.yaml` | 修改 | `multi_agent:` 配置段 |

#### 2.8 子任务清单

- [ ] **Phase 1 — SubAgent 基础设施**
  - [ ] 调研 Claude Code SubAgent 设计模式
  - [ ] `agent/multi_agent.py` — `SubAgentConfig` 数据模型
    - `role: str` — `explorer / planner / executor / reviewer / tester`
    - `model: str | None` — 可选模型覆盖
    - `tool_names: list[str]` — 允许的工具列表
    - `max_steps: int`
    - `budget_tokens: int`
    - `isolation: str | None` — `"worktree"` 或 None
  - [ ] `agent/multi_agent.py` — `SubAgentExecutor`
    - `spawn(config, task) → SubAgentResult` — 创建 ReActAgent 实例
    - 传递独立的 ConversationHistory + ToolRegistry（过滤版）
    - 注入角色特定的 system prompt
    - 结果序列化：`run_result.summary` → 摘要文本
    - 超时保护：超预算时强行结束
  - [ ] `agent/multi_agent.py` — `SubAgentResult`
    - `role, summary, files_changed, test_results, error`
    - `conversation_path` — 完整对话日志（供 debug）
    - `summary` — 压缩后的摘要

- [ ] **Phase 2 — Coordinator Agent**
  - [ ] `agent/multi_agent.py` — `CoordinatorAgent`
    - 继承或组合 `ReActAgent`
    - 注册 `spawn_agent` 工具（供 LLM 调用）
    - 注册 `list_agent_results` 工具
    - 注册 `finish` 工具
    - System prompt：协调者角色定义 + 决策策略
  - [ ] `agent/prompt.py` — 新增 prompt 模板
    - `COORDINATOR_SYSTEM_PROMPT` — 协调者行为定义
    - `EXPLORER_PROMPT` — 搜索者 prompt（轻量、只读、输出文件列表）
    - `PLANNER_PROMPT` — 规划者 prompt（输出 Markdown 计划）
    - `EXECUTOR_PROMPT` — 执行者 prompt（按计划修改）
    - `REVIEWER_PROMPT` — 审查者 prompt（检查 diff + 测试）
  - [ ] 任务分发逻辑
    - `spawn_agent(role, task, depends_on)` 工具实现
    - 依赖跟踪：`depends_on` 列表维护 DAG
    - Coordinator 等待依赖完成后再 spawn 下游
  - [ ] 结果汇总逻辑
    - `list_agent_results(role=None)` — 按角色过滤
    - 汇总所有结果 → 最终回复
  - [ ] 裁决逻辑
    - Reviewer 发现问题 → Coordinator 判断重试或上报
    - 重试次数上限（默认 2 次）

- [ ] **Phase 3 — 并行执行**
  - [ ] `tools/snapshot.py` — `WorktreeManager`
    - `create_worktree(branch_name)` → worktree 路径
    - `merge_worktree(worktree_path, target_branch)` → git merge
    - `discard_worktree(worktree_path)` → 清理
    - HITL：合并前展示 diff，需用户确认
  - [ ] `agent/multi_agent.py` — 并行 Executor
    - 多个 `spawn_agent('executor', ...)` 并行执行
    - 每个 Executor 分配独立 worktree
    - 所有 Executor 完成 → 依次合并 worktree
    - 合并冲突 → Coordinator 裁决
  - [ ] Token 预算分配
    - `distribute_budget(agents, total_budget)` — 等额分配 + 预留 Coordinator
    - 超预算 Agent 强制结束，返回已有结果

- [ ] **Phase 4 — 集成**
  - [ ] `agent/factory.py` — `create_agent('multi-agent', ...)` 分支
  - [ ] `entry/cli.py` — `--mode multi-agent`
  - [ ] `entry/chat.py` — `/mode multi-agent` 切换
  - [ ] `config/default.yaml` — `multi_agent:` 配置段
    - `default_mode: "sequential"`（sequential / parallel）
    - `max_parallel_executors: 3`
    - `worker_model: null`（轻量模型覆盖）
    - `review_required: true`
    - `max_retries: 2`

- [ ] **测试**
  - [ ] `test_multi_agent.py` — SubAgent spawn + 结果获取测试
  - [ ] `test_coordinator.py` — Coordinator 调度逻辑测试
  - [ ] `test_worktree_manager.py` — worktree 创建/合并/丢弃测试
  - [ ] 端到端测试：多 Agent 修复一个已知问题的完整流程

---

### 🔌 三、MCP 高级能力

#### 3.1 背景

当前 `tools/mcp_client.py` 已完成 MCP 协议核心（stdio 连接、工具发现、工具调用代理），但缺少：
- Resources 支持（`resources/list` + `resources/read`）
- Prompts 展示（`prompts/list` + `prompts/get`）
- 被动通知处理（`tools/list_changed` 等）
- 运行中取消（`/cancel`）

#### 3.2 设计思路

```
MCPClientManager 扩展
  ├── tools/list → 现有工具发现
  ├── tools/call → 现有工具执行
  ├── resources/list → 新增：列出 Server 暴露的资源
  ├── resources/read → 新增：读取资源内容
  ├── prompts/list → 新增：列出 Prompt 模板
  ├── prompts/get → 新增：获取 prompt 模板 + 渲染
  └── 通知处理 → 新增：tools/list_changed / resources/list_changed
```

#### 3.3 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `mcp/manager.py` | 新建 | 从 `tools/mcp_client.py` 抽取 `manager.py` 到独立包 |
| `mcp/client.py` | 新建 | 底层 JSON-RPC 客户端 |
| `mcp/transport.py` | 新建 | stdio / streamable HTTP 传输抽象 |
| `mcp/__init__.py` | 新建 | 包初始化 |
| `tools/mcp_client.py` | 重构 | 改为导入 `mcp/` 包的轻量 wrapper |

#### 3.4 子任务清单

- [ ] **基础设施**
  - [ ] 新建 `mcp/` 包目录结构（`__init__.py`, `client.py`, `transport.py`, `manager.py`）
  - [ ] `mcp/transport.py`
    - `BaseTransport` 抽象接口
    - `StdioTransport`（从现有 `mcp_client.py` 抽取）
    - `StreamableHttpTransport`（预留，SSE 流式响应）
  - [ ] `mcp/client.py`
    - `JsonRpcClient`：JSON-RPC 2.0 全实现
    - 请求-响应配对（request id 匹配）
    - 通知（无 id 的消息）
    - 错误码处理（`-32700` Parse Error, `-32601` Method Not Found 等）
    - 超时控制（可配，默认 30s）

- [ ] **Resources 支持**
  - [ ] `mcp/manager.py` — `list_resources(server_name)` 方法
  - [ ] `mcp/manager.py` — `read_resource(server_name, uri)` 方法
  - [ ] 工具层注册：`mcp__{server}__list_resources` / `mcp__{server}__read_resource` 虚拟工具
  - [ ] 用户 @-mention 层：`@server://protocol/path` 语法（可选）

- [ ] **Prompts 支持**
  - [ ] `mcp/manager.py` — `list_prompts(server_name)` 方法
  - [ ] `mcp/manager.py` — `get_prompt(server_name, name, args)` 方法
  - [ ] CLI：`/mcp prompts <server>` 命令

- [ ] **通知处理**
  - [ ] `mcp/manager.py` — 注册 notification handlers
  - [ ] `notifications/tools/list_changed` → 重拉工具列表 → 全量替换
  - [ ] `notifications/resources/list_changed` → 清除 resources cache
  - [ ] 通知循环：后台线程监听 server 的 notification stream
  - [ ] 不做 health ping（Server 不需要主动确认存活）

- [ ] **运行中取消**
  - [ ] `agent/core.py` — 在每个 tool execute 边界检查取消信号
  - [ ] `entry/chat.py` — `/cancel` 命令实现
  - [ ] MCP 层面：`notifications/cancelled` 通知

- [ ] **配置与集成**
  - [ ] `config/default.yaml` — `mcp:` 配置段合并
  - [ ] `tools/mcp_client.py` — 重构为 `mcp/` 包的轻量 wrapper，保持向后兼容
  - [ ] `entry/chat.py` — `/mcp`、`/mcp restart <name>`、`/mcp disable/enable <name>` 命令

- [ ] **测试**
  - [ ] `tests/test_mcp_transport.py` — transport 通信测试
  - [ ] `tests/test_mcp_manager.py` — resources/prompts/notifications 测试（mock server）

---

### 📘 四、Skill 系统

#### 4.1 设计思路

Skill = `SKILL.md`（YAML frontmatter + Markdown body），把工具选择策略打包成可复用的「专家手册」。

```
Skill 文件格式：
---
name: web-access
description: Web browsing and search strategies
tools: [web_search, web_fetch]
---

## When to use web tools
- Use web_search for API docs, error messages, libraries
- Use web_fetch after search to read specific pages
...

加载方式：
LLM 调用 load_skill("web-access")
  → 系统从磁盘读取 web-access/SKILL.md
  → 注入下一轮 LLM 上下文
  → 一次性消费，最多保留 3 个 skill body 同时生效
```

#### 4.2 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `skills/` | 新建 | 包目录 |
| `skills/__init__.py` | 新建 | 包初始化 |
| `skills/loader.py` | 新建 | 三层目录扫描 + SKILL.md 解析 |
| `skills/web-access/SKILL.md` | 新建 | 内置 skill 示例 |
| `tools/skill_tool.py` | 新建 | `load_skill` / `list_skills` / `unload_skill` 工具 |
| `agent/core.py` | 修改 | 注册 skill 工具 |
| `entry/chat.py` | 修改 | `/skill list`, `/skill show`, `/skill reload` |

#### 4.3 子任务清单

- [ ] **基础设施**
  - [ ] 新建 `skills/` 包（`__init__.py`, `loader.py`）
  - [ ] `skills/loader.py` — `SkillLoader`
    - 三层目录扫描优先顺序：内置 `skills/` → `~/.forge-agent/skills/` → `.forge-agent/skills/`
    - SKILL.md 解析：YAML frontmatter（name, description, tools）+ Markdown body
    - 校验：必含 name + description，可选 tools 列表
    - 缓存已加载的 skill 内容（进程级 LRU cache）
  - [ ] `SkillContextBuffer`
    - 最多保留 3 个 skill body 同时生效
    - 一次性消费：LLM 使用后标记为已消费，下一轮不再自动注入
    - FIFO 淘汰：超过 3 个时丢弃最旧的

- [ ] **工具注册**
  - [ ] 新建 `tools/skill_tool.py`
    - `LoadSkillTool`（`load_skill`）
      - 参数：`name`（skill 名称）
      - 读取 SKILL.md → 注入 `SkillContextBuffer`
      - 返回 skill 的 description + 可用工具列表
    - `ListSkillsTool`（`list_skills`）
      - 参数：无
      - 列出所有可用 skill 的 name + description
    - `UnloadSkillTool`（`unload_skill`）
      - 参数：`name`
      - 从 `SkillContextBuffer` 移除
  - [ ] `agent/prompt.py` — system prompt 加一段 skill 使用指引

- [ ] **内置 Skill**
  - [ ] `skills/web-access/SKILL.md` — Web 访问策略 skill
    - web_search vs web_fetch 选择
    - 常见网站的经验（如 GitHub API、PyPI、MDN）
    - SSRF 安全提醒
    - 站点行为模式（如 Stack Overflow 可能屏蔽自动化）
  - [ ] 预留后续 skill 模板目录结构

- [ ] **CLI 集成**
  - [ ] `entry/chat.py` — `/skill list`、`/skill show <name>`、`/skill reload`
  - [ ] `/skill reload` — 清空全部缓存，重新扫描磁盘

- [ ] **与 Context 集成**
  - [ ] `context/history.py` — 在 `build_messages()` 中插入 skill context
  - [ ] `agent/core.py` — 注册 `load_skill` / `list_skills` / `unload_skill` 工具

- [ ] **测试**
  - [ ] `tests/test_skill_loader.py` — 三层目录扫描 + frontmatter 解析
  - [ ] `tests/test_skill_buffer.py` — SkillContextBuffer FIFO 淘汰
  - [ ] `tests/test_skill_tool.py` — load/list/unload 工具测试

---

### 📋 明日任务优先级

```
高优先级（必须完成）：
  P0 ─ AST 代码分块 + 向量索引（context/code_chunker.py + code_indexer.py）
  P0 ─ Multi-Agent Phase 1 SubAgent 基础设施（agent/multi_agent.py）

中优先级（按时间）：
  P1 ─ Multi-Agent Phase 2 Coordinator（agent/multi_agent.py）
  P1 ─ Skill 系统基础（skills/loader.py + tools/skill_tool.py）

低优先级（有时间再做）：
  P2 ─ MCP 高级能力（mcp/ 包重构 + resources + prompts）
  P2 ─ Multi-Agent Phase 3 并行执行
```

---

📋 功能实现核对总表
#	功能点	状态	实现情况
1	Plan模式 + DAG 任务拆解	✅ 已实现	`agent/plan.py` — PlanExecuteAgent + DAG 调度
2	/plan 命令	✅ 已实现	`/mode plan` 切换，复杂任务自动拆解
3	依赖与执行顺序展示	✅ 已实现	DAG 拓扑排序 + TaskDAG 依赖管理
4	简单任务自动最小计划	✅ 已实现	_is_complex_task() 启发式判断
5	短/长期记忆 + 相关检索	✅ 已实现	三层记忆系统 + 向量语义检索 + 主动召回
6	摘要压缩 + Token 预算	✅ 已实现	TokenBudget + ConversationCompactor（LLM + regex）
7	动态预算 + Prompt Cache + 成本	🟡 部分	静态预算已完成，Cache 部分底层支持但成本可见化缺失
8	/memory 与 /save 命令	✅ 已实现	`memory_read`/`write`/`list`/`delete` 工具 + 主动记忆
9	多模型支持 + 运行时切换	✅ 已实现	5 Provider + `/model` 运行时切换 + `.env` 配置
10	联网搜索 + 网页抓取	✅ 已实现	`WebSearchTool`(DuckDuckGo) + `WebFetchTool`(readability) + SSRF
11	MCP 协议支持	✅ 已实现	`tools/mcp_client.py` — stdio JSON-RPC + 自动工具注册
12	TUI 渲染器	✅ 已实现	InlineRenderer（状态栏/伸缩面板/diff 高亮/诊断着色）+ PlainRenderer
13	并行工具执行	✅ 已实现	原生 multi-tool-call 支持
14	Multi-Agent 协作	❌ 未实现	README 已设计架构，未编码
15	Chrome DevTools 集成	❌ 未实现	待通过 MCP 对接
16	Git 快照回滚	❌ 未实现	待实现 SideGitManager
17	LSP 诊断注入	❌ 未实现	待实现 LspManager
18	Skill 系统	❌ 未实现	待实现 skill loader + buffer
19	Prompt 分层	❌ 未实现	待拆分 prompts/ 目录
20	后台任务 + Runtime API	❌ 未实现	待实现 runtime/ 包
21	图片输入	❌ 未实现	待实现 ContentPart + 多模态支持
22	AST 代码分块（RAG）	❌ 未实现	待实现 context/code_chunker.py
23	Multi-Agent 系统	❌ 未实现	待实现 agent/multi_agent.py
24	MCP 高级能力	❌ 未实现	待重构 mcp/ 独立包
25	Skill 系统	❌ 未实现	待实现 skills/ 包
