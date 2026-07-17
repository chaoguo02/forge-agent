# MCP 系统 CC 对齐 — 实现计划

> 依据: CC 官方文档 + DeepWiki 源码分析
> 参考: https://code.claude.com/docs/en/mcp

---

## 批次数

| 批次 | 主题 | 文件数 | 核心改动 |
|------|------|--------|---------|
| M1 | agent-scoped mcpServers 连接生命周期 | 6 | 在 spawn_agent 时连接/断开内联 MCP 服务器 |
| M2 | 用户级 MCP 配置 + deferred 验证 | 4 | 支持 ~/.forge-agent/mcp.json, ToolSearch 端到端验证 |
| M3 | SSE dispatch + HTTP content-type | 2 | 修复通知路由, 添加响应验证 |

---

## Batch M1: agent-scoped mcpServers 连接生命周期

### CC 依据

> Agent frontmatter `mcpServers` 声明的服务器在 agent 启动时连接、结束时断开。
> 内联定义 (`{name: {command: "npx", args: [...]}}`) 是一个完整的 MCP server config。
> 字符串引用 (`"slack"`) 复用已连接的 session 级服务器。

### 现状

`agent/session/mcp_integration.py` 的 `MCPToolIntegration` 只有 `initialize()` 一次性连接所有 session 级服务器。没有 `connect_agent_servers()` / `disconnect_agent_servers()` 方法。
`_mcp_tool_names_for_spec()` 只能查已连接的服务器, 内联定义查不到。

### 修改

#### 1. `agent/session/mcp_integration.py` — 新增连接/断开方法

```python
def connect_agent_servers(self, spec: AgentDefinition) -> list[str]:
    """Connect MCP servers declared in an agent's mcpServers frontmatter.
    Returns list of newly registered tool names.
    """
    if not spec.mcp_servers:
        return []
    new_tools = []
    for entry in spec.mcp_servers:
        if isinstance(entry, dict):
            for name, config in entry.items():
                if not isinstance(config, dict):
                    continue
                # Create MCPServerConfig from inline definition
                server_config = _parse_server_config(name, config)
                if server_config:
                    self._connect_server(server_config)
                    # Register discovered tools into registry
                    for tool in self._tools:
                        if hasattr(tool, '_runtime_tool') and hasattr(tool._runtime_tool, 'mcp_props'):
                            if tool._runtime_tool.mcp_props and tool._runtime_tool.mcp_props.server_name == name:
                                new_tools.append(tool.name)
    return new_tools

def disconnect_agent_servers(self, spec: AgentDefinition) -> None:
    """Disconnect agent-scoped MCP servers when agent finishes."""
    if not spec.mcp_servers:
        return
    for entry in spec.mcp_servers:
        if isinstance(entry, dict):
            for name in entry:
                self._disconnect_server(name)
```

#### 2. `executor/mcp/client.py` — MCPToolBridge 支持连接跟踪

在 `MCPToolBridge` 中添加 `server_name` 属性, 让 `MCPToolIntegration` 能按 server 名工具归类和断开。

#### 3. `agent/session/runtime.py` — spawn_agent 时连接/断开

在 `spawn_agent()` 中, 创建 child session 后调用 `_mcp_integration.connect_agent_servers(definition)`。
在 agent 完成时（`_execute_child_session` 返回后）调用 `_mcp_integration.disconnect_agent_servers(definition)`。

#### 4. `agent/session/runtime.py` — 修复 _mcp_tool_names_for_spec

当前逻辑对 `spec.mcp_servers` 中的内联定义查 `server_tools` 无效。改为：
- 内联定义的 MCP 工具由 `connect_agent_servers()` 注册到 `self._tools`, 然后返回所有已注册的工具名。
- 字符串引用仍然查 server_tools。

### 涉及文件 (6 个)
1. `agent/session/mcp_integration.py` — connect/disconnect 方法
2. `agent/session/runtime.py` — spawn_agent 生命周期
3. `executor/mcp/client.py` — server_name 跟踪
4. `executor/mcp/types.py` — MCPServerConfig 增强
5. `entry/bootstrap/registry_factory.py` — 传递 skill_registry
6. `agent/session/agent_definition.py` — mcp_servers 解析 (验证)

---

## Batch M2: 用户级 MCP 配置 + deferred 验证

### 1. 用户级 MCP 配置

**CC**: `~/.claude/config.json` 中的 `mcpServers` 作为用户级全局配置。

**改动**: `executor/mcp/config.py`
```python
def _load_user_mcp_config() -> dict:
    """Load user-level MCP config from ~/.forge-agent/mcp.json."""
    path = Path.home() / ".forge-agent" / "mcp.json"
    if path.exists():
        return json.loads(path.read_text()).get("mcpServers", {})
    return {}
```
在 `load_mcp_config()` 中增加用户级配置扫描, 优先级: CLI > project > user。

### 涉及文件 (3 个)
1. `executor/mcp/config.py` — 用户级配置加载
2. `agent/session/mcp_integration.py` — 传递用户级配置
3. `entry/cli.py` — mcp CLI 管理命令支持用户级

---

## Batch M3: SSE dispatch + HTTP content-type

### 1. SSE 通知分发修复

**现状**: `SseMCPBridge._read_sse_stream()` 中, event-stream 事件被解析为 JSON-RPC, 但通知需要路由到 `_dispatch_notification()` 。

**改动**: `executor/mcp/client.py:442-517`
```python
async def _read_sse_stream(self):
    async for event in self._sse_response.aiter_lines():
        if event.type == "event" and event.data:
            try:
                msg = json.loads(event.data)
                if "method" in msg:  # It's a notification
                    await self._handle_notification(msg)
                elif "id" in msg:  # It's a response
                    # route to pending request
                    pass
            except json.JSONDecodeError:
                pass
```

### 2. HTTP content-type 验证

**现状**: `HttpMCPBridge.call_tool()` 发送 POST 后不验证 Content-Type。

**改动**: `executor/mcp/client.py:346-436`
```python
if not response.headers.get("content-type", "").startswith("application/json"):
    return MCPCallResult(
        success=False, output="",
        error=f"Expected application/json, got {response.headers.get('content-type')}"
    )
```

### 涉及文件 (2 个)
1. `executor/mcp/client.py` — SSE dispatch + HTTP content-type
2. `agent/session/mcp_integration.py` — 通知传播到 ToolSearch
