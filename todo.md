# forge-agent 开发任务清单

对照 PaiCLI 第 1-21 期路线图，逐期分析 forge-agent 的完成度与后续任务。

---

## 逐期对照总览

| 期数 | PaiCLI 主题 | forge-agent 状态 | 对应任务 |
|------|------------|------------------|---------|
| 1 | 基础 ReAct + Tool Call | ✅ 完成 | — |
| 2 | Plan-and-Execute | ❌ 未开始 | 任务 1 |
| 3 | Memory + 上下文工程 | 🟡 部分 | 任务 3 |
| 4 | RAG + 代码库理解 | 🟡 部分 | 任务 4 |
| 5 | Multi-Agent 协作 | ❌ 未开始 | 任务 15 |
| 6 | HITL + 审批流 | 🟡 部分 | 任务 5 |
| 7 | 异步 + 并行工具 | ❌ 未开始 | 任务 14 |
| 8 | 多模型适配 + 运行时切换 | 🟡 部分 | 任务 6 |
| 9 | 联网能力 + Web 工具 | ❌ 未开始 | 任务 2 |
| 10 | MCP 协议核心 | ❌ 未开始 | 任务 9 |
| 11 | MCP 高级能力 | ❌ 未开始 | 任务 10 |
| 12 | 长上下文工程 + Prompt Caching | 🟡 部分 | 任务 7 |
| 13 | Chrome DevTools MCP | ❌ 未开始 | 任务 11 |
| 14 | CDP 会话复用 + 登录态 | ❌ 未开始 | 任务 12 |
| 15 | Skill 系统 | ❌ 未开始 | 任务 13 |
| 16 | TUI 界面 + 产品化 | 🟡 部分 | 任务 8 |
| 17 | LSP 诊断注入 | ❌ 未开始 | 任务 16 |
| 18 | Git Side-History 快照回滚 | ❌ 未开始 | 任务 17 |
| 19 | Prompt 分层架构 | ❌ 未开始 | 任务 18 |
| 20 | 后台任务 + Runtime API | ❌ 未开始 | 任务 19 |
| 21 | 图片复制粘贴输入 | ❌ 未开始 | 任务 20 |

---

## 🟡 已部分完成 — 需补齐的缺口

以下各期 forge-agent 已有基础能力，但未完全覆盖 PaiCLI 对应期的全部功能。

### 第 3 期缺口：Memory 系统

**已有**：
- `ConversationHistory` — 滑动窗口、首条不丢弃
- `TokenBudget` — tiktoken 精确计数 + 字符 fallback、各部分配额分配
- 历史裁剪：`trim_history()` 保留首条 + 最近消息

**缺失**：
- 长期记忆持久化（记忆存储到磁盘）
- 上下文自动摘要压缩（对话过长时生成摘要而非简单丢弃）
- 记忆检索（基于相似度匹配关键历史信息召回）

### 第 4 期缺口：RAG 检索

**已有**：
- `RepoMap` — tree-sitter AST 提取函数/类/方法定义，9 种语言支持 + 正则 fallback
- RepoMap 是 Aider 风格的"轻量 RAG"——不需要 embedding，直接用 AST 做结构摘要

**缺失**：
- 代码向量化（Embedding），支持本地 Ollama 和远程 API
- 向量数据库（本地持久化 + 余弦相似度检索）
- 代码分块策略（文件 / 类 / 方法粒度）
- 自然语言语义搜索代码（区别于正则 grep）

### 第 6 期缺口：HITL 审批流

**已有**：
- Shell 四层安全（黑名单硬拦截 → 白名单免确认 → confirm_callback 确认 → 输出截断）
- `terminal_confirm()` 交互式确认
- `always_allow()` / `always_deny()` 可注入回调
- Docker 沙箱（`DockerRuntime`：懒启动 + 网络隔离 + bind mount）

**缺失**：
- 操作审计日志（`AuditLog`）：危险工具调用按天写 JSONL
- 路径围栏（`PathGuard`）：file_read / file_write 限制在项目根目录内
- `write_file` 单文件大小上限
- CLI `/policy` 查看安全策略状态

### 第 8 期缺口：多模型运行时切换

**已有**：
- `router.py` — 5 个 Provider（Anthropic / OpenAI / DeepSeek / Groq / Ollama）
- `OpenAICompatBackend` — 覆盖 4 种 OpenAI 兼容 API
- `create_backend_from_config()` — 从 YAML 配置创建后端

**缺失**：
- 运行时 `/model` 切换命令（当前只能启动时指定）
- 配置持久化（切换后的模型选择保存到配置文件）
- `LlmClient` 接口级公共类型（当前各后端独立定义）

### 第 12 期缺口：长上下文工程

**已有**：
- `TokenBudget` — 静态 80K 总量、各部分固定比例
- 历史裁剪机制

**缺失**：
- 模型能力声明（`maxContextWindow` / `supportsPromptCaching`）
- 按模型动态计算预算（默认 `80% × maxContextWindow`）
- Short / Balanced / Long 三种上下文模式
- Prompt Caching 接入（Anthropic `cache_control`、OpenAI/DeepSeek automatic prefix cache）
- 上下文成本可见化（每轮展示 token 用量 + 缓存节省比例）
- 检索策略自适应（长窗口提高 topK）

### 第 16 期缺口：TUI 产品化

**已有**：
- CLI 彩色输出（ANSI escape codes）
- 流式 thought（dim）/ message（bright）分离打印
- 实时 event 打印（`_print_event_live`）
- Chat 模式持久化会话

**缺失**：
- 正式 TUI 框架（`rich` 已在依赖中但未用）
- 文件树浏览
- 代码 diff 高亮
- 对话历史可视化
- 底部状态栏（模型名 / token 用量 / 耗时）
- 工具调用可折叠面板
- `Renderer` 接口抽象（inline / plain 多形态）

---

## 🔴 Tier 1 — 基础能力补齐（预计 5-7 周）

---

### 任务 1：Plan-and-Execute 模式（PaiCLI 第 2 期）

**目标**：让 Agent 能处理复杂多步任务，先规划后执行。

**调研**：

| 方案 | 说明 | 改动量 |
|------|------|--------|
| 方案 A（轻量） | system prompt 里加"先列出步骤再执行"，不改主循环 | < 50 行 |
| 方案 B（完整） | 新 `PlanExecuteAgent`，生成 TaskDAG，拓扑执行，失败重规划 | ~500 行 |

**推荐**：先 A 后 B。方案 A 一周验证效果，方案 B 复用现有 `Agent` 作为执行器。

**子任务**：
- [ ] 调研 Plan-and-Solve 论文 [Plan-and-Solve Prompting](https://arxiv.org/abs/2305.04091)
- [ ] 调研 Aider `/architect` 模式的 prompt 设计
- [ ] 方案 A：`agent/prompt.py` 新增 `_PLAN_MODE_TEMPLATE`
- [ ] 方案 B：新建 `agent/plan_execute.py`（TaskDAG + 依赖管理 + 重规划）
- [ ] 方案 B：`agent/core.py` 可选切换到 plan 模式
- [ ] 编写对应测试（MockBackend 模拟多步计划执行）
- [ ] 评测：SWE-bench Lite（300 题）对比 Plan vs ReAct 的 resolve rate

**改动文件**：
- `agent/prompt.py` — 新增 plan 模式 system prompt
- `agent/core.py` — 可选注入 plan prompt
- 新建 `agent/plan_execute.py`（方案 B）

---

### 任务 2：联网能力（PaiCLI 第 9 期）

**目标**：让 Agent 能访问互联网获取实时信息。

**调研**：

| 工具 | 方案 | 优劣 |
|------|------|------|
| web_search | DuckDuckGo (`duckduckgo_search`) | 免费、零配置，适合开发阶段 |
| web_search | SerpAPI | 付费但稳定，生产可用 |
| web_search | SearXNG 自部署 | 免费可控，需运维 |
| web_fetch | `requests` + `BeautifulSoup` + `readability-lxml` | 经典组合，正文提取效果好 |

**推荐**：DuckDuckGo + readability-lxml，零成本启动。

**子任务**：
- [ ] 调研 DuckDuckGo API 速率限制与使用条款
- [ ] 调研 `readability-lxml` 正文提取算法
- [ ] 新建 `tools/web_tool.py` — `WebSearchTool` + `WebFetchTool`
- [ ] URL 白名单/黑名单（仅允许 http/https，拦截 `file://`、内网 IP）
- [ ] 响应体大小限制（默认 100KB）
- [ ] 搜索结果 LLM 二次摘要（可选）
- [ ] `agent/prompt.py` system prompt 告知 Agent 何时用联网工具
- [ ] `config/default.yaml` 新增 web 配置段
- [ ] 编写测试（mock HTTP 响应）
- [ ] 评测：10 个需要联网的任务，验证准确率

**改动文件**：
- 新建 `tools/web_tool.py`
- `agent/prompt.py` — 联网工具选择指引
- `config/default.yaml` — `web:` 配置段

---

### 任务 3：Memory 系统补齐（PaiCLI 第 3 期）

**目标**：补齐长期记忆和上下文摘要能力。

**调研**：
- 长期记忆持久化：SQLite 存储 key-value（任务 → 关键发现），启动时加载
- 上下文摘要：对话超窗口时，用 LLM 生成摘要而非直接丢弃历史
- 记忆检索（可选）：用 sentence-transformers 做 embedding + 余弦相似度召回

**子任务**：
- [ ] 调研 Map-Reduce 摘要算法（Aider 的 summarization 策略）
- [ ] `context/history.py` 新增 `summarize_and_compress()` — 历史过长时 LLM 生成摘要
- [ ] 新建 `context/long_term_memory.py` — SQLite 持久化 + 关键信息存取
- [ ] `agent/core.py` 在每轮结束时把关键发现写入长期记忆
- [ ] 编写测试
- [ ] 评测：20 轮长对话后的上下文相关性保持率

**改动文件**：
- `context/history.py` — 摘要生成
- 新建 `context/long_term_memory.py`
- `agent/core.py` — 长期记忆读写 hook

---

### 任务 4：RAG 检索系统（PaiCLI 第 4 期）

**目标**：在 RepoMap 的基础上增加语义搜索能力。

> **注意**：第 4 期与 RepoMap 是互补关系，不是替代。RepoMap 提供结构概览（"有哪些文件和类"），RAG 提供语义搜索（"跟用户问题最相关的代码片段是什么"）。

**调研**：
- Embedding 模型：Ollama `nomic-embed-text`（免费本地）或 OpenAI `text-embedding-3-small`（廉价远程）
- 向量存储：`chromadb` 最轻量，或直接用 numpy + 内存余弦检索
- 代码分块：按函数/类边界切分（复用 RepoMap 的 tree-sitter 解析结果）
- 已有基础设施：`RepoMap` 已经扫描了所有源码文件并提取了符号

**子任务**：
- [ ] 调研 `chromadb` 与内存余弦检索的性能差异
- [ ] 调研代码分块策略（AST-aware chunking vs 固定窗口）
- [ ] 新建 `context/code_index.py` — 代码索引（分块 + 向量化 + 存储）
- [ ] 新建 `tools/rag_tool.py` — `search_code` 工具（自然语言搜代码）
- [ ] 支持本地 Ollama 和远程 API 两种 Embedding 源
- [ ] 代码关系图谱（类/方法依赖关系，可选）
- [ ] 编写测试
- [ ] 评测：对比 RAG vs 纯 grep 搜索的定位准确率

**改动文件**：
- 新建 `context/code_index.py`
- 新建 `tools/rag_tool.py`
- `config/default.yaml` — `rag:` 配置段

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

### 任务 6：运行时模型切换（PaiCLI 第 8 期缺口）

**目标**：支持 Chat 模式下 `/model` 运行时切换。

**子任务**：
- [ ] `agent/core.py` — Agent 支持运行时更换 backend
- [ ] `entry/chat.py` — ChatSession 新增 `/model <name>` 命令
- [ ] 配置持久化：切换后的模型保存到 `~/.forge-agent/config.json`
- [ ] 编写测试

**改动文件**：
- `agent/core.py` — `swap_backend()` 方法
- `entry/chat.py` — `/model` 命令
- `config/schema.py` — 用户级配置文件读写

---

## 🟡 Tier 2 — 上下文 + 工具 + 展示（预计 4-6 周）

---

### 任务 7：长上下文工程 + Prompt Caching（PaiCLI 第 12 期）

**目标**：适配 200K+ 长上下文模型，开启 Prompt Caching 降低成本。

**调研**：
- Anthropic `cache_control`：在 system prompt 最后一行加 breakpoint，后续相同 prompt 命中缓存
- OpenAI/DeepSeek automatic prefix cache：自动匹配，API 返回 `cached_tokens` 字段
- 成本模型：cached input 通常为原价的 10%

**子任务**：
- [ ] `llm/base.py` — `LLMBackend` 新增 `max_context_window` 和 `supports_prompt_caching` 属性
- [ ] `context/token_budget.py` — 动态预算（`0.8 × maxContextWindow`）
- [ ] `context/token_budget.py` — 新增 short / balanced / long 三种 `ContextProfile`
- [ ] `llm/anthropic_backend.py` — system prompt 末尾注入 cache_control breakpoint
- [ ] `llm/openai_compat.py` — 解析 usage 中的 `cached_tokens`
- [ ] `agent/core.py` — 每轮打印 token 用量 + 缓存命中统计
- [ ] 编写测试
- [ ] 评测：对比 cache ON vs OFF 的 token 消耗和延迟

**改动文件**：
- `llm/base.py`
- `context/token_budget.py`
- `llm/anthropic_backend.py`
- `llm/openai_compat.py`
- `agent/core.py`

---

### 任务 8：TUI 内联流式界面（PaiCLI 第 16 期）

**目标**：从 CLI 到 Claude Code 风格的内联流式 TUI。

**调研**：
- `rich` 库（已在 `pyproject.toml`）— 支持 Live、Panel、Syntax、Layout
- DECSTBM 状态栏：终端底部固定一行显示模型/token/耗时
- Claude Code 参考：主屏直出 + 底部状态栏 + 可折叠工具块

**子任务**：
- [ ] 新建 `entry/renderer.py` — `Renderer` 接口 + `InlineRenderer` + `PlainRenderer`
- [ ] `InlineRenderer` 实现：
  - 底部状态栏（模型名、token 用量、耗时、步数）
  - 工具调用黄色可折叠面板（`ctrl+o` 展开/折叠）
  - diff 语法高亮
  - 诊断块红/黄 ANSI 渲染
- [ ] `PlainRenderer` 兜底（非终端环境降级）
- [ ] `entry/chat.py` — ChatSession 使用 Renderer
- [ ] `entry/cli.py` — `--renderer inline|plain` 参数
- [ ] 对话历史可视化（`~/.forge-agent/history/` 目录查看）
- [ ] 编写测试
- [ ] 评测：人工体验评估（UX checklist）

**改动文件**：
- 新建 `entry/renderer.py`
- `entry/chat.py` — 接入 Renderer
- `entry/cli.py` — `--renderer` 参数

---

## 🟢 Tier 3 — 架构重构 + 可维护性（预计 3-5 周）

---

### 任务 9：MCP 协议核心（PaiCLI 第 10 期）

**目标**：让 forge-agent 接入 MCP 生态，第三方工具自动注册。

**调研**：
- MCP 2024-11-05 规范：stdio（子进程）+ Streamable HTTP（2025 年 3 月新规范）
- `pymcp` / `mcp` Python SDK — 是否有现成可用？
- Claude Code 兼容：配置格式与 `claude_desktop_config.json` 一致

**子任务**：
- [ ] 调研是否有成熟的 Python MCP client SDK（如 `mcp` 包）
- [ ] 手工实现 `JsonRpcClient`：JSON-RPC 2.0，请求-响应配对、通知、错误码、超时
- [ ] 新建 `mcp/` 包 — `transport.py`、`client.py`、`manager.py`
  - `StdioTransport`：subprocess + newline-delimited JSON-RPC
  - `StreamableHttpTransport`：httpx + SSE 流式响应
- [ ] `initialize` 握手 + capabilities 协商 + protocol version negotiation
- [ ] `tools/list` + `tools/call`：工具按 `mcp__{server}__{tool}` 前缀注册
- [ ] MCP content 数组扁平化（text 拼接，image 给 fallback 提示）
- [ ] 配置文件：`~/.forge-agent/mcp.json` + `.forge-agent/mcp.json`
- [ ] HITL 集成：MCP 工具默认走确认
- [ ] CLI：`/mcp`、`/mcp restart <name>`、`/mcp disable/enable <name>`
- [ ] 编写测试（mock MCP server）
- [ ] 评测：接入 `filesystem` MCP server，对比内置 FileTool 行为

**改动文件**：
- 新建 `mcp/` 包（`__init__.py`, `client.py`, `transport.py`, `manager.py`）
- `tools/base.py` — ToolRegistry 支持动态添加/移除
- `config/default.yaml` — `mcp:` 配置段

---

### 任务 10：MCP 高级能力（PaiCLI 第 11 期）

**前置依赖**：任务 9（MCP 协议核心）

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
- `mcp/manager.py` — resources + prompts + 通知处理
- `agent/core.py` — 取消信号检查
- `entry/chat.py` — `/cancel`、`/mcp resources`、`/mcp prompts` 命令

---

### 任务 11：Chrome DevTools MCP（PaiCLI 第 13 期）

**前置依赖**：任务 9 / 10（MCP 框架）

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
- [ ] 端到端测试：微信公众号文章验证 web_fetch 失败 → 自动 fallback 到浏览器
- [ ] 编写测试（mock MCP server）

**改动文件**：
- `mcp/manager.py` — server 维度 HITL、超时配置
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
- [ ] Skill 加载：三层目录扫描（jar 内置 → `~/.forge-agent/skills/` → `.forge-agent/skills/`）
- [ ] `load_skill(name)` 工具：LLM 调用后把 SKILL.md 注入下一轮上下文
- [ ] `SkillContextBuffer`：一次性消费、最多保留 3 个 skill body
- [ ] 内置 `web-access` skill（任务 2 完成后）：浏览策略 + 工具选择表 + 站点经验
- [ ] CLI：`/skill list`、`/skill show <name>`、`/skill reload`
- [ ] 编写测试

**改动文件**：
- 新建 `skills/` 包
- `agent/core.py` — 注册 `load_skill` 工具
- `entry/chat.py` — `/skill` 命令

---

## 🔵 Tier 4 — 进阶能力（预计 5-7 周）

---

### 任务 14：多工具并行执行（PaiCLI 第 7 期）

**目标**：同一轮 LLM 返回多个 tool_calls 时并行执行。

**调研**：
- `concurrent.futures.ThreadPoolExecutor` 并行执行
- 统一超时机制（所有工具共享超时，超时的取消并返回占位结果）
- OpenAI/Anthropic 都支持单轮多个 tool_calls

**子任务**：
- [ ] `agent/core.py` — step 循环改为支持并行工具执行
- [ ] `tools/base.py` — ToolRegistry 新增 `execute_parallel(tool_calls)`
- [ ] 统一超时：任意工具超时不影响其他工具结果
- [ ] 编写测试
- [ ] 评测：对比串行 vs 并行的耗时（如同时读 5 个文件）

**改动文件**：
- `agent/core.py`
- `tools/base.py`

---

### 任务 15：Multi-Agent 协作（PaiCLI 第 5 期）

**目标**：多个 Agent 分工协作完成复杂任务。

**调研**：
- 三角色：Planner（分析→计划）→ Worker（执行）→ Reviewer（检查 diff + 测试结果）
- Worker 可并行多个
- 通信：共享 EventLog → Planner 读 Review 结果 → 决定重试或通过

**子任务**：
- [ ] 新建 `agent/multi_agent.py` — `Planner` / `Worker` / `Reviewer` 三角色
- [ ] 角色间通信协议（共享上下文传递）
- [ ] 任务分配与协调（DAG 拓扑依赖）
- [ ] 冲突解决策略（两个 Worker 改同一文件 → Reviewer 裁决）
- [ ] CLI：`--mode multi` 切换到 Multi-Agent 模式
- [ ] 编写测试

**改动文件**：
- 新建 `agent/multi_agent.py`
- `agent/prompt.py` — 新增 Planner/Worker/Reviewer prompt 模板
- `entry/cli.py` — `--mode multi`

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
- [ ] TUI 展示：诊断块红色(error)/黄色(warning) ANSI 渲染
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

## 🟣 Tier 5 — 产品化 + 高级特性（预计 5-7 周）

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
      plan.md            # Plan 模式（任务 1 完成后）
    tools/               # 各工具使用规范
    safety.md            # 安全约束
  ```
- [ ] 新建 `agent/prompt_assembler.py` — 按序拼接，稳定在前
- [ ] `agent/prompt.py` — 改为调用 PromptAssembler
- [ ] 启动时校验：必含 `## Language` section
- [ ] 用户级覆盖支持
- [ ] 回归全部现有测试（376 条确保行为不变）

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
- [ ] `llm/openai_compat.py` — 含图片时构造 content array
- [ ] `llm/anthropic_backend.py` — 含图片时构造 image content block
- [ ] MCP image content 的 `data` / `mimeType` 回灌为图片消息
- [ ] 用户输入支持 `@image:file:///path/to/img.png`
- [ ] 图片压缩：短边 ≤ 768px，长边 ≤ 2000px
- [ ] HITL 弹窗展示图片元数据（尺寸 / 大小），不展示原图
- [ ] 编写测试

**改动文件**：
- `llm/base.py`
- `llm/openai_compat.py`
- `llm/anthropic_backend.py`
- `mcp/manager.py` — image content 回灌

---

## 📐 评测体系设计

### 层级 1：功能回归测试（已有）

现有 `tests/` 目录 376 条用例。每次改动必跑。

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
- 复用 `EventLog` + `summarize_run()` — 提取统计数据（已有！）
- 新建 `eval/runner.py` — 批量执行 + 收集结果
- 新建 `eval/report.py` — 生成 Markdown / HTML 报告

**改动文件**：
- 新建 `eval/` 包

---

## 🔥 forge-agent 独有优势（PaiCLI 路线图未涵盖）

| 特性 | 说明 |
|------|------|
| **Docker 沙箱** | PaiCLI 第 6 期明确拒绝做沙箱，forge-agent 已实现 |
| **Reflection 反思** | 测试失败 / 连续无编辑两种自动触发 |
| **死循环检测** | 连续 N 步相同 (tool, params) 自动 GAVE_UP |
| **LLM 重试 + 指数退避** | 网络可恢复，认证不可恢复 |
| **GitHub Issue → PR** | 完整流水线 |
| **EventLog JSONL** | 事件日志 + replay + summarize_run |
| **推理模型思考/回答分离** | reasoning_content + message 独立流式 |

---

## 📊 工期估算

| Tier | 任务数 | 任务 | 预估 |
|------|--------|------|------|
| Tier 1（基础能力） | 6 | Plan / 联网 / Memory 补齐 / RAG / 审计路径 / 运行时切换 | 5-7 周 |
| Tier 2（上下文 + 工具 + 展示） | 2 | 长上下文 / TUI | 4-6 周 |
| Tier 3（架构重构） | 5 | MCP 核心 / MCP 高级 / Chrome / CDP / Skill | 3-5 周 |
| Tier 4（进阶能力） | 4 | 并行 / Multi-Agent / LSP / 快照 | 5-7 周 |
| Tier 5（产品化） | 3 | Prompt 分层 / 后台任务 / 图片输入 | 5-7 周 |
| 评测体系 | — | eval runner + report + mini-bench + 专项 | 2-3 周 |

**总计**：20 个任务，约 **24-35 周**（6-9 个月，单人全职）

以上估算基于单人全职开发。并行可压缩时间。
