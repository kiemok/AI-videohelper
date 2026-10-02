"""MCP（Model Context Protocol）模块：把外部工具服务器接入 AI 咨询。

- ``config.McpServerSettings``：服务器配置（stdio / SSE），随应用配置持久化
- ``client.McpToolbox``：聚合已启用服务器的工具，转成 OpenAI function-calling 定义并执行调用
"""

from app.mcp.client import (
    TOOL_NAME_SEP,
    McpError,
    McpTool,
    McpToolbox,
    call_tool,
    collect_toolbox,
    list_tools,
    test_connection,
)

__all__ = [
    "TOOL_NAME_SEP",
    "McpError",
    "McpTool",
    "McpToolbox",
    "call_tool",
    "collect_toolbox",
    "list_tools",
    "test_connection",
]
