"""
tools/mcp_client.py

MCP (Model Context Protocol) 客户端：
- 连接独立的 MCP Server（子进程，stdio JSON-RPC 传输）
- 自动发现其提供的工具
- 将每个远程工具包装成本地 BaseTool，注册到 ToolRegistry
- 代理工具调用请求给远程 MCP Server

支持多种 MCP Server：
- 我们自己写的 web_search_server
- 第三方提供的 MCP Server（如 Brave Search、Postgres 等）
- Claude Desktop 兼容的 MCP Server

设计：
- MCPToolProxy 继承 BaseTool，对 agent core 完全透明
- 所有 JSON-RPC 通信通过 mcp Python SDK 处理
- 同步 API，适配现有同步 BaseTool 接口
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional, List

from mcp.client.stdio import StdioClientTransport
from mcp.client.session import ClientSession

from mcp.types import (
    Tool as MCPTool,
    TextContent,
    CallToolResult,
)

from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration: MCPServerConfig
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """
    MCP Server 连接配置。

    对应 Claude Desktop config.json 中每个 server 条目：
    {
        "command": "python",
        "args": ["-m", "mcp_servers.web_search_server"],
        "env": {"SEARCH_MAX_RESULTS": "10"},
        "cwd": "/path/to/cwd",
    }

    Attributes:
        name:    服务器名称（用于日志和错误信息）
        command: 启动命令，如 "python" 或 "npx"
        args:    命令行参数列表
        env:     额外环境变量（可选，会继承当前进程环境）
        cwd:     工作目录（可选，默认当前目录）
    """
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None


# ---------------------------------------------------------------------------
# Proxy: MCPToolProxy (BaseTool subclass)
# ---------------------------------------------------------------------------

class MCPToolProxy(BaseTool):
    """
    把一个远程 MCP tool 包装成本地 BaseTool。

    对 forge-agent core 完全透明 — 就像使用本地工具一样使用远程工具。
    """

    def __init__(
        self,
        mcp_tool: MCPTool,
        session: ClientSession,
        server_name: str,
    ) -> None:
        self._mcp_tool = mcp_tool
        self._session = session
        self._server_name = server_name
        self._name = mcp_tool.name
        self._description = mcp_tool.description or f"MCP tool {mcp_tool.name} from {server_name}"
        self._parameters_schema = mcp_tool.inputSchema

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._parameters_schema

    def execute(self, params: dict[str, Any]) -> ToolResult:
        """
        同步执行：调用远程 MCP Server 的工具调用。

        会阻塞当前线程等待响应，适配现有同步 API。
        """
        try:
            # 需要在 asyncio 事件循环中运行 mcp SDK
            result = asyncio.run(self._call_remote(params))
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP tool '{self._name}' from server '{self._server_name}' failed: {exc}",
            )

        # 解析 CallToolResult — 拼接所有 text content
        output_text = ""
        has_error = False
        for content in result.content:
            if isinstance(content, TextContent):
                output_text += content.text + "\n"
            # 其他类型（如 image）暂时不支持，忽略
        output_text = output_text.strip()

        if result.is_error:
            return ToolResult(
                success=False,
                output=output_text,
                error=output_text or f"MCP tool '{self._name}' returned error",
            )

        return ToolResult(
            success=True,
            output=output_text,
        )

    async def _call_remote(self, params: dict[str, Any]) -> CallToolResult:
        """异步封装，供 asyncio.run() 调用。"""
        return await self._session.call_tool(self._name, params)


# ---------------------------------------------------------------------------
# Manager: MCPClientManager
# ---------------------------------------------------------------------------

class MCPClientManager:
    """
    管理多个 MCP Server 连接：
    1. 启动每个 server 子进程
    2. 建立 StdioClientTransport
    3. 初始化 session
    4. 调用 tools/list 发现工具
    5. 返回 MCPToolProxy 列表供注册

    使用后必须调用 close() 关闭所有连接和子进程。
    """

    def __init__(self) -> None:
        self._configs: list[MCPServerConfig] = []
        self._transports: list[StdioClientTransport] = []
        self._processes: list[subprocess.Popen] = []
        self._sessions: list[ClientSession] = []
        self._proxies: list[MCPToolProxy] = []
        self._connected = False

    def add_server(self, config: MCPServerConfig) -> "MCPClientManager":
        """添加一个 MCP Server 配置。"""
        if self._connected:
            raise RuntimeError("Cannot add servers after connect()")
        self._configs.append(config)
        return self

    async def connect_server(
        self, config: MCPServerConfig,
    ) -> AsyncGenerator[MCPToolProxy, None]:
        """连接单个 MCP Server 并发现工具。"""
        # 准备环境变量 — 继承当前环境 + 额外覆盖
        env = dict(os.environ)
        if config.env:
            env.update(config.env)

        # 启动子进程
        logger.info(f"Starting MCP server '{config.name}': {config.command} {' '.join(config.args)}")
        process = subprocess.Popen(
            [config.command] + config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=config.cwd or os.getcwd(),
            text=False,
        )
        self._processes.append(process)

        # 创建 transport
        transport = StdioClientTransport(
            process.stdout,
            process.stdin,
        )
        self._transports.append(transport)

        # 创建 session 并初始化
        session = ClientSession(transport)
        self._sessions.append(session)

        await session.initialize()
        logger.debug(f"Initialized MCP server '{config.name}'")

        # 列出所有工具
        tools_resp = await session.list_tools()
        logger.info(
            f"MCP server '{config.name}' discovered {len(tools_resp.tools)} tools: "
            f"{[t.name for t in tools_resp.tools]}"
        )

        # 创建 proxy 给每个工具
        for mcp_tool in tools_resp.tools:
            proxy = MCPToolProxy(mcp_tool, session, config.name)
            self._proxies.append(proxy)
            yield proxy

    async def connect_all(self) -> AsyncGenerator[MCPToolProxy, None]:
        """连接所有已添加的服务器，yield 所有工具 proxy。"""
        for config in self._configs:
            async for proxy in self.connect_server(config):
                yield proxy
        self._connected = True

    def connect_and_discover_sync(self) -> list[MCPToolProxy]:
        """同步版 connect_all，供入口代码调用。"""
        proxies: list[MCPToolProxy] = []

        async def _run():
            async for proxy in self.connect_all():
                proxies.append(proxy)

        asyncio.run(_run())
        return proxies

    def close(self) -> None:
        """关闭所有连接和子进程。"""
        logger.info(f"Closing {len(self._processes)} MCP server processes...")

        # 先关闭 transport 和 session（mcp SDK 会处理）
        # 然后关闭子进程

        for proc in self._processes:
            try:
                if proc.stdin:
                    proc.stdin.close()
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
                proc.terminate()
                proc.wait(timeout=5)
            except Exception as exc:
                logger.warning(f"Error terminating MCP process: {exc}")

        self._processes.clear()
        self._transports.clear()
        self._sessions.clear()
        self._connected = False

    @property
    def proxies(self) -> list[MCPToolProxy]:
        """已发现的工具代理列表。"""
        return self._proxies

    def __len__(self) -> int:
        return len(self._proxies)


# ---------------------------------------------------------------------------
# Helper: 从配置字典批量创建
# ---------------------------------------------------------------------------

def create_manager_from_config(
    servers_config: dict[str, dict[str, Any]],
    base_dir: str | None = None,
) -> MCPClientManager:
    """
    从 yaml 配置的 mcp_servers 字典创建 Manager。

    格式示例：
    mcp_servers:
      web-search:
        command: python
        args: ["-m", "mcp_servers.web_search_server"]
        env:
          SEARCH_MAX_RESULTS: "10"
        cwd: "/absolute/path"

    Returns:
        已添加所有 server 配置的 MCPClientManager（还未连接）
    """
    manager = MCPClientManager()
    base_cwd = base_dir or os.getcwd()

    for name, cfg in servers_config.items():
        command = cfg.get("command")
        args = cfg.get("args", [])
        env = cfg.get("env")
        cwd = cfg.get("cwd")

        if not command:
            logger.warning(f"Skipping MCP server '{name}': missing 'command'")
            continue

        # 相对 cwd 相对于项目根目录
        if cwd and not os.path.isabs(cwd) and base_dir:
            cwd = os.path.join(base_dir, cwd)
        elif not cwd:
            cwd = base_cwd

        manager.add_server(MCPServerConfig(
            name=name,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        ))

    return manager