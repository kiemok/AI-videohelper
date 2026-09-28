"""异常拐点检测。

方法（工程化、可解释，便于论文说明）：
1. 对「当日新增播放」序列做 3 日移动平均平滑，抑制单日噪声；
2. 以移动窗口（默认 7 天）的均值/标准差计算 z-score，``|z| >= 阈值`` 视为异常点；
3. 结合增长率符号变化判定拐点类型：``spike``（突然放量）/``drop``（传播衰减）/
   ``recover``（触底回升）/``fade``（增长转负）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_WINDOW = 7
DEFAULT_Z = 2.0


def _zscore_series(series: pd.Series, window: int) -> pd.Series:
    """滚动窗口 z-score（不使用未来数据）。"""
    mean = series.rolling(window=window, min_periods=3).mean()
    std = series.rolling(window=window, min_periods=3).std(ddof=0)
    z = (series - mean) / std.replace(0, np.nan)
    return z.fillna(0.0)


def detect_turning_points(
    daily: pd.DataFrame, window: int = DEFAULT_WINDOW, z_threshold: float = DEFAULT_Z
) -> list[dict[str, Any]]:
    """在「单作品每日增量」序列上检测拐点。

    ``daily`` 需包含列：video_id, title, platform, account, stat_date,
    daily_views, engagement_rate, growth_rate, health_score
    """
    if daily.empty:
        return []
    anomalies: list[dict[str, Any]] = []
    for video_id, part in daily.sort_values("stat_date").groupby("video_id"):
        series = part["daily_views"].astype("float64").reset_index(drop=True)
        if len(series) < 4 or series.max() <= 0:
            continue
        smooth = series.rolling(window=3, min_periods=1).mean()
        # 突变用原始序列的 z（平滑会削峰），持续变化用平滑序列的 z
        z_raw = _zscore_series(series, window)
        z_smooth = _zscore_series(smooth, window)
        z = pd.concat([z_raw, z_smooth], axis=1).max(axis=1)
        growth = part["growth_rate"].reset_index(drop=True)
        for idx in range(1, len(series)):
            z_val = float(z.iloc[idx])
            prev_growth = float(growth.iloc[idx - 1])
            cur_growth = float(growth.iloc[idx])
            kind = None
            if z_val >= z_threshold and cur_growth > prev_growth:
                kind = "spike"
            elif z_val >= z_threshold and cur_growth < 0:
                kind = "drop"
            elif z_val <= -z_threshold and cur_growth > prev_growth and prev_growth < 0:
                kind = "recover"
            elif prev_growth > 0.15 and cur_growth < -0.1:
                kind = "fade"
            if kind is None:
                continue
            row = part.iloc[idx]
            anomalies.append(
                {
                    "video_id": int(video_id),
                    "title": str(row.get("title", ""))[:60],
                    "platform": row.get("platform", ""),
                    "account": row.get("account", ""),
                    "stat_date": str(row.get("stat_date")),
                    "kind": kind,
                    "daily_views": int(series.iloc[idx]),
                    "prev_daily_views": int(series.iloc[idx - 1]),
                    "z_score": round(z_val, 2),
                    "growth_rate": round(float(cur_growth) * 100, 2),
                    "health_score": round(float(row.get("health_score", 0)), 2),
                    "note": _describe(kind, float(cur_growth), z_val),
                }
            )
    anomalies.sort(key=lambda a: (abs(a["z_score"]), a["stat_date"]), reverse=True)
    return anomalies


def _describe(kind: str, growth: float, z_val: float) -> str:
    table = {
        "spike": f"播放量异常放量（z={z_val:.1f}），建议复用该选题/封面风格",
        "drop": f"传播明显衰减（环比 {growth * 100:.1f}%），检查是否进入流量尾期",
        "recover": f"触底回升（环比 {growth * 100:.1f}%），二次分发/被推荐可能已生效",
        "fade": f"增长由正转负（环比 {growth * 100:.1f}%），内容生命周期拐点已出现",
    }
    return table.get(kind, "指标出现异常波动")


def detect_overall_trend(trend: list[dict[str, Any]], z_threshold: float = 1.5) -> list[dict[str, Any]]:
    """在整体每日新增播放序列上找异常日（双平台合计口径）。"""
    if len(trend) < 6:
        return []
    frame = pd.DataFrame(trend)
    series = frame["daily_views"].astype("float64")
    z = _zscore_series(series, DEFAULT_WINDOW)
    out: list[dict[str, Any]] = []
    for idx, value in enumerate(z):
        if abs(float(value)) < z_threshold:
            continue
        row = frame.iloc[idx]
        out.append(
            {
                "stat_date": row["stat_date"],
                "daily_views": int(row["daily_views"]),
                "engagement_rate": float(row["engagement_rate"]),
                "health_score": float(row["health_score"]),
                "z_score": round(float(value), 2),
                "direction": "up" if value > 0 else "down",
                "note": "整体流量异常放大" if value > 0 else "整体流量异常回落",
            }
        )
    return out


def busiest_dates(daily: pd.DataFrame, stat_date: date | None = None, top_n: int = 5) -> list[dict[str, Any]]:
    """各平台的流量高点（近 30 天）。"""
    if daily.empty:
        return []
    out: list[dict[str, Any]] = []
    for platform, part in daily.groupby("platform"):
        agg = part.groupby("stat_date")["daily_views"].sum().sort_values(ascending=False).head(top_n)
        for day, views in agg.items():
            out.append({"platform": platform, "stat_date": str(day), "daily_views": int(views)})
    return out
