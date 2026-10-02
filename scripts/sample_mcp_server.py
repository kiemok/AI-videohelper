"""示例 MCP 服务器：把本机数据分析能力暴露给 AI 咨询。

用途：

1. **验证 MCP 集成**（纯 Python，不需要 node/npx，任何环境都能跑通）；
2. 作为你自建 MCP 服务器的**模板** —— 换掉工具实现即可接入自己的数据源。

在软件「技能与工具」页新增 MCP 服务器时按下表填写：

| 字段 | 值 |
| --- | --- |
| 名称 | 本地数据助手 |
| 传输 | stdio |
| 命令 | ``<项目根>\\.venv\\Scripts\\python.exe`` |
| 参数 | ``scripts/sample_mcp_server.py`` |
| 环境变量 | （可留空；如需指定数据库可加 ``CCD_CONFIG_PATH``）|

注意：MCP 的 stdio 传输使用 **stdout** 传 JSON-RPC，因此本脚本的日志一律写到 stderr。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# 日志必须走 stderr，否则会污染 MCP 的 stdout 协议流
logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.db.repository import latest_analysis, list_comments, list_videos  # noqa: E402

server = MCPServer(
    name="本地数据助手",
    instructions="提供本机数据库中的作品、评论与平台对比数据，供创作者的数据咨询使用。",
)


def _db_url() -> str:
    return load_settings().resolved_db_url()


@server.tool(description="查询本地库中累计播放最高的作品；platform 可填 bilibili / douyin，留空表示全部")
def query_top_videos(platform: str = "", limit: int = 5) -> str:
    try:
        size = max(1, min(int(limit or 5), 20))
    except (TypeError, ValueError):
        size = 5
    rows = list_videos(_db_url(), platform=platform.strip() or None, limit=size)
    payload = [
        {
            "title": str(row.get("title", ""))[:50],
            "platform": row.get("platform"),
            "account": row.get("account"),
            "views": row.get("view_count"),
            "likes": row.get("like_count"),
            "comments": row.get("comment_count"),
        }
        for row in rows[:size]
    ]
    if not payload:
        return "本地库中没有匹配的作品（可能尚未导入数据）"
    return json.dumps(payload, ensure_ascii=False, indent=2)


@server.tool(description="按关键词查询评论样本，返回内容与情感标签；keyword 留空则返回最新评论")
def query_comments(keyword: str = "", limit: int = 10) -> str:
    try:
        size = max(1, min(int(limit or 10), 50))
    except (TypeError, ValueError):
        size = 10
    rows = list_comments(_db_url(), limit=300)
    key = keyword.strip()
    if key:
        rows = [row for row in rows if key in (row.get("content") or "")]
    payload = [
        {
            "content": str(row.get("content", ""))[:80],
            "sentiment": row.get("sentiment_label"),
            "likes": row.get("like_count"),
            "platform": row.get("platform"),
        }
        for row in rows[:size]
    ]
    if not payload:
        return "没有匹配的评论"
    return json.dumps(payload, ensure_ascii=False, indent=2)


@server.tool(description="读取最近一次分析结果的关键指标：双平台对比、传播健康度、评论情感分布与热词")
def query_latest_metrics() -> str:
    metrics = latest_analysis(_db_url()) or {}
    if not metrics:
        return "还没有分析结果，请先在软件里执行一次分析"
    sentiment = metrics.get("sentiment") or {}
    payload = {
        "stat_date": metrics.get("stat_date"),
        "headline": metrics.get("headline"),
        "platform_compare": metrics.get("platform_compare"),
        "sentiment_summary": {
            key: sentiment.get(key)
            for key in ("total", "positive_ratio", "negative_ratio", "avg_score")
        },
        "top_keywords": [item.get("word") for item in (metrics.get("keywords") or [])[:10]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    server.run(transport="stdio")
