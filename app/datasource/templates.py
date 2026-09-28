"""生成数据仓库模板：标准 CSV 结构 + 格式说明，便于用户按约定推送数据。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

ACCOUNT_HEADER = (
    "platform,platform_account_id,nickname,follower_count,following_count,"
    "total_favorite,verified,signature,home_url"
)
VIDEO_HEADER = (
    "platform,platform_video_id,account_platform_id,title,description,tags,"
    "content_type,duration_sec,publish_time,cover_url,video_url,topic"
)
SNAPSHOT_HEADER = (
    "platform,platform_video_id,stat_date,view_count,like_count,comment_count,"
    "share_count,favorite_count,danmaku_count,follower_gain"
)
COMMENT_HEADER = (
    "platform,platform_comment_id,platform_video_id,content,user_nickname,"
    "like_count,publish_time"
)

README_TEXT = """# 数据仓库格式约定

软件只负责**拉取并导入**本仓库的数据，不在软件内执行爬取。支持两种格式（可混用）。

## A. 标准 CSV（推荐，字段为统一模型）

```
accounts.csv                 平台账号
videos.csv                   作品（含所属账号 ID）
snapshots/YYYY-MM-DD.csv     每日累计指标快照（按日期分片，便于增量）
comments/YYYY-MM-DD.csv      评论（按日期分片）
```

- **accounts.csv**：platform, platform_account_id, nickname, follower_count, following_count,
  total_favorite, verified, signature, home_url
- **videos.csv**：platform, platform_video_id, account_platform_id, title, description, tags（用 | 分隔）,
  content_type, duration_sec, publish_time（YYYY-MM-DD HH:MM:SS）, cover_url, video_url, topic
- **snapshots/*.csv**：platform, platform_video_id, stat_date, view_count, like_count, comment_count,
  share_count, favorite_count, danmaku_count, follower_gain
- **comments/*.csv**：platform, platform_comment_id, platform_video_id, content, user_nickname,
  like_count, publish_time

> platform 取值为 `bilibili` 或 `douyin`；stat_date / publish_time 也可用文件名日期兜底。
> 也允许把 snapshots / comments 写成一个单文件（snapshots.csv / comments.csv）。

## B. 平台原始字段 JSON / JSONL（爬虫直接导出，无需转换）

```
bilibili/accounts.json     [{ "mid": 100001, "name": "...", "follower": 132000, ... }]
bilibili/videos.json       [{ "bvid": "BV1xx", "title": "...", "stat": {...}, "owner": {...} }]
bilibili/comments.json     [{ "rpid": "...", "message": "...", "member": {"uname": "..."} }]
douyin/accounts.json       [{ "uid": "200001", "nickname": "...", "follower_count": 286000 }]
douyin/videos.json         [{ "aweme_id": "7...", "desc": "...", "statistics": {...}, "author": {...} }]
douyin/comments.json       [{ "cid": "...", "text": "...", "digg_count": 12 }]
```

原始字段会由软件内的融合映射（`app/collect/fusion.py`）自动归一化为统一模型，
无需你手动改字段名。`.jsonl`（每行一个对象）同样支持；
若一个作品对象里带 `snapshots` / `stats` 数组，会被解析为该作品的每日快照。

## C. 更新方式

- 仓库直接推送到本仓库即可，软件端设置页/数据仓库页点击「拉取 / 更新数据」；
- 若开启了「每日自动拉取」，定时任务会先拉取再分析。
"""


def write_data_templates(out_dir: Path | str) -> dict[str, Path]:
    """在指定目录写出模板文件（不覆盖已有文件）。"""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    written: dict[str, Path] = {}

    targets = {
        "accounts.csv": (ACCOUNT_HEADER, f"bilibili,100001,示例账号,132000,120,86000,1,简介,https://space.bilibili.com/100001"),
        "videos.csv": (VIDEO_HEADER, f"bilibili,BV1example,100001,示例标题,示例简介,数码|实测,video,215,{today} 20:00:00,,,数码测评"),
        f"snapshots/{today}.csv": (SNAPSHOT_HEADER, f"bilibili,BV1example,{today},41000,3200,210,190,900,260,35"),
        f"comments/{today}.csv": (COMMENT_HEADER, f"bilibili,bi_c_example,BV1example,讲得太清楚了,路过的风,88,{today} 21:10:00"),
    }
    for relative, (header, sample) in targets.items():
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header + "\n" + sample + "\n", encoding="utf-8-sig")
        written[relative] = path

    readme = root / "DATA_FORMAT.md"
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")
        written["DATA_FORMAT.md"] = readme

    logger.info("数据模板已生成：%d 个文件 -> %s", len(written), root)
    return written
