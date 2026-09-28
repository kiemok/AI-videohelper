"""数据融合层：把双平台（B站 / 抖音）的异构字段归一化为统一数据模型。

融合规则集中在此处，新增平台时只需补充一组 ``normalize_*`` 分支：
- **账号**：``mid/uid`` → ``platform_account_id``，``follower/follower_count`` → ``follower_count`` …
- **作品**：``bvid/aweme_id`` → ``platform_video_id``，``desc`` → 标题/描述，``#话题`` → tags …
- **指标**：``stat.view / statistics.play_count`` → ``view_count``，``reply/comment_count`` → ``comment_count`` …
- **评论**：``rpid/cid`` → ``platform_comment_id``，``message/text`` → ``content`` …
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_HASHTAG_RE = re.compile(r"#([^\s#]+)")


def to_datetime(value: Any) -> datetime | None:
    """兼容 Unix 秒/毫秒时间戳、ISO 字符串与 datetime。"""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:  # 毫秒
            ts /= 1000.0
        return datetime.fromtimestamp(ts)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() and len(text) >= 9:
            return to_datetime(int(text))
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            logger.warning("无法解析时间字段: %r", value)
            return None
    return None


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def normalize_tags(value: Any) -> list[str]:
    """标签统一为列表：支持 ``"a|b"`` / 逗号分隔 / 平台原始列表。"""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    parts = re.split(r"[|,，;；]", text)
    return [p.strip() for p in parts if p.strip()]


def extract_hashtags(text: str) -> list[str]:
    return _HASHTAG_RE.findall(text or "")


# --------------------------------------------------------------------------- #
# 账号
# --------------------------------------------------------------------------- #
def normalize_account(platform: str, raw: dict[str, Any]) -> dict[str, Any]:
    """平台账号原始字段 → 统一 Account 字段。"""
    if platform == "bilibili":
        return {
            "platform": "bilibili",
            "platform_account_id": str(raw.get("mid") or raw.get("platform_account_id") or ""),
            "nickname": raw.get("name") or raw.get("nickname") or "",
            "follower_count": to_int(raw.get("follower", raw.get("follower_count"))),
            "following_count": to_int(raw.get("following", raw.get("following_count"))),
            "total_favorite": to_int(raw.get("total_favorited", raw.get("total_favorite"))),
            "verified": to_bool(raw.get("official_verify", raw.get("verified", False))),
            "signature": raw.get("sign") or raw.get("signature") or "",
            "home_url": raw.get("home_url") or "",
            "source": raw.get("source") or "sample",
            "extra": {"raw_provider": "bilibili"},
        }
    return {
        "platform": "douyin",
        "platform_account_id": str(raw.get("uid") or raw.get("platform_account_id") or ""),
        "nickname": raw.get("nickname") or raw.get("name") or "",
        "follower_count": to_int(raw.get("follower_count", raw.get("follower"))),
        "following_count": to_int(raw.get("following_count", raw.get("following"))),
        "total_favorite": to_int(raw.get("favoriting_count", raw.get("total_favorite"))),
        "verified": to_bool(
            raw.get("custom_verify") or raw.get("enterprise_verify_reason") or raw.get("verified", False)
        ),
        "signature": raw.get("signature") or raw.get("sign") or "",
        "home_url": raw.get("home_url") or "",
        "source": raw.get("source") or "sample",
        "extra": {"raw_provider": "douyin"},
    }


# --------------------------------------------------------------------------- #
# 作品
# --------------------------------------------------------------------------- #
def normalize_video(platform: str, raw: dict[str, Any]) -> dict[str, Any]:
    """平台作品原始字段 → 统一 Video 字段。"""
    if platform == "bilibili":
        bvid = str(raw.get("bvid") or raw.get("platform_video_id") or "")
        owner = raw.get("owner") or {}
        title = raw.get("title") or ""
        return {
            "platform": "bilibili",
            "platform_video_id": bvid,
            "account_platform_id": str(owner.get("mid") or raw.get("account_platform_id") or ""),
            "title": title,
            "description": raw.get("desc") or raw.get("description") or "",
            "tags": normalize_tags(raw.get("tag") or raw.get("tags")),
            "content_type": "video",
            "duration_sec": to_int(raw.get("duration", raw.get("duration_sec"))),
            "publish_time": to_datetime(raw.get("pubdate") or raw.get("publish_time")),
            "cover_url": raw.get("pic") or raw.get("cover_url") or "",
            "video_url": raw.get("video_url") or (f"https://www.bilibili.com/video/{bvid}" if bvid else ""),
            "topic": raw.get("topic") or "",
            "extra": {"aid": raw.get("aid"), "raw_provider": "bilibili"},
        }

    aweme_id = str(raw.get("aweme_id") or raw.get("platform_video_id") or "")
    author = raw.get("author") or {}
    desc = raw.get("desc") or raw.get("description") or ""
    cover = raw.get("cover") or {}
    cover_url = raw.get("cover_url") or ""
    if not cover_url and isinstance(cover, dict):
        urls = cover.get("url_list") or []
        cover_url = urls[0] if urls else ""
    duration_ms = to_int(raw.get("duration", raw.get("duration_sec")))
    duration_sec = raw.get("duration_sec")
    if duration_sec is None:
        duration_sec = duration_ms // 1000  # 抖音 duration 为毫秒
    images = raw.get("images") or []
    return {
        "platform": "douyin",
        "platform_video_id": aweme_id,
        "account_platform_id": str(author.get("uid") or raw.get("account_platform_id") or ""),
        "title": (raw.get("title") or desc)[:120],
        "description": desc,
        "tags": normalize_tags(raw.get("tags")) or extract_hashtags(desc),
        "content_type": "image_text" if images else "video",
        "duration_sec": to_int(duration_sec),
        "publish_time": to_datetime(raw.get("create_time") or raw.get("publish_time")),
        "cover_url": cover_url,
        "video_url": raw.get("video_url") or (f"https://www.douyin.com/video/{aweme_id}" if aweme_id else ""),
        "topic": raw.get("topic") or "",
        "extra": {"statistics_keys": sorted((raw.get("statistics") or {}).keys()), "raw_provider": "douyin"},
    }


# --------------------------------------------------------------------------- #
# 指标快照
# --------------------------------------------------------------------------- #
def normalize_snapshot(
    platform: str, raw: dict[str, Any], stat_date: date | str | None = None
) -> dict[str, Any]:
    """平台统计字段 → 统一快照字段。

    支持两种输入：平台上原始嵌套结构（``stat`` / ``statistics``），
    或已是统一字段的扁平 dict（CSV 导入）。
    """
    if platform == "bilibili":
        stat = raw.get("stat") or raw
        author_stat = raw.get("author_stat") or {}
        mapped = {
            "view_count": to_int(stat.get("view", stat.get("view_count"))),
            "like_count": to_int(stat.get("like", stat.get("like_count"))),
            "comment_count": to_int(stat.get("reply", stat.get("comment_count"))),
            "share_count": to_int(stat.get("share", stat.get("share_count"))),
            "favorite_count": to_int(stat.get("favorite", stat.get("favorite_count"))),
            "danmaku_count": to_int(stat.get("danmaku", stat.get("danmaku_count"))),
        }
        follower = author_stat.get("follower", raw.get("follower_count"))
    else:
        stat = raw.get("statistics") or raw
        author_stat = raw.get("author_stat") or {}
        mapped = {
            "view_count": to_int(stat.get("play_count", stat.get("view_count"))),
            "like_count": to_int(stat.get("digg_count", stat.get("like_count"))),
            "comment_count": to_int(stat.get("comment_count")),
            "share_count": to_int(stat.get("share_count")),
            "favorite_count": to_int(stat.get("collect_count", stat.get("favorite_count"))),
            "danmaku_count": to_int(stat.get("danmaku_count")),
        }
        follower = author_stat.get("follower_count", raw.get("follower_count"))

    resolved_date = to_date(stat_date or raw.get("stat_date")) or date.today()
    return {
        "platform": platform,
        "stat_date": resolved_date,
        "follower_gain": to_int(raw.get("follower_gain")),
        "follower_count": to_int(follower) if follower is not None else None,
        "raw": {"provider": platform, "payload": _shrink(raw)},
        **mapped,
    }


def to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        dt = to_datetime(text)
        return dt.date() if dt else None


def _shrink(payload: dict[str, Any], limit: int = 900) -> dict[str, Any]:
    """原样保留原始字段但限制体积，并保证 JSON 可序列化（date/datetime → 字符串）。"""
    import json

    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {}
    if len(text) > limit:
        return {"truncated": text[:limit]}
    return json.loads(text)


# --------------------------------------------------------------------------- #
# 评论
# --------------------------------------------------------------------------- #
def normalize_comment(platform: str, raw: dict[str, Any]) -> dict[str, Any]:
    """平台评论原始字段 → 统一 Comment 字段。"""
    if platform == "bilibili":
        member = raw.get("member") or {}
        content = raw.get("content") or {}
        text = raw.get("message") or (content.get("message") if isinstance(content, dict) else "") or ""
        return {
            "platform": "bilibili",
            "platform_comment_id": str(raw.get("rpid") or raw.get("platform_comment_id") or ""),
            "content": text,
            "user_nickname": raw.get("user_nickname") or member.get("uname") or "",
            "like_count": to_int(raw.get("like", raw.get("like_count"))),
            "publish_time": to_datetime(raw.get("ctime") or raw.get("publish_time")),
        }

    user = raw.get("user") or {}
    return {
        "platform": "douyin",
        "platform_comment_id": str(raw.get("cid") or raw.get("platform_comment_id") or ""),
        "content": raw.get("text") or raw.get("content") or "",
        "user_nickname": raw.get("user_nickname") or user.get("nickname") or "",
        "like_count": to_int(raw.get("digg_count", raw.get("like_count"))),
        "publish_time": to_datetime(raw.get("create_time") or raw.get("publish_time")),
    }
