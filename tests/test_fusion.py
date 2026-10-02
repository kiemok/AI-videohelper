"""数据融合单测：B站/抖音原始字段 → 统一数据模型的映射与容错。"""

from __future__ import annotations

from datetime import date, datetime

from app.collect import fusion as F


# ---------------------------------------------------------------------- #
# 基础类型转换
# ---------------------------------------------------------------------- #
def test_to_int_accepts_text_and_defaults():
    assert F.to_int("1,234") == 1234
    assert F.to_int(None) == 0
    assert F.to_int("abc", default=-1) == -1


def test_to_datetime_handles_unix_and_iso():
    assert F.to_datetime(1758931200) is not None, "应支持 Unix 时间戳"
    parsed = F.to_datetime("2026-09-28 10:30:00")
    assert isinstance(parsed, datetime) and parsed.year == 2026
    assert F.to_datetime("") is None


def test_to_date_parses_iso():
    assert F.to_date("2026-09-28") == date(2026, 9, 28)
    assert F.to_date("非法日期") is None


def test_extract_hashtags_from_text():
    tags = F.extract_hashtags("第一次尝试citywalk #城市 #生活方式")
    assert "城市" in tags and "生活方式" in tags


# ---------------------------------------------------------------------- #
# 作品映射
# ---------------------------------------------------------------------- #
def test_normalize_bilibili_video():
    payload = F.normalize_video(
        "bilibili",
        {
            "bvid": "BV1TEST",
            "title": "手写笔记电子化",
            "desc": "我的完整流程",
            "tag": "数码,效率",
            "duration": 480,
            "pubdate": 1758931200,
            "owner": {"mid": 10086, "name": "数码小美"},
            "stat": {"view": 1000, "like": 100},
        },
    )
    assert payload["platform"] == "bilibili"
    assert payload["platform_video_id"] == "BV1TEST"
    assert payload["account_platform_id"] == "10086"
    assert payload["title"] == "手写笔记电子化"
    assert payload["tags"] == ["数码", "效率"]
    assert payload["duration_sec"] == 480
    assert payload["video_url"].endswith("/video/BV1TEST")


def test_normalize_douyin_video_uses_desc_as_title_and_hashtags():
    payload = F.normalize_video(
        "douyin",
        {
            "aweme_id": "7400000000000000001",
            "desc": "搬家第7天 #家居 #生活方式",
            "duration": 15000,  # 毫秒
            "create_time": 1758931200,
            "author": {"uid": "douyin_user_1", "nickname": "美美Vlog"},
            "statistics": {"play_count": 41997, "digg_count": 1650},
        },
    )
    assert payload["platform_video_id"] == "7400000000000000001"
    assert payload["account_platform_id"] == "douyin_user_1"
    assert payload["title"].startswith("搬家第7天")
    assert payload["duration_sec"] == 15, "抖音 duration 是毫秒，应换算为秒"
    assert "家居" in payload["tags"], "正文里的 #话题 应被提取为标签"


# ---------------------------------------------------------------------- #
# 快照映射
# ---------------------------------------------------------------------- #
def test_normalize_bilibili_snapshot_from_nested_stat():
    snapshot = F.normalize_snapshot(
        "bilibili",
        {"stat": {"view": 1500, "like": 120, "reply": 30, "share": 8, "favorite": 40, "danmaku": 5}},
        stat_date=date(2026, 9, 28),
    )
    assert snapshot["stat_date"] == date(2026, 9, 28)
    assert snapshot["view_count"] == 1500
    assert snapshot["comment_count"] == 30, "B站 reply 应映射为 comment_count"
    assert snapshot["favorite_count"] == 40


def test_normalize_snapshot_accepts_flat_unified_fields():
    snapshot = F.normalize_snapshot(
        "bilibili",
        {"view_count": "1,000", "like_count": 50, "stat_date": "2026-09-28"},
    )
    assert snapshot["view_count"] == 1000
    assert str(snapshot["stat_date"])[:10] == "2026-09-28"


def test_normalize_douyin_snapshot_falls_back_to_passed_date():
    snapshot = F.normalize_snapshot(
        "douyin",
        {"statistics": {"play_count": 500, "digg_count": 20, "comment_count": 3}},
        stat_date="2026-09-28",
    )
    assert snapshot["view_count"] == 500
    assert str(snapshot["stat_date"])[:10] == "2026-09-28"


# ---------------------------------------------------------------------- #
# 账号与评论
# ---------------------------------------------------------------------- #
def test_normalize_account_both_platforms():
    bili = F.normalize_account("bilibili", {"mid": 10086, "name": "数码小美", "follower": 1200})
    douyin = F.normalize_account("douyin", {"uid": "u1", "nickname": "美美Vlog", "follower_count": 800})

    assert bili["platform_account_id"] == "10086"
    assert bili["nickname"] == "数码小美"
    assert douyin["platform_account_id"] == "u1"
    assert douyin["nickname"] == "美美Vlog"


def test_normalize_comment_both_platforms():
    bili = F.normalize_comment(
        "bilibili", {"rpid": 1, "message": "讲得很清楚", "like": 12, "member": {"uname": "观众A"}}
    )
    douyin = F.normalize_comment(
        "douyin", {"cid": "c1", "text": "真香，已收藏", "digg_count": 8, "user": {"nickname": "观众B"}}
    )

    assert bili["platform_comment_id"] == "1"
    assert bili["content"] == "讲得很清楚"
    assert douyin["platform_comment_id"] == "c1"
    assert douyin["content"] == "真香，已收藏"
