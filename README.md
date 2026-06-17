# Forge Agent

自主编程智能体。给它一个任务描述，它会自己探索代码库、修改文件、运行测试，直到完成。

支持 **Claude、DeepSeek、OpenAI、Groq、Ollama** 多种模型，内置流式输出、Docker 沙箱、HITL 人工审批、Multi-Agent 协作。

---

## 快速开始

```bash
# 克隆 & 安装
git clone <repo-url> && cd forge-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 配置（复制模板，填入 API Key）
cp .env.template .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx

# 启动交互对话
python -m entry.cli chat --repo .
```

> `.env` 启动时自动加载（python-dotenv），无需手动 export。

---

## 配置

所有 LLM 配置通过 `.env` 文件管理，敏感信息不入库：

```bash
# .env（从 .env.template 复制）
FORGE_LLM_PROVIDER=deepseek                    # deepseek / openai / anthropic / groq / ollama
FORGE_LLM_MODEL=deepseek/deepseek-v4-flash     # 模型名称
FORGE_LLM_BASE_URL=https://api.llm.mioffice.cn/v1/  # API 地址
DEEPSEEK_API_KEY=sk-xxx                        # API Key
HF_ENDPOINT=https://hf-mirror.com             # embedding 模型下载镜像
```

配置优先级：**CLI 参数 > .env 环境变量 > config/default.yaml 默认值**

运行时可通过 `/model` 和 `/mode` 命令动态切换，无需重启。

---

## 使用方式

### chat 模式（推荐）

持续对话，每轮历史保留，最接近 Claude Code 的体验：

```bash
python -m entry.cli chat                          # 当前目录
python -m entry.cli chat --repo /path/to/project  # 指定目录
python -m entry.cli chat --model gpt-4o           # 临时切换模型
python -m entry.cli chat --sandbox                # Docker 沙箱
```

对话内命令：

| 命令 | 作用 |
|------|------|
| `/exit` | 退出 |
| `/mode react\|plan\|auto\|multi-agent` | 切换 agent 模式 |
| `/model <name>` | 切换 LLM 模型 |
| `/compact` | 压缩对话历史 |
| `/stats` | 查看统计 |
| `/clear` | 清空历史 |
| `/help` | 帮助 |

### run 模式

一次性任务，适合明确的批处理场景：

```bash
python -m entry.cli run --task "修复所有 failing 的测试"
python -m entry.cli run --task-file task.txt
python -m entry.cli run --task "..." --confirm     # 危险命令需确认
python -m entry.cli run --task "..." --sandbox     # Docker 沙箱
```

### plan 模式

复杂任务先拆解为 DAG，再按依赖顺序执行：

```bash
# chat 内通过 /mode 切换
/mode plan
重构 api.py，拆分成更小的函数并补测试
```

### multi-agent 模式

Coordinator 驱动多个子 Agent 并行协作：

```bash
/mode multi-agent
重构整个认证模块，需要探索、编码、测试三步并行
```

### GitHub Issue 自动修复

```bash
export GITHUB_TOKEN=ghp_xxx
python -m entry.github_issue \
    --repo owner/repo --issue 42 --local-path /tmp/myrepo
```

---

## 架构

```
forge-agent/
├── agent/              # 核心 Agent 引擎
│   ├── core.py         # ReAct 主循环（思考→行动→观察）
│   ├── plan.py         # Plan-and-Execute（DAG 调度）
│   ├── multi_agent.py  # Multi-Agent 协作（Coordinator + SubAgent）
│   ├── factory.py      # Agent 工厂（react/plan/auto/multi-agent）
│   ├── task.py         # Task / Action / Observation 数据模型
│   ├── event_log.py    # JSONL append-only 事件流
│   └── prompt.py       # System prompt 模板
│
├── llm/                # LLM 后端抽象
│   ├── base.py         # LLMBackend 基类 + native tool_use
│   ├── anthropic_backend.py   # Claude（原生 tool_use + prompt cache）
│   ├── openai_backend.py      # OpenAI / DeepSeek / Groq / Ollama
│   └── router.py       # 按配置自动选择 backend
│
├── tools/              # 工具层（Agent 可调用的操作）
│   ├── base.py         # BaseTool + RiskLevel + ToolRegistry（含 HITL 门控）
│   ├── file_tool.py    # 文件读写查看
│   ├── shell_tool.py   # Shell 执行（三层安全防护）
│   ├── search_tool.py  # 文本搜索 / 文件查找 / 符号定位
│   ├── git_tool.py     # git status / diff / add / commit
│   ├── memory_tool.py  # 记忆读写搜索（含 RAG 向量检索）
│   ├── web_tool.py     # web_search + web_fetch
│   ├── runtime.py      # LocalRuntime / DockerRuntime 沙箱
│   └── mcp_client.py   # MCP 外部工具服务器连接
│
├── hitl/               # Human-in-the-Loop 框架
│   ├── request.py      # HitlRequest / HitlResult / HitlStats
│   ├── policy.py       # PolicyEngine（YAML 规则，自动审批/拒绝）
│   └── manager.py      # HitlManager（风险阈值→策略→用户确认）
│
├── memory/             # 三层记忆系统
│   ├── store.py        # 文件型长期记忆（YAML frontmatter .md）
│   ├── external_store.py # SQLite + 向量语义搜索
│   ├── chunker.py      # 语义分块（段落/标题 + 滑动窗口）
│   ├── indexer.py      # 写入时自动向量索引
│   ├── retriever.py    # 主动检索（每轮自动注入相关记忆）
│   ├── context.py      # 记忆上下文注入管理
│   └── proactive.py    # 主动记忆检测（用户偏好/命令模式）
│
├── context/            # 上下文工程
│   ├── repo_map.py     # tree-sitter 多语言符号提取
│   ├── structured.py   # StructuredContext 分层上下文
│   ├── history.py      # 对话历史滑动窗口
│   ├── token_budget.py # Token 预算管理
│   └── compaction.py   # 多层上下文压缩
│
├── skills/             # Skill 系统（可复用提示词包）
│   ├── registry.py     # Skill 发现与加载
│   └── tool.py         # load_skill 工具
│
├── mcp_servers/        # 内置 MCP 服务器
│   └── web_search_server.py  # Web 搜索 MCP server
│
├── entry/              # 入口层
│   ├── cli.py          # Click CLI（run / chat / log）
│   ├── chat.py         # ChatSession 跨轮持久化
│   ├── renderer.py     # TUI 渲染（流式 + 工具面板 + HITL 确认 UI）
│   └── github_issue.py # GitHub Issue → PR 自动化
│
├── config/
│   ├── default.yaml    # 默认配置（引用 ${ENV_VAR}）
│   └── schema.py       # 配置加载 + 环境变量展开
│
├── .env.template       # 环境变量模板（提交到 git）
├── .env                # 本地配置（不提交，填入真实 key）
└── tests/              # 578 测试用例
```

---

## 核心特性

### HITL 人工审批框架

统一的 Human-in-the-Loop 审批流，所有工具调用按风险分级：

| 风险等级 | 代表工具 | 行为 |
|---------|---------|------|
| NONE | file_read, git_status, search | 静默通过 |
| LOW | git_add, memory_write | 低于阈值自动通过 |
| MEDIUM | file_write | 弹出确认框 |
| HIGH | git_commit, shell(rm/pip install) | 弹出确认框 |

```
┌─ Confirmation Required ──────────────────────────────────
│  Tool:   file_write
│  Risk:   MEDIUM
│  Params: path="src/main.py"
└──────────────────────────────────────────────────────────
[y]approve / [n]deny / [n: reason]deny with feedback >
```

特性：
- **PolicyEngine**: YAML 规则文件，支持 regex/contains/equals 条件自动审批/拒绝
- **动态风险分类**: ShellTool 根据命令内容动态判断（readonly→NONE, rm→HIGH）
- **反馈注入**: deny 时附带原因，注入 Agent 上下文影响后续决策
- **统计追踪**: HitlStats 记录审批率、平均等待时间

### Multi-Agent 协作

Coordinator 驱动的星型多 Agent 架构：

| Agent 角色 | 工具权限 | 用途 |
|-----------|---------|------|
| Coordinator | spawn_agent, spawn_parallel | 任务分解、结果汇总 |
| Reader | 只读工具 | 代码搜索、文件定位 |
| Writer | 读写工具 | 代码编写、文件修改 |
| Verifier | Shell + 只读 | 运行测试、验证结果 |

- ThreadPoolExecutor 并行执行独立子 Agent
- Git worktree 隔离并行文件修改
- Token 预算 Coordinator 30% / SubAgents 70% 分配

### 三层记忆系统

| 层级 | 存储 | 用途 |
|------|------|------|
| 短期记忆 | 对话历史（内存） | 当前会话上下文，滑动窗口 + 多层压缩 |
| 长期记忆 | .md 文件 | 跨会话持久化，按 name 精确读取 |
| 外部记忆 | SQLite + 向量索引 | RAG 语义检索，自动分块 + 主动召回 |

RAG 管线：
```
写入记忆 → 自动分块(chunker) → 批量 embed(fastembed) → SQLite memory_chunks
                                                          ↑
每轮对话 → user_message → ProactiveRetriever → search_chunks → 注入 LLM 上下文
```

### Prompt Caching + 结构化上下文

StructuredContext 分层组装 system prompt，稳定前缀最大化缓存命中：

```
[system_prompt] → [repo_map] → [memory] → [skills] → [conversation]
     稳定                                                  变化
     ← prompt cache 命中区 →
```

- DeepSeek 自动前缀缓存（100% hit rate）
- Anthropic 显式 cache_control 标记
- 每轮结束显示 `cache 100%` 命中率

### 多模型支持

- Anthropic Claude（原生 tool_use + prompt cache）
- OpenAI、DeepSeek、Groq、Ollama（OpenAI-compatible）
- 运行时 `/model` 切换，历史保留

### 安全机制（三层）

- **硬拦截**：`rm -rf /`、`mkfs` 等永不执行
- **只读白名单**：`ls`、`grep`、`git status` 等直接执行
- **HITL 审批**：中高风险操作弹出确认框，支持 deny + feedback

### 其他

- **流式输出**：thought + 工具调用实时渲染，Claude Code 风格 TUI
- **Plan-and-Execute**：复杂任务 DAG 拆解 + 按依赖并行
- **Docker 沙箱**：`--sandbox` 隔离执行
- **Reflection**：测试失败/死循环自动反思
- **Web 工具**：搜索 + URL 抓取 + SSRF 防护
- **MCP 协议**：外部工具服务器热插拔
- **Skill 系统**：可复用提示词包，按需加载

---

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest                            # 全量（578 passed）
pytest tests/test_hitl.py         # HITL 框架测试
pytest tests/test_multi_agent.py  # Multi-Agent 测试
pytest tests/test_rag_memory.py   # RAG 管线测试

# 可选：更多语言的 tree-sitter 支持
pip install tree-sitter-javascript tree-sitter-typescript \
            tree-sitter-go tree-sitter-rust tree-sitter-java

# 可选：精确 token 计数
pip install tiktoken
```

---

## 命令参考

```bash
# chat（交互对话）
python -m entry.cli chat [--repo PATH] [--model MODEL] [--sandbox] [-v]

# run（一次性任务）
python -m entry.cli run --task TEXT [--repo PATH] [--task-file FILE]
          [--model MODEL] [--confirm] [--sandbox] [--no-stream] [-v]

# log（事件日志查看）
python -m entry.cli log list [--dir DIR]
python -m entry.cli log show LOG_FILE

# github issue（自动修复）
python -m entry.github_issue \
    -r owner/repo -i ISSUE_NUM -l LOCAL_PATH [--no-pr] [-v]
```
