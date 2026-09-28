"""指标计算模块（Pandas / NumPy 实现）。

指标定义（与论文/文档保持一致）：

- **当日新增播放** ``daily_views``：相邻两天累计播放量差值，首日取累计值。
- **互动数** ``engagement``：点赞 + 评论 + 分享 + 收藏 + 弹幕。
- **互动率** ``engagement_rate``：当日新增互动 / 当日新增播放（当日口径，对趋势更敏感）；
  另有 ``cum_engagement_rate`` 为累计互动 / 累计播放。
- **日增长率** ``growth_rate``：当日新增播放 / 前一日累计播放。
- **传播健康度** ``health_score``（0~100）：互动率、收藏率（沉淀价值）、分享率（破圈能力）、
  增长率四项归一化后加权求和，权重见 ``HEALTH_WEIGHTS``。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

STAT_COLUMNS = ("view_count", "like_count", "comment_count", "share_count", "favorite_count", "danmaku_count")
DELTA_COLUMNS = tuple("d_" + c for c in STAT_COLUMNS)

#: 传播健康度权重（互动率 / 收藏率 / 分享率 / 增长率）
HEALTH_WEIGHTS = {"engagement": 0.40, "favorite": 0.20, "share": 0.20, "growth": 0.20}
#: 各分项归一化参考上限（达到该值记满分）
HEALTH_REFERENCE = {"engagement": 0.10, "favorite": 0.025, "share": 0.012, "growth": 0.20}


def safe_div(numerator: float, denominator: float) -> float:
    """安全除法：分母为 0 时返回 0.0。"""
    try:
        denominator = float(denominator)
        if denominator == 0 or np.isnan(denominator):
            return 0.0
        return float(numerator) / denominator
    except (TypeError, ValueError):
        return 0.0


def snapshots_to_frame(snapshots: list[dict[str, Any]]) -> pd.DataFrame:
    """快照列表 → 规范化的 DataFrame（含发布时间、账号、标题等维度）。"""
    if not snapshots:
        return pd.DataFrame(columns=["video_id", "platform", "stat_date", *STAT_COLUMNS])
    df = pd.DataFrame(snapshots)
    df["stat_date"] = pd.to_datetime(df["stat_date"]).dt.date
    for col in STAT_COLUMNS + ("follower_gain",):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def compute_video_daily(df: pd.DataFrame) -> pd.DataFrame:
    """按作品分组计算当日增量与派生指标。"""
    if df.empty:
        return df.assign(
            daily_views=pd.Series(dtype="int64"),
            daily_engagement=pd.Series(dtype="int64"),
            engagement_rate=pd.Series(dtype="float64"),
            growth_rate=pd.Series(dtype="float64"),
            health_score=pd.Series(dtype="float64"),
        )
    out = df.sort_values(["video_id", "stat_date"]).copy()
    grouped = out.groupby("video_id", sort=False)

    for col in STAT_COLUMNS:
        prev = grouped[col].shift(1).astype("float64")
        delta = (out[col].astype("float64") - prev).clip(lower=0)
        delta = delta.where(prev.notna(), out[col].astype("float64"))
        out["d_" + col] = delta.fillna(0)

    out["prev_view"] = grouped["view_count"].shift(1).astype("float64")
    out["daily_views"] = out["d_view_count"]
    out["daily_engagement"] = out[list(DELTA_COLUMNS[1:])].sum(axis=1)
    out["engagement"] = out[["like_count", "comment_count", "share_count", "favorite_count", "danmaku_count"]].sum(axis=1)

    out["engagement_rate"] = np.where(
        out["daily_views"] > 0, out["daily_engagement"] / out["daily_views"].replace(0, np.nan), 0.0
    )
    out["cum_engagement_rate"] = np.where(
        out["view_count"] > 0, out["engagement"] / out["view_count"].replace(0, np.nan), 0.0
    )
    out["favorite_rate"] = np.where(
        out["daily_views"] > 0, out["d_favorite_count"] / out["daily_views"].replace(0, np.nan), 0.0
    )
    out["share_rate"] = np.where(
        out["daily_views"] > 0, out["d_share_count"] / out["daily_views"].replace(0, np.nan), 0.0
    )
    out["comment_rate"] = np.where(
        out["daily_views"] > 0, out["d_comment_count"] / out["daily_views"].replace(0, np.nan), 0.0
    )
    out["growth_rate"] = np.where(
        out["prev_view"].fillna(0) > 0,
        out["daily_views"] / out["prev_view"].replace(0, np.nan),
        0.0,
    )

    out[["engagement_rate", "cum_engagement_rate", "favorite_rate", "share_rate", "comment_rate", "growth_rate"]] = out[
        ["engagement_rate", "cum_engagement_rate", "favorite_rate", "share_rate", "comment_rate", "growth_rate"]
    ].fillna(0.0)

    out["health_score"] = out.apply(health_score, axis=1)
    return out


def health_score(row: pd.Series) -> float:
    """传播健康度（0~100）。"""
    parts = {
        "engagement": safe_div(row.get("engagement_rate", 0), HEALTH_REFERENCE["engagement"]),
        "favorite": safe_div(row.get("favorite_rate", 0), HEALTH_REFERENCE["favorite"]),
        "share": safe_div(row.get("share_rate", 0), HEALTH_REFERENCE["share"]),
        "growth": safe_div(max(0.0, row.get("growth_rate", 0)), HEALTH_REFERENCE["growth"]),
    }
    score = sum(HEALTH_WEIGHTS[k] * min(1.0, max(0.0, v)) for k, v in parts.items())
    return round(score * 100, 2)


def daily_series(df_enriched: pd.DataFrame) -> list[dict[str, Any]]:
    """按日期聚合的时序数据（供趋势图使用）。"""
    if df_enriched.empty:
        return []
    grouped = df_enriched.groupby("stat_date")
    rows: list[dict[str, Any]] = []
    for stat_date, part in grouped:
        views = int(part["daily_views"].sum())
        engagement = int(part["daily_engagement"].sum())
        rows.append(
            {
                "stat_date": stat_date.isoformat() if isinstance(stat_date, date) else str(stat_date),
                "daily_views": views,
                "total_views": int(part["view_count"].sum()),
                "daily_engagement": engagement,
                "engagement_rate": round(safe_div(engagement, views) * 100, 3),
                "health_score": round(float(part["health_score"].mean()), 2),
                "follower_gain": int(part["follower_gain"].sum()),
                "video_count": int(part["video_id"].nunique()),
            }
        )
    return sorted(rows, key=lambda r: r["stat_date"])


def platform_compare(df_enriched: pd.DataFrame, stat_date: date | None = None) -> dict[str, dict[str, Any]]:
    """双平台对比：当日 + 近 7 日口径。"""
    if df_enriched.empty:
        return {}
    stat_date = stat_date or max(df_enriched["stat_date"])
    today_df = df_enriched[df_enriched["stat_date"] == stat_date]
    week_start = stat_date - timedelta(days=6)
    week_df = df_enriched[(df_enriched["stat_date"] >= week_start) & (df_enriched["stat_date"] <= stat_date)]

    result: dict[str, dict[str, Any]] = {}
    for platform, part in today_df.groupby("platform"):
        week_part = week_df[week_df["platform"] == platform]
        views = int(part["daily_views"].sum())
        engagement = int(part["daily_engagement"].sum())
        result[str(platform)] = {
            "stat_date": stat_date.isoformat(),
            "daily_views": views,
            "total_views": int(part["view_count"].sum()),
            "daily_engagement": engagement,
            "engagement_rate": round(safe_div(engagement, views) * 100, 3),
            "cum_engagement_rate": round(
                safe_div(part["engagement"].sum(), part["view_count"].sum()) * 100, 3
            ),
            "health_score": round(float(part["health_score"].mean()), 2),
            "follower_gain": int(part["follower_gain"].sum()),
            "video_count": int(part["video_id"].nunique()),
            "week_daily_views": int(week_part["daily_views"].sum()),
            "week_health_score": round(float(week_part["health_score"].mean()), 2) if not week_part.empty else 0.0,
        }
    return result


def daily_series_by_platform(df_enriched: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """按平台拆分的每日时序（供双平台对比趋势图使用）。"""
    if df_enriched.empty:
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for platform, part in df_enriched.groupby("platform"):
        rows: list[dict[str, Any]] = []
        for stat_date, day in part.groupby("stat_date"):
            views = int(day["daily_views"].sum())
            engagement = int(day["daily_engagement"].sum())
            rows.append(
                {
                    "stat_date": (
                        stat_date.isoformat() if isinstance(stat_date, date) else str(stat_date)
                    ),
                    "daily_views": views,
                    "daily_engagement": engagement,
                    "engagement_rate": round(safe_div(engagement, views) * 100, 3),
                    "health_score": round(float(day["health_score"].mean()), 2),
                    "follower_gain": int(day["follower_gain"].sum()),
                }
            )
        result[str(platform)] = sorted(rows, key=lambda r: r["stat_date"])
    return result


def funnel_summary(
    df_enriched: pd.DataFrame, stat_date: date | None = None
) -> list[dict[str, Any]]:
    """流量与价值转化漏斗（累计口径）。

    曝光展示（播放）→ 内容点赞 → 深度互动（评论/收藏/分享/弹幕）→ 关注转化（涨粉）。
    """
    if df_enriched.empty:
        return []
    stat_date = stat_date or max(df_enriched["stat_date"])
    today = df_enriched[df_enriched["stat_date"] == stat_date]
    views = int(today["view_count"].sum())
    likes = int(today["like_count"].sum())
    deep = int(
        today[["comment_count", "favorite_count", "share_count", "danmaku_count"]].sum(axis=1).sum()
    )
    follows = int(today["follower_gain"].sum())
    rows = (
        ("曝光展示 → 完播（Plays）", views),
        ("内容点赞（Likes）", likes),
        ("深度互动（评论 / 收藏 / 分享）", deep),
        ("关注转化（Followers Added）", follows),
    )
    return [
        {"label": label, "value": value, "ratio": round(safe_div(value, views) * 100, 3)}
        for label, value in rows
    ]


def summarize_videos(df_enriched: pd.DataFrame, stat_date: date | None = None, top_n: int = 8) -> list[dict[str, Any]]:
    """作品榜：按当日新增播放排序，含互动率、健康度、日增长率。"""
    if df_enriched.empty:
        return []
    stat_date = stat_date or max(df_enriched["stat_date"])
    latest = df_enriched[df_enriched["stat_date"] == stat_date].copy()
    latest["title_short"] = latest["title"].astype(str).str.slice(0, 40)
    latest = latest.sort_values("daily_views", ascending=False).head(top_n)
    return [
        {
            "title": row["title"],
            "platform": row["platform"],
            "account": row.get("account", ""),
            "stat_date": str(row["stat_date"]),
            "view_count": int(row["view_count"]),
            "daily_views": int(row["daily_views"]),
            "daily_engagement": int(row["daily_engagement"]),
            "engagement_rate": round(float(row["engagement_rate"]) * 100, 3),
            "growth_rate": round(float(row["growth_rate"]) * 100, 2),
            "health_score": float(row["health_score"]),
        }
        for _, row in latest.iterrows()
    ]


def summarize_accounts(df_enriched: pd.DataFrame, stat_date: date | None = None) -> list[dict[str, Any]]:
    """账号维度汇总（近 7 日口径）。"""
    if df_enriched.empty:
        return []
    stat_date = stat_date or max(df_enriched["stat_date"])
    week = df_enriched[(df_enriched["stat_date"] <= stat_date) & (df_enriched["stat_date"] > stat_date - timedelta(days=7))]
    rows: list[dict[str, Any]] = []
    for (account, platform), part in week.groupby(["account", "platform"]):
        views = int(part["daily_views"].sum())
        engagement = int(part["daily_engagement"].sum())
        rows.append(
            {
                "account": account,
                "platform": platform,
                "week_daily_views": views,
                "week_engagement": engagement,
                "engagement_rate": round(safe_div(engagement, views) * 100, 3),
                "health_score": round(float(part["health_score"].mean()), 2),
                "follower_gain": int(part["follower_gain"].sum()),
                "video_count": int(part["video_id"].nunique()),
            }
        )
    return sorted(rows, key=lambda r: r["week_daily_views"], reverse=True)


def publish_hour_distribution(df_enriched: pd.DataFrame) -> dict[int, float]:
    """发布时间段（小时）→ 平均健康度，用于"发布时间建议"。"""
    if df_enriched.empty or "publish_time" not in df_enriched.columns:
        return {}
    work = df_enriched.dropna(subset=["publish_time"]).copy()
    if work.empty:
        return {}
    work["hour"] = pd.to_datetime(work["publish_time"]).dt.hour
    first_day = work.sort_values("stat_date").groupby("video_id").first()
    stats = first_day.groupby("hour")["health_score"].mean()
    return {int(hour): round(float(score), 2) for hour, score in stats.items()}


def headline(df_enriched: pd.DataFrame, stat_date: date | None = None) -> dict[str, Any]:
    """看板 KPI 汇总。"""
    if df_enriched.empty:
        return {
            "stat_date": None,
            "daily_views": 0,
            "total_views": 0,
            "daily_engagement": 0,
            "engagement_rate": 0.0,
            "health_score": 0.0,
            "follower_gain": 0,
            "video_count": 0,
            "active_videos": 0,
            "daily_views_growth": 0.0,
        }
    stat_date = stat_date or max(df_enriched["stat_date"])
    today_df = df_enriched[df_enriched["stat_date"] == stat_date]
    prev_df = df_enriched[df_enriched["stat_date"] == stat_date - timedelta(days=1)]
    views = int(today_df["daily_views"].sum())
    prev_views = int(prev_df["daily_views"].sum()) if not prev_df.empty else 0
    engagement = int(today_df["daily_engagement"].sum())
    return {
        "stat_date": stat_date.isoformat(),
        "daily_views": views,
        "total_views": int(today_df["view_count"].sum()),
        "daily_engagement": engagement,
        "engagement_rate": round(safe_div(engagement, views) * 100, 3),
        "cum_engagement_rate": round(
            safe_div(today_df["engagement"].sum(), today_df["view_count"].sum()) * 100, 3
        ),
        "health_score": round(float(today_df["health_score"].mean()), 2),
        "follower_gain": int(today_df["follower_gain"].sum()),
        "video_count": int(today_df["video_id"].nunique()),
        "active_videos": int((today_df["daily_views"] > 0).sum()),
        "daily_views_growth": round(safe_div(views - prev_views, prev_views) * 100, 2),
    }
