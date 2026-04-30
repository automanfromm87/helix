import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool as MCPRemoteTool

from app.domain.models.mcp_config import MCPConfig, MCPServerConfig
from app.domain.models.tool_result import ToolResult
from app.domain.services.tools.base import BaseToolkit, Tool

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Manages connections to configured MCP servers and dispatches tool calls."""

    def __init__(self, config: Optional[MCPConfig] = None):
        self._clients: Dict[str, ClientSession] = {}
        self._exit_stack = AsyncExitStack()
        self._tools_cache: Dict[str, List[MCPRemoteTool]] = {}
        self._initialized = False
        self._config = config

    async def initialize(self):
        if self._initialized:
            return
        try:
            logger.info(
                "Loaded %d MCP server configs", len(self._config.mcpServers) if self._config else 0
            )
            await self._connect_servers()
            self._initialized = True
            logger.info("MCP client manager initialized")
        except Exception as e:
            logger.error(f"MCP client manager init failed: {e}")
            raise

    async def _connect_servers(self):
        if not self._config:
            return
        for server_name, server_config in self._config.mcpServers.items():
            if not server_config.enabled:
                continue
            try:
                await self._connect_server(server_name, server_config)
            except Exception as e:
                logger.error(f"Failed to connect MCP server {server_name}: {e}")

    async def _connect_server(self, server_name: str, server_config: MCPServerConfig):
        transport_type = server_config.transport
        if transport_type == "stdio":
            await self._connect_stdio_server(server_name, server_config)
        elif transport_type in ("http", "sse"):
            await self._connect_http_server(server_name, server_config)
        elif transport_type == "streamable-http":
            await self._connect_streamable_http_server(server_name, server_config)
        else:
            logger.error(f"Unsupported MCP transport: {transport_type}")

    async def _connect_stdio_server(self, server_name: str, server_config: MCPServerConfig):
        command = server_config.command
        if not command:
            raise ValueError(f"MCP server {server_name} missing command")
        server_params = StdioServerParameters(
            command=command,
            args=server_config.args or [],
            env={**os.environ, **(server_config.env or {})},
        )
        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_server_tools(server_name, session)

    async def _connect_http_server(self, server_name: str, server_config: MCPServerConfig):
        url = server_config.url
        if not url:
            raise ValueError(f"MCP server {server_name} missing url")
        sse_transport = await self._exit_stack.enter_async_context(sse_client(url))
        read_stream, write_stream = sse_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_server_tools(server_name, session)

    async def _connect_streamable_http_server(self, server_name: str, server_config: MCPServerConfig):
        url = server_config.url
        if not url:
            raise ValueError(f"MCP server {server_name} missing url")
        client_params: Dict[str, Any] = {"url": url}
        if server_config.headers:
            client_params["headers"] = server_config.headers
        streamable_transport = await self._exit_stack.enter_async_context(
            streamablehttp_client(**client_params)
        )
        if len(streamable_transport) == 3:
            read_stream, write_stream, _ = streamable_transport
        else:
            read_stream, write_stream = streamable_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._clients[server_name] = session
        await self._cache_server_tools(server_name, session)

    async def _cache_server_tools(self, server_name: str, session: ClientSession):
        try:
            response = await session.list_tools()
            self._tools_cache[server_name] = response.tools if response else []
            logger.info(f"MCP server {server_name} exposes {len(self._tools_cache[server_name])} tools")
        except Exception as e:
            logger.error(f"Failed to list tools for {server_name}: {e}")
            self._tools_cache[server_name] = []

    def all_tools(self) -> List[tuple[str, MCPRemoteTool]]:
        out: List[tuple[str, MCPRemoteTool]] = []
        for server_name, tools in self._tools_cache.items():
            for t in tools:
                out.append((server_name, t))
        return out

    @staticmethod
    def public_name(server_name: str, tool_name: str) -> str:
        if server_name.startswith("mcp_"):
            return f"{server_name}_{tool_name}"
        return f"mcp_{server_name}_{tool_name}"

    def resolve_tool(self, public_tool_name: str) -> Optional[tuple[str, str]]:
        if not self._config:
            return None
        for server_name in self._config.mcpServers.keys():
            prefix = server_name if server_name.startswith("mcp_") else f"mcp_{server_name}"
            if public_tool_name.startswith(prefix + "_"):
                return server_name, public_tool_name[len(prefix) + 1:]
        return None

    async def call_tool(self, public_tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        try:
            resolved = self.resolve_tool(public_tool_name)
            if not resolved:
                return ToolResult(success=False, message=f"Cannot resolve MCP tool: {public_tool_name}")
            server_name, original_name = resolved
            session = self._clients.get(server_name)
            if not session:
                return ToolResult(success=False, message=f"MCP server {server_name} not connected")

            result = await session.call_tool(original_name, arguments)
            if result is None:
                return ToolResult(success=True, data="OK")
            content_parts: List[str] = []
            if hasattr(result, "content") and result.content:
                for item in result.content:
                    if hasattr(item, "text"):
                        content_parts.append(item.text)
                    else:
                        content_parts.append(str(item))
            return ToolResult(
                success=True,
                data="\n".join(content_parts) if content_parts else "OK",
            )
        except Exception as e:
            logger.error(f"MCP tool call {public_tool_name} failed: {e}")
            return ToolResult(success=False, message=f"MCP tool failed: {e}")

    async def cleanup(self):
        try:
            await self._exit_stack.aclose()
            self._clients.clear()
            self._tools_cache.clear()
            self._initialized = False
        except Exception as e:
            logger.error(f"MCP cleanup failed: {e}")


class MCPToolkit(BaseToolkit):
    """Exposes remote MCP tools as local Tool objects."""

    name: str = "mcp"

    def __init__(self) -> None:
        super().__init__()
        self.manager: Optional[MCPClientManager] = None
        self._initialized = False

    async def initialized(self, config: Optional[MCPConfig] = None) -> None:
        if self._initialized:
            return
        self.manager = MCPClientManager(config)
        await self.manager.initialize()
        self._build_tools()
        self._initialized = True

    def _build_tools(self) -> None:
        if not self.manager:
            return
        for server_name, remote in self.manager.all_tools():
            public = MCPClientManager.public_name(server_name, remote.name)
            schema = remote.inputSchema or {"type": "object", "properties": {}}
            description = f"[{server_name}] {remote.description or remote.name}"
            tool_obj = Tool(
                toolkit=self,
                name=public,
                description=description,
                input_schema=schema,
                fn=self._make_invoker(public),
            )
            self._add_tool(tool_obj)

    def _make_invoker(self, public_name: str):
        async def _invoke(**kwargs: Any) -> ToolResult:
            assert self.manager is not None
            return await self.manager.call_tool(public_name, kwargs)

        return _invoke

    async def cleanup(self) -> None:
        if self.manager:
            await self.manager.cleanup()
