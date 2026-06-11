"""
mcp_servers/

独立的 MCP (Model Context Protocol) 服务器包。
每个服务器是一个独立的进程，通过 stdio JSON-RPC 与 MCP 客户端通信。

当前包含：
- web_search_server: 提供 web_search 和 web_fetch 工具

用法：
    python -m mcp_servers.web_search_server

在 Claude Desktop 配置中：
    {
        "mcpServers": {
            "web-search": {
                "command": "python",
                "args": ["-m", "mcp_servers.web_search_server"],
                "cwd": "/path/to/forge-agent"
            }
        }
    }
"""