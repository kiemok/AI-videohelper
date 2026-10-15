"""指标计算模块（Pandas / NumPy 实现）。

指标定义（与论文/文档保持一致）：

- **当日新增播放** ``daily_views``：相邻两天累计播放量差值，首日取累计值。
- **互动数** ``engagement``：点赞 + 评论 + 分享 + 收藏 + 弹幕。
- **互动率** ``engagement_rate``：当日新增互动 / 当日新增播放（当日口径，对趋势更敏感）；
  另有 ``cum_engagement_rate`` 为累计互动 / 累计播放。
- **日增长率** ``growth_rate``：当日新增播放 / 前一日累计播放。
- **传播健康度** ``health_score``（0~100）：**分平台适配**的四项加权 —— 互动强度、沉淀价值（收藏占比）、
  破圈能力（分享占比）、增长动能；参考上限按**真实数据 P75 标定**（见 ``HEALTH_REFERENCE``），
  平台**不可获取**的指标不参与计分（见 ``PLATFORM_CAPABILITIES``），单日样本缺"增长"时权重让给其它维度。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

STAT_COLUMNS = ("view_count", "like_count", "comment_count", "share_count", "favorite_count", "danmaku_count")
DELTA_COLUMNS = tuple("d_" + c for c in STAT_COLUMNS)

#: 各平台**接口可获取**的指标（详见 docs/接口能力与缺口.md）：
#: B站六项统计齐全；抖音接口不返回播放量（``play_count`` 恒为 0）且没有弹幕。
PLATFORM_CAPABILITIES: dict[str, frozenset[str]] = {
    "bilibili": frozenset(STAT_COLUMNS),
    "douyin": frozenset({"like_count", "comment_count", "share_count", "favorite_count"}),
}
#: 平台不在能力表里时的兜底（按 B站全量处理）
DEFAULT_CAPABILITIES = PLATFORM_CAPABILITIES["bilibili"]


def platform_capabilities(platform: str) -> frozenset[str]:
    """该平台可获取的统计项。"""
    return PLATFORM_CAPABILITIES.get(str(platform or "").lower(), DEFAULT_CAPABILITIES)


def platform_has_views(platform: str) -> bool:
    """该平台能否拿到播放量（抖音不能，相关指标必须换口径）。"""
    return "view_count" in platform_capabilities(platform)


def platform_missing_metrics(platform: str) -> list[str]:
    """该平台无法获取的统计项（界面显示"— / 不适用"，而不是伪装成 0）。"""
    caps = platform_capabilities(platform)
    return [column for column in STAT_COLUMNS if column not in caps]


#: 传播健康度权重：互动强度 / 沉淀价值 / 破圈能力 / 增长动能
HEALTH_WEIGHTS = {"strength": 0.30, "favorite": 0.25, "share": 0.20, "growth": 0.25}
#: 分项参考上限 = **真实数据（2692 作品 / 4639 快照）P75 标定**，达到即满分；
#: 某维度数据不可得时（如单日样本没有"增长"），其权重按比例让给其它维度。
HEALTH_REFERENCE: dict[str, dict[str, float]] = {
    "bilibili": {
        "strength_view": 0.10,  # 互动量 / 当日新增播放（实测 P75 = 11.3%）
        "favorite_share": 0.25,  # 收藏 / 当日互动（实测 P75 = 25.0%）
        "share_share": 0.04,  # 分享 / 当日互动（实测 P75 = 3.9%）
        "growth": 0.20,  # 当日互动 / 前一日累计互动
    },
    "douyin": {
        "engagement_p90": 30000.0,  # 无播放量 → 当日互动量对数归一（实测 P90 = 29,528）
        "favorite_share": 0.12,  # 实测 P75 = 11.9%
        "share_share": 0.12,  # 实测 P75 = 12.3%
        "growth": 0.20,
    },
}
#: 柔化指数：分项得分按 ``(实际/参考) ** 0.7`` 压缩，避免线性映射把中位水平压得过低
HEALTH_CURVE = 0.7


def _num(value: Any) -> float:
    """转 float，无法转换或 NaN 时返回 0.0。"""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if np.isnan(result) else result


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

    # 平台无关的"互动结构"指标：以**当日互动量**为分母（B站与抖音都能算）
    engagement_base = out["daily_engagement"].replace(0, np.nan)
    out["favorite_share"] = (out["d_favorite_count"] / engagement_base).fillna(0.0)
    out["share_share"] = (out["d_share_count"] / engagement_base).fillna(0.0)
    out["comment_share"] = (out["d_comment_count"] / engagement_base).fillna(0.0)

    # 增长动能：当日互动 / 前一日累计互动；只有一天样本时为 NaN（该维度不计分）
    prev_engagement = grouped["engagement"].shift(1).astype("float64")
    out["prev_engagement"] = prev_engagement
    out["daily_engagement_growth"] = np.where(
        prev_engagement.fillna(0) > 0,
        out["daily_engagement"] / prev_engagement.replace(0, np.nan),
        np.nan,
    )

    out["health_score"] = out.apply(health_score, axis=1)
    return out


def health_score(row: pd.Series) -> float:
    """传播健康度（0~100）：分平台适配的四项加权。

    - **互动强度**：B站 = 当日互动 / 当日新增播放；抖音无播放量 → 当日互动量的对数归一；
    - **沉淀价值**：收藏 / 当日互动；
    - **破圈能力**：分享 / 当日互动；
    - **增长动能**：当日互动 / 前一日累计互动（只有一天样本时不参与计分，权重让给其它维度）。
    """
    platform = str(row.get("platform") or "bilibili").lower()
    reference = HEALTH_REFERENCE.get(platform, HEALTH_REFERENCE["bilibili"])
    daily_engagement = _num(row.get("daily_engagement"))

    parts: dict[str, float] = {
        "favorite": safe_div(_num(row.get("favorite_share")), reference["favorite_share"]),
        "share": safe_div(_num(row.get("share_share")), reference["share_share"]),
    }
    if platform_has_views(platform):
        parts["strength"] = safe_div(_num(row.get("engagement_rate")), reference["strength_view"])
    else:
        parts["strength"] = safe_div(
            float(np.log1p(max(0.0, daily_engagement))),
            float(np.log1p(reference["engagement_p90"])),
        )

    weights = dict(HEALTH_WEIGHTS)
    growth = row.get("daily_engagement_growth")
    if growth is None or (isinstance(growth, float) and np.isnan(growth)):
        weights.pop("growth", None)  # 单日样本：增长维度无区分度，权重让给其它三项
    else:
        parts["growth"] = safe_div(max(0.0, _num(growth)), reference["growth"])

    total_weight = sum(weights.values()) or 1.0
    score = 0.0
    for key, weight in weights.items():
        value = max(0.0, parts.get(key, 0.0))
        score += weight * min(1.0, value**HEALTH_CURVE)
    return round(score / total_weight * 100, 2)


def active_mean_health(part: pd.DataFrame) -> float:
    """只统计「当日有互动」作品的平均健康度。

    **0 互动的作品（刚发布、还没开始传播）不等于"不健康"**：把它们计入均值会把
    整体健康度系统性拉低（实测 1859 个 B站作品里当天有 866 个 0 互动）。
    界面会同时展示参与统计的作品数，保证口径透明。
    """
    if part.empty:
        return 0.0
    active = part[part["daily_engagement"] > 0]
    if active.empty:
        return 0.0
    return round(float(active["health_score"].mean()), 2)


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
                "health_score": active_mean_health(part),
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
            "health_score": active_mean_health(part),
            "follower_gain": int(part["follower_gain"].sum()),
            "video_count": int(part["video_id"].nunique()),
            "week_daily_views": int(week_part["daily_views"].sum()),
            "week_health_score": active_mean_health(week_part),
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
                    "health_score": active_mean_health(day),
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
    # 抖音接口不返回播放量（见 docs/接口能力与缺口.md），漏斗首层实际只统计可获取该指标的平台
    rows = (
        ("曝光展示（仅 B站可获取）", views),
        ("内容点赞（Likes）", likes),
        ("深度互动（评论 / 收藏 / 分享）", deep),
        ("关注转化（Followers Added）", follows),
    )
    return [
        {"label": label, "value": value, "ratio": round(safe_div(value, views) * 100, 3)}
        for label, value in rows
    ]


def summarize_videos(
    df_enriched: pd.DataFrame,
    stat_date: date | None = None,
    top_n: int = 8,
    sort: str = "fresh",
) -> list[dict[str, Any]]:
    """作品榜（两种口径，界面可切换）。

    - ``sort="fresh"``（默认）：**当日新发布的作品**，按发布时间倒序（最新发布的排最前）；
      当天没有新发布作品时回退为「最近发布的一批作品」，避免看板空白。
    - ``sort="engagement"``：当日**互动量最高**的 N 条作品（跨平台统一口径 —— 抖音不返回
      播放量，"按互动量排序"比"按播放量排序"更公平）。

    平台接口**不提供**的指标以 ``None`` 返回（界面显示"—"），而不是伪装成 0
    —— 例如抖音不返回播放量（见 ``docs/接口能力与缺口.md``）。
    """
    if df_enriched.empty or "publish_time" not in df_enriched.columns:
        return []
    stat_date = stat_date or max(df_enriched["stat_date"])
    today = df_enriched[df_enriched["stat_date"] == stat_date].copy()
    if today.empty:
        return []
    today["publish_date"] = pd.to_datetime(today["publish_time"], errors="coerce").dt.date

    is_new_today = False
    if sort == "engagement":
        picked = today.sort_values("daily_engagement", ascending=False).head(top_n)
    else:
        picked = today[today["publish_date"] == stat_date]
        is_new_today = not picked.empty
        if not is_new_today:
            # 当天没有新发布 → 回退为最近发布的一批（按发布时间倒序）
            picked = today.dropna(subset=["publish_date"])
            if picked.empty:
                return []
        picked = picked.sort_values("publish_date", ascending=False).head(top_n)

    rows: list[dict[str, Any]] = []
    for _, row in picked.iterrows():
        platform = str(row.get("platform") or "")
        has_views = platform_has_views(platform)
        rows.append(
            {
                "title": row.get("title") or "",
                "platform": platform,
                "publish_time": str(row.get("publish_time") or "")[:16],
                "publish_date": str(row.get("publish_date") or ""),
                "stat_date": str(row["stat_date"]),
                # 平台不可得的指标返回 None → 界面显示"—"
                "view_count": int(row["view_count"]) if has_views else None,
                "daily_views": int(row["daily_views"]) if has_views else None,
                "daily_engagement": int(row["daily_engagement"]),
                "engagement_rate": (
                    round(float(row["engagement_rate"]) * 100, 3) if has_views else None
                ),
                "favorite_share": round(float(row.get("favorite_share") or 0) * 100, 2),
                "share_share": round(float(row.get("share_share") or 0) * 100, 2),
                "health_score": float(row["health_score"]),
                "is_new_today": is_new_today,
            }
        )
    return rows


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
                "health_score": active_mean_health(part),
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
            "health_videos": 0,
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
        "health_score": active_mean_health(today_df),
        "health_videos": int((today_df["daily_engagement"] > 0).sum()),
        "follower_gain": int(today_df["follower_gain"].sum()),
        "video_count": int(today_df["video_id"].nunique()),
        "active_videos": int((today_df["daily_views"] > 0).sum()),
        "daily_views_growth": round(safe_div(views - prev_views, prev_views) * 100, 2),
    }
