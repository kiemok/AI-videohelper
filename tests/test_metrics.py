"""指标计算的单元测试：派生指标口径、健康度范围、漏斗与日期序列。

全部使用合成数据，不依赖数据库与网络。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analysis import metrics as M


def snapshot_rows(days: int = 10, start: date = date(2026, 9, 1), step: int = 100) -> list[dict]:
    """构造一个 B 站作品的逐日累计快照（用于验证「累计 → 当日增量」的换算）。"""
    rows: list[dict] = []
    for index in range(days):
        rows.append(
            {
                "video_id": 1,
                "platform": "bilibili",
                "platform_video_id": "BV1TEST",
                "title": "测试作品",
                "account_nickname": "测试账号",
                "publish_time": start,
                "stat_date": start + timedelta(days=index),
                "view_count": 1000 + step * index,
                "like_count": 100 + index * 5,
                "comment_count": 10 + index,
                "share_count": 5 + index,
                "favorite_count": 20 + index,
                "danmaku_count": index,
                "follower_gain": 3 + index,
            }
        )
    return rows


# ---------------------------------------------------------------------- #
# 基础工具
# ---------------------------------------------------------------------- #
def test_safe_div_handles_zero_and_none():
    assert M.safe_div(10, 2) == 5
    assert M.safe_div(10, 0) == 0.0
    assert M.safe_div(0, 0) == 0.0


def test_snapshots_to_frame_empty_input():
    frame = M.snapshots_to_frame([])
    assert frame.empty
    assert {"video_id", "platform", "stat_date"} <= set(frame.columns)


# ---------------------------------------------------------------------- #
# 派生指标
# ---------------------------------------------------------------------- #
def test_compute_video_daily_converts_cumulative_to_daily():
    frame = M.snapshots_to_frame(snapshot_rows(days=5))
    enriched = M.compute_video_daily(frame)

    assert len(enriched) == 5
    # 首日没有前一日可比 → 当日新增取累计值本身
    assert int(enriched.iloc[0]["daily_views"]) == 1000
    # 之后每天累计 +100 → 当日新增 100
    assert int(enriched.iloc[1]["daily_views"]) == 100
    assert int(enriched.iloc[4]["daily_views"]) == 100


def test_engagement_rate_and_growth_rate_definitions():
    frame = M.snapshots_to_frame(snapshot_rows(days=4))
    enriched = M.compute_video_daily(frame)

    row = enriched.iloc[2]
    # 行级 engagement_rate 是**小数**口径：当日互动 / 当日播放
    assert row["engagement_rate"] == pytest.approx(
        row["daily_engagement"] / row["daily_views"], rel=1e-3
    )
    # 行级 growth_rate 是「当日新增播放 / 前一日累计播放」的比值（恒为正、远小于 1）
    assert row["growth_rate"] == pytest.approx(100 / 1100, rel=1e-3)
    # 聚合视图（daily_series）里的 engagement_rate 才是百分数
    series = M.daily_series(enriched)
    assert series[1]["engagement_rate"] == pytest.approx(
        series[1]["daily_engagement"] / series[1]["daily_views"] * 100, rel=1e-3
    )


def test_growth_rate_shrinks_when_daily_views_drop():
    rows = snapshot_rows(days=4)
    rows[3]["view_count"] = rows[2]["view_count"] + 20  # 当日新增从 100 降到 20
    enriched = M.compute_video_daily(M.snapshots_to_frame(rows))

    assert enriched.iloc[3]["daily_views"] < enriched.iloc[2]["daily_views"]
    assert enriched.iloc[3]["growth_rate"] < enriched.iloc[2]["growth_rate"]
    assert enriched.iloc[3]["growth_rate"] > 0, "比值口径恒为正，衰减由比值下降体现"


def test_health_score_within_range():
    frame = M.snapshots_to_frame(snapshot_rows(days=6))
    enriched = M.compute_video_daily(frame)
    scores = [M.health_score(row) for _, row in enriched.iterrows()]
    assert scores, "至少应有一条快照"
    assert all(0.0 <= score <= 100.0 for score in scores)


# ---------------------------------------------------------------------- #
# 聚合视图
# ---------------------------------------------------------------------- #
def test_daily_series_length_and_fields():
    frame = M.snapshots_to_frame(snapshot_rows(days=7))
    enriched = M.compute_video_daily(frame)
    series = M.daily_series(enriched)

    assert len(series) == 7
    assert {"stat_date", "daily_views", "daily_engagement", "engagement_rate", "health_score"} <= set(
        series[0]
    )
    assert isinstance(series[0]["stat_date"], str), "序列日期为字符串，便于前端展示"


def test_platform_compare_splits_platforms():
    rows = snapshot_rows(days=3)
    for row in rows:
        row["platform"] = "douyin"
        row["video_id"] = 2
        row["platform_video_id"] = "DOUYIN1"
    mixed = snapshot_rows(days=3) + rows
    enriched = M.compute_video_daily(M.snapshots_to_frame(mixed))
    compare = M.platform_compare(enriched, stat_date=date(2026, 9, 3))

    assert set(compare) >= {"bilibili", "douyin"}
    for platform in ("bilibili", "douyin"):
        assert compare[platform]["daily_views"] > 0
        assert compare[platform]["video_count"] == 1
        assert "week_daily_views" in compare[platform], "应同时给出近 7 日口径"


def test_funnel_summary_is_monotonic():
    frame = M.snapshots_to_frame(snapshot_rows(days=5))
    enriched = M.compute_video_daily(frame)
    funnel = M.funnel_summary(enriched)

    assert len(funnel) >= 3
    for item in funnel:
        assert {"label", "value", "ratio"} <= set(item)
    values = [item["value"] for item in funnel]
    assert values == sorted(values, reverse=True), "漏斗应逐级收敛（播放 ≥ 点赞 ≥ 互动 ≥ 涨粉）"


def test_headline_contains_core_kpis():
    frame = M.snapshots_to_frame(snapshot_rows(days=5))
    enriched = M.compute_video_daily(frame)
    head = M.headline(enriched, date(2026, 9, 5))

    assert {"daily_views", "engagement_rate", "health_score", "follower_gain", "video_count"} <= set(head)
    assert head["stat_date"] == "2026-09-05"
