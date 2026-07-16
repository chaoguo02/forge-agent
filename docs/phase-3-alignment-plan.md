# Phase 3: 工具参数对齐 + 工具命名对齐 + MCP 修复

> 参考来源：[CC Tools Reference](https://code.claude.com/docs/en/tools-reference) · [MCP Transports](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports/)

---

## 已有功能盘点

| CC 工具 | we have | 现状 |
|---------|---------|------|
| ReportFindings | `submit_findings` | BaseTool ✅，改名为 `ReportFindings` |
| SendMessage | `agent_control` (action=message) | BaseTool ✅，拆为独立 `SendMessage` |
| TaskCreate | `task` | BaseTool ✅ |
| TaskStop | `agent_control` (action=cancel) | BaseTool ✅ |
| EnterWorktree/ExitWorktree | 5 个 worktree tool + CLI | BaseTool ✅，需包装为 CC 名 |
| EnterPlanMode/ExitPlanMode | PlanApprovalService + CLI | 内部逻辑 ✅，需暴露为 BaseTool |
| Workflow | fan-out + concurrency_mode | 内部机制 ✅，需暴露为 BaseTool |
| ToolSearch | deferred_mcp_tool + is_deferred | 延迟加载后端 ✅，需暴露为 BaseTool |

---

## P0: 工具参数缺失 + MCP 错误（立即修复）

### P0-1: Read 添加 offset/limit 参数

**CC 参考**: Read 接受 `file_path`(必填)、`offset`(可选，起始行)、`limit`(可选，行数)。
参数超出范围时返回 PARTIAL view 通知。PDF 用 `pages` 参数。空文件返回空内容通知。

**当前状态**: `tools/file_tool.py` 的 `FileReadTool` 只有 `path` 参数，内部有 `MAX_READ_LINES` 硬截断。

**修改文件** (2):
- `tools/file_tool.py` — `FileReadTool.parameters_schema` 加 `offset`(integer)、`limit`(integer)
- `tests/test_file_tool.py` — 测试分页

**实现要点**:
```python
"offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
"limit": {"type": "integer", "description": "Maximum lines to read"},
```

---

### P0-2: Grep 添加 output_mode/glob/type/-i/head_limit/multiline

**CC 参考**: Grep 基于 ripgrep，参数包括:
- `pattern`(必填，regex)
- `path`(可选，搜索目录)
- `glob`(可选，如 `**/*.tsx`)
- `type`(可选，如 `py` `rust`)
- `output_mode`(可选，`files_with_matches`/`content`/`count`)，默认 files_with_matches
- `-i`(可选，忽略大小写)
- `head_limit`(可选，截断结果)
- `multiline`(可选，跨行匹配)
- `-A/-B/-C`(可选，上下文行数)

**当前状态**: `tools/search_tool.py` 的 `SearchTextTool` 只有 `pattern`、`path`、`file_pattern`、`case_sensitive`。

**修改文件** (2):
- `tools/search_tool.py` — `SearchTextTool` 参数全面对齐
- `tests/test_search_tool.py` — 测试新增参数

---

### P0-3: WebSearch → PascalCase + allowed_domains/blocked_domains

**CC 参考**: `WebSearch` 接受 `query`(必填)、`allowed_domains`(string[])、`blocked_domains`(string[])。不加 specifier。

**当前状态**: `tools/web_tool.py` 命名为 `web_search`，只有 `query` 和 `count`。

**修改文件** (2):
- `tools/web_tool.py` — 改名为 `WebSearch`，alias `web_search`，加 `allowed_domains`/`blocked_domains`
- 所有引用 `web_search` 的地方（registry_factory, agent models, prompts）

---

### P0-4: WebFetch → PascalCase + prompt 参数

**CC 参考**: `WebFetch` 接受 `url`(必填)、`prompt`(必填，描述要提取什么)。

**当前状态**: `tools/web_tool.py` 命名为 `web_fetch`，只有 `url`。

**修改文件** (2):
- `tools/web_tool.py` — 改名为 `WebFetch`，alias `web_fetch`，加 `prompt`
- 所有引用 `web_fetch` 的地方

---

### P0-5: Bash 添加 dangerouslyDisableSandbox

**CC 参考**: Bash 接受 `command`、`description`、`timeout`(默认120s，最大600s)、`run_in_background`、`dangerouslyDisableSandbox`。

**当前状态**: 缺 `dangerouslyDisableSandbox`。

**修改文件** (1):
- `tools/shell_tool.py` — 加参数，默认 False，需用户确认

---

### P0-6: MCP SSE 修复 — 消息派发

**CC 参考**: SSE 通过 `GET /sse` 接收 server→client 的 JSON-RPC 消息。当收到 `message` event 时，解析 JSON 并派发（notifications 通知、responses 回调）。

**当前状态**: `SseMCPBridge._read_sse_stream` 解析 JSON 后**丢弃**。消息从未到达调用者。

**修改文件** (1):
- `runtime/mcp/client.py` — 重写 `_read_sse_stream`，派发 incoming notifications/responses

---

### P0-7: MCP Resources — ListMcpResourcesTool + ReadMcpResourceTool

**CC 参考**: MCP Resources 通过 `resources/list` 和 `resources/read` JSON-RPC 方法暴露。`ListMcpResourcesTool` 和 `ReadMcpResourceTool` 是暴露这些功能的 CC 工具。

**修改文件** (2):
- `runtime/mcp/client.py` — `MCPToolBridge` 加 `list_resources()`/`read_resource()` 方法
- `runtime/mcp/tool_adapter.py` — 创建资源工具适配器

---

## P1: 工具命名对齐 + 已有功能整合

### P1-1: web_search → WebSearch, web_fetch → WebFetch
同 P0-3, P0-4，此处为引用更新。

### P1-2: task → Agent (CC 命名)
- `agent/v2/task_tool.py` — `AgentTool.name` 改为 `"Agent"`，alias `"task"`

### P1-3: submit_findings → ReportFindings
- `tools/submit_findings_tool.py` — `SubmitFindingsTool.name` 改为 `"ReportFindings"`，alias `"submit_findings"`

### P1-4: agent_control 功能拆分
拆为 `SendMessage`(message) + `TaskStop`(cancel) + `TaskOutput`(wait) 三个独立工具。

### P1-5: EnterPlanMode / ExitPlanMode
将 `PlanApprovalService` 包装为 BaseTool。

### P1-6: EnterWorktree / ExitWorktree
将已有 worktree 管理包装为 CC 命名的 BaseTool。

### P1-7: Workflow 工具
将 fan-out 并行机制暴露为 Workflow 工具。

### P1-8: ToolSearch 工具
将 deferred MCP tool 延迟加载暴露为 ToolSearch 工具。

### P1-9: Git + Test 工具策略
Git 工具 (git_status/diff/add/commit) 和 PytestTool 保留为 forge-agent 独有工具，不在 CC 对齐范围内。命名从 snake_case 改为小写首字母（如 `GitStatus` → 保持 `git_status` 作为项目约定）。

---

## P2: 新工具开发 (待后续实现)

| 工具 | 依赖 | 复杂度 |
|------|------|--------|
| AskUserQuestion | hitl/pipeline.py 的基础 | 低 |
| CronCreate/Delete/List | 全新调度系统 | 高 |
| LSP | 需插件系统 | 高 |
| Monitor | WebSocket 基础已有 | 中 |
| NotebookEdit | 全新 | 中 |
| PushNotification | 全新 | 低 |
| TaskList/TaskGet/TaskOutput/TaskUpdate | SessionStore 已有基础 | 中 |
| ScheduleWakeup | 全新 | 中 |
| SendUserFile | 全新 | 低 |
| WaitForMcpServers | SyncMCPToolManager 已有基础 | 低 |

---

## 批次执行计划

### Batch 12 (P0): Read + Grep 参数对齐（3 文件）
- `tools/file_tool.py` — Read 加 offset/limit
- `tools/search_tool.py` — Grep 参数完全对齐 CC
- `tests/` — 测试

### Batch 13 (P0): WebSearch + WebFetch 命名 + 参数（4 文件）
- `tools/web_tool.py` — PascalCase + 参数
- `entry/bootstrap/registry_factory.py` — 引用更新
- `agent/v2/models.py` — DEFAULT_GENERAL_TOOLS 更新
- `prompts/` — prompt 更新

### Batch 14 (P0): Bash + MCP SSE + MCP Resources（5 文件）
- `tools/shell_tool.py` — dangerouslyDisableSandbox
- `runtime/mcp/client.py` — SSE 消息派发 + resources 方法
- `runtime/mcp/tool_adapter.py` — 资源工具适配
- `tests/` — 测试

### Batch 15 (P1): 工具命名对齐 — Agent + WebSearch/WebFetch + ReportFindings（5 文件）
- `agent/v2/task_tool.py` — task → Agent
- `tools/submit_findings_tool.py` — submit_findings → ReportFindings
- `tools/web_tool.py` — 最终命名
- `agent/v2/models.py` — DEFAULT_GENERAL_TOOLS
- 引用更新

### Batch 16 (P1): 已有功能暴露 — PlanMode + Worktree + SendMessage + TaskStop（6 文件）
- 新增 `tools/plan_mode_tool.py` — EnterPlanMode/ExitPlanMode
- 新增 `tools/worktree_tool.py` — EnterWorktree/ExitWorktree
- `agent/v2/agent_control_tool.py` — 拆分 SendMessage + TaskStop
- 引用更新

### Batch 17 (P1): Workflow + ToolSearch（4 文件）
- 新增 `tools/workflow_tool.py`
- `runtime/mcp/` — ToolSearch 工具
- 引用更新

---

## 验证

每批完成后：
```
pytest tests/ -q --ignore=tests/test_v2_runtime.py
```
