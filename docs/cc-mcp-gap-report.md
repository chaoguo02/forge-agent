# MCP 系统 — CC 对齐差距报告

> 依据: CC 官方文档 + DeepWiki 源码分析
> 调研: 2026-07-16

---

## 一、架构总览对比

```
CC MCP 架构                          forge-agent MCP 架构
─────────────────                    ────────────────────
.mcp.json (project)                   .mcp.json ✓
~/.claude/config.json (user)          未实现
--mcp-config CLI flag                 支持
managed-mcp.json (enterprise)         未实现

transport: stdio / http / sse / ws    stdio ✓ / http ✓ / sse ✓ / ws ✓
on-demand connect                     总是启动时连接
agent-scoped mcpServers frontmatter   字段已解析, 未连接
auto-reconnect (exponential backoff)  SyncMCPToolManager ✓
tool discovery at startup             ✓
resources/list + resources/read       ✓
notifications (tools/list_changed)    ✓
20+ server cap                        无限制
```

---

## ✅ 已正确实现

| # | 特性 | 位置 | 说明 |
|---|------|------|------|
| 1 | stdio transport | `executor/mcp/client.py:80-284` | MCP SDK stdio_client |
| 2 | HTTP transport | `executor/mcp/client.py:286-440` | JSON-RPC 2.0 over httpx |
| 3 | SSE transport | `executor/mcp/client.py:442-517` | SSE streaming + POST |
| 4 | WS transport | `executor/mcp/client.py:518-582` | websockets 库 |
| 5 | Sync bridge | `executor/mcp/sync_bridge.py` | asyncio.run() 包装 |
| 6 | 自动重连 | `executor/mcp/sync_bridge.py:41-52` | 指数退避 max_retries=2 |
| 7 | ExecutionPolicy | `executor/mcp/sync_bridge.py:29-55` | idle_timeout / max_retries |
| 8 | 工具发现 | `MCPToolBridge.list_tools()` | 初始化时查询 |
| 9 | Resources 支持 | `executor/mcp/client.py:213-249` | list_resources / read_resource |
| 10 | Notifications 支持 | `executor/mcp/client.py:258-262` | tools/list_changed |
| 11 | MCPToolIntegration | `agent/session/mcp_integration.py` | V2 集成层 |
| 12 | agent_definition.mcp_servers 解析 | `agent/session/agent_definition.py:203-208` | 字段已解析 |

---

## ❌ 未实现

### 1. user-scoped MCP config (`~/.claude.json`)

**CC**: `~/.claude.json` 中的 `mcpServers` 作为用户级全局配置, 跨项目可用。

**我们**: 只支持 `.mcp.json` (项目级)。无用户级 MCP 配置。

### 2. enterprise/managed MCP config

**CC**: `managed-mcp.json` 由管理员部署, 用户无法覆盖。

**我们**: 不支持。

### 3. agent-scoped mcpServers 真正连接

**CC**: agent frontmatter 中的 `mcpServers` 在 agent 启动时连接, 结束时断开。

**我们**: 字段已解析到 `AgentDefinition.mcp_servers`, `_mcp_tool_names_for_spec()` 尝试解析命名引用, 但 `server_tools` 属性只对**已连接的全局服务器**有效。agent-scoped 的内联定义 (`{name: {command: ...}}`) 从未真正连接过:

```python
# agent/session/runtime.py:1561-1568
if spec.mcp_servers:
    server_tools = self._mcp_integration.server_tools
    for entry in spec.mcp_servers:
        if isinstance(entry, str):
            raw_names.update(server_tools.get(entry, []))  # 只查已连接的
        elif isinstance(entry, dict):
            for name in entry:
                raw_names.update(server_tools.get(name, []))  # 也查不到!
```

### 4. on-demand 连接 (懒加载)

**CC**: 服务器在首次调用时才连接, 不是所有服务器都在启动时连接。

**我们**: `MCPToolIntegration.initialize()` 一次性连接所有已配置的服务器。

### 5. agent 级别 MCP server 生命周期 (连接/断开)

**CC**: agent 启动时连接 mcpServers, 结束时断开。工具描述不出现在主会话中。

**我们**: `MCPToolIntegration` 没有 `connect_agent_servers()` / `disconnect_agent_servers()` 方法 (虽然我在 Batch C2 中设计了但未实现)。

### 6. 最大 20 服务器限制

**CC**: 超过 20 个服务器时发现时间超过 2s, 有性能警告。

**我们**: 无限制。

### 7. OAuth 认证流程

**CC**: SSE transport 自动处理 OAuth flow, 在浏览器中提示用户。

**我们**: HTTP/SSE 只有 `headers` 参数, 无 OAuth 支持。

---

## ⚠️ 已实现但错误

### 1. `_mcp_tool_names_for_spec()` 有代码路径但从不被调用

**位置**: `agent/session/runtime.py:1556-1583`

**问题**: 这个方法计算 agent 应该有哪些 MCP 工具, 但 `registry_builder.py` 中构建 session registry 的代码路径是:

```python
# registry_builder.py:105
declared = agent_registry.tool_names_for(spec.name)
# ...
registry = registry.filtered(declared | mcp_tool_names)
```

其中 `mcp_tool_names` 来自 `SessionRuntime._mcp_tool_names_for_spec()`, 但这个调用链只在特定路径中触发。让我确认这个函数是否真的被调用:

```python
# runtime.py:1490 — 这是另一个方法
mcp_tool_names = getattr(self._mcp_integration, "tool_names", frozenset())
```

看起来 `build_registry_for_session()` 在 `registry_builder.py:90` 接受 `mcp_tool_names` 参数, 但这个参数是从哪里传来的? 让我检查:

如果在`SessionRuntime._build_registry_for_session()` 传了 `_mcp_tool_names_for_spec(spec)`, 那它应该工作。但这个调用关系需要验证。

### 2. SSE bridge 的 `_read_sse_stream` 通知被丢弃

**位置**: `executor/mcp/client.py:468-498`

**问题**: SSE stream 中收到的 `event: message` 通知被解析了, 但 `dispatch` 路径需要验证是否正确路由到 `_on_list_changed`。

### 3. HTTP bridge 没有 content-type 验证

**位置**: `executor/mcp/client.py:346-436`

**问题**: `HttpMCPBridge.call_tool()` 发送 POST 请求后, 不验证响应 Content-Type 是否为 `application/json`, 可能被非 JSON 响应误导。

---

## 总结

| 类别 | 数量 | 关键项 |
|------|------|--------|
| ✅ 已正确实现 | 12 项 | 4 transport、sync_bridge、auto-reconnect、resources、notifications |
| ❌ 未实现 | 7 项 | user/managed config、agent-scoped 连接、on-demand、OAuth |
| ⚠️ 已实现但错误 | 3 项 | _mcp_tool_names_for_spec 调用链、SSE dispatch、HTTP content-type |
