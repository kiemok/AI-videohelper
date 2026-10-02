"""MCP（Model Context Protocol）客户端：连接外部工具服务器并调用其工具。

基于官方 ``mcp`` SDK，支持两种传输：

- ``stdio``：本地命令启动的服务器（python / npx / uvx …）
- ``sse``  ：远程 HTTP/SSE 服务器

SDK 是异步接口，这里统一封装为**同步函数**，供界面线程池中的任务直接调用：
每次调用按需建立会话、执行、关闭，避免跨线程事件循环带来的复杂度。

调用链：配置服务器 → AI 咨询时把工具列表交给大模型（function calling）
→ 模型选择工具 → 本地执行 → 结果回传模型 → 生成最终回答。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import McpServerSettings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

#: 工具名前缀分隔符：``{server}__{tool}``（避免多个服务器的同名工具冲突）
TOOL_NAME_SEP = "__"


class McpError(RuntimeError):
    """MCP 连接或调用失败。"""


@dataclass
class McpTool:
    """一个来自 MCP 服务器的工具。"""

    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    #: ASCII 安全的调用名（服务端/模型侧要求 ``^[a-zA-Z0-9_-]+$``），
    #: 由 ``collect_toolbox`` 按「服务器 + 工具」生成并去重；展示时仍用中文原名。
    alias: str = ""

    @property
    def qualified(self) -> str:
        return self.alias or f"{self.server}{TOOL_NAME_SEP}{self.name}"

    def to_openai_spec(self) -> dict[str, Any]:
        """转成 OpenAI function-calling 的 tools 定义。"""
        schema = self.input_schema or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.qualified[:64],
                "description": (self.description or f"{self.server} 提供的工具 {self.name}")[:1000],
                "parameters": schema,
            },
        }


def _parse_tool(server: str, raw: Any) -> McpTool:
    return McpTool(
        server=server,
        name=str(getattr(raw, "name", "") or ""),
        description=str(getattr(raw, "description", "") or ""),
        input_schema=dict(getattr(raw, "inputSchema", None) or {}),
    )


def _content_to_text(result: Any) -> str:
    """把 MCP 调用结果转成纯文本。"""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
        else:
            parts.append(f"[{getattr(item, 'type', '内容')}]")
    payload = "\n".join(parts) or "（工具返回空结果）"
    if getattr(result, "isError", False):
        return "工具返回错误：" + payload
    return payload


# --------------------------------------------------------------------------- #
# 异步核心（被同步函数包裹）
# --------------------------------------------------------------------------- #
async def _run_in_session(settings: McpServerSettings, handler, timeout: int):  # noqa: ANN001
    try:
        from mcp import ClientSession
    except ImportError as exc:  # pragma: no cover - 依赖未安装时的兜底
        raise McpError("未安装 mcp SDK，请先执行：pip install mcp") from exc

    transport = (settings.transport or "stdio").lower()
    if transport == "sse":
        try:
            from mcp.client.sse import sse_client
        except ImportError as exc:  # pragma: no cover
            raise McpError("当前 mcp SDK 不支持 SSE 传输，请改用 stdio") from exc
        async with sse_client(settings.url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await asyncio.wait_for(handler(session), timeout)

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {str(k): str(v) for k, v in (settings.env or {}).items()} or None
    params = StdioServerParameters(
        command=settings.command.strip(),
        args=[str(a) for a in (settings.args or [])],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await asyncio.wait_for(handler(session), timeout)


def list_tools(settings: McpServerSettings, timeout: int | None = None) -> list[McpTool]:
    """连接服务器并列出其工具（同步）。"""
    if not settings.is_configured():
        raise McpError("配置不完整：stdio 需要 command，SSE 需要 url")
    server_name = settings.name.strip() or (settings.command or "mcp")
    limit = timeout or settings.timeout or 30

    async def handler(session) -> list[McpTool]:  # noqa: ANN001
        result = await session.list_tools()
        return [_parse_tool(server_name, tool) for tool in (getattr(result, "tools", None) or [])]

    try:
        return asyncio.run(_run_in_session(settings, handler, limit))
    except McpError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转为可读错误
        raise McpError(f"连接 MCP 服务器失败：{exc}") from exc


def call_tool(
    settings: McpServerSettings,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> str:
    """调用服务器上的某个工具（同步），返回文本结果。"""
    if not settings.is_configured():
        raise McpError("配置不完整：stdio 需要 command，SSE 需要 url")
    limit = timeout or settings.timeout or 30

    async def handler(session) -> str:  # noqa: ANN001
        result = await session.call_tool(tool_name, dict(arguments or {}))
        return _content_to_text(result)

    try:
        return asyncio.run(_run_in_session(settings, handler, limit))
    except McpError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise McpError(f"调用工具 {tool_name} 失败：{exc}") from exc


def test_connection(settings: McpServerSettings) -> tuple[bool, str]:
    """连接测试（界面按钮用）。"""
    if not settings.is_configured():
        return False, "配置不完整：stdio 需要 command，SSE 需要 url"
    try:
        tools = list_tools(settings)
    except McpError as exc:
        return False, str(exc)
    if not tools:
        return True, "连接成功，但该服务器未提供任何工具"
    names = "、".join(tool.name for tool in tools[:6])
    suffix = "…" if len(tools) > 6 else ""
    return True, f"连接成功，发现 {len(tools)} 个工具：{names}{suffix}"


# --------------------------------------------------------------------------- #
# 多服务器聚合
# --------------------------------------------------------------------------- #
@dataclass
class McpToolbox:
    """已启用服务器的工具集合（供 AI 咨询使用）。"""

    tools: list[McpTool] = field(default_factory=list)
    bindings: dict[str, McpServerSettings] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def specs(self) -> list[dict[str, Any]]:
        return [tool.to_openai_spec() for tool in self.tools]

    def call(self, qualified_name: str, arguments: dict[str, Any] | None = None) -> str:
        """按限定名调用工具，失败时返回可读的错误文本（供回传模型）。"""
        tool = next((t for t in self.tools if t.qualified == qualified_name), None)
        settings = self.bindings.get(qualified_name)
        if tool is None or settings is None:
            return f"未找到工具 {qualified_name}"
        try:
            result = call_tool(settings, tool.name, arguments)
        except McpError as exc:
            logger.warning("MCP 工具调用失败 %s: %s", qualified_name, exc)
            return f"调用失败：{exc}"
        return result[:6000]

    def describe(self) -> str:
        if not self.tools:
            return "未启用任何 MCP 工具"
        servers = sorted({tool.server for tool in self.tools})
        return f"{len(self.tools)} 个工具（来自 {len(servers)} 个服务器：{'、'.join(servers)}）"


def _safe_name(text: str, fallback: str, limit: int = 40) -> str:
    """把任意名称转成 ASCII 安全标识（中文服务器名/工具名也能用）。"""
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", (text or "").strip()).strip("_")
    return cleaned[:limit] or fallback


def _unique_alias(base: str, used: set[str]) -> str:
    """保证别名唯一（不同服务器可能有同名工具）。"""
    candidate = base[:64]
    suffix = 2
    while candidate in used:
        candidate = f"{base[:58]}_{suffix}"
        suffix += 1
    return candidate


def collect_toolbox(servers: list[McpServerSettings]) -> McpToolbox:
    """汇总所有已启用服务器的工具；单个服务器失败不影响其它服务器。"""
    box = McpToolbox()
    used_aliases: set[str] = set()
    for index, settings in enumerate(servers or [], 1):
        if not settings.enabled or not settings.is_configured():
            continue
        try:
            tools = list_tools(settings)
        except McpError as exc:
            box.errors.append(f"{settings.name or settings.command}：{exc}")
            logger.warning("MCP 服务器不可用 %s：%s", settings.name, exc)
            continue
        server_key = _safe_name(settings.name or settings.command, f"server{index}")
        for tool_index, tool in enumerate(tools, 1):
            tool.alias = _unique_alias(
                f"{server_key}{TOOL_NAME_SEP}{_safe_name(tool.name, f'tool{tool_index}')}",
                used_aliases,
            )
            used_aliases.add(tool.alias)
            box.tools.append(tool)
            box.bindings[tool.alias] = settings
    return box
