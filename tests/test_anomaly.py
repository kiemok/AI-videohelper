"""异常拐点检测单测：spike/drop 识别与整体异常日。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.analysis import anomaly as A


def turning_frame(values: list[int], start: date = date(2026, 9, 1)) -> pd.DataFrame:
    """构造「单作品每日增量」序列（detect_turning_points 的输入契约）。"""
    rows = []
    for index, value in enumerate(values):
        rows.append(
            {
                "video_id": 1,
                "title": "测试作品",
                "platform": "douyin",
                "account": "测试账号",
                "stat_date": start + timedelta(days=index),
                "daily_views": float(value),
                "engagement_rate": 5.0,
                "growth_rate": 0.0,
                "health_score": 60.0,
            }
        )
    frame = pd.DataFrame(rows)
    frame["growth_rate"] = frame["daily_views"].pct_change().fillna(0.0)
    return frame


# ---------------------------------------------------------------------- #
# 单作品拐点
# ---------------------------------------------------------------------- #
def test_spike_is_detected():
    # 平稳序列中插入一个明显放量日
    values = [100] * 8 + [500] + [120] * 2
    points = A.detect_turning_points(turning_frame(values))
    kinds = [point["kind"] for point in points]
    assert "spike" in kinds, f"应识别出放量拐点，实际：{kinds}"


def test_drop_is_detected():
    # 长期高位后突然断崖式下跌 → 应识别为 drop（依赖内部自算的环比变化率）
    values = [500] * 10 + [40] + [500] * 3
    points = A.detect_turning_points(turning_frame(values))
    kinds = [point["kind"] for point in points]
    assert "drop" in kinds, f"应识别出衰减拐点，实际：{kinds}"


def test_flat_series_has_no_turning_points():
    assert A.detect_turning_points(turning_frame([100] * 12)) == []


def test_turning_point_fields():
    values = [100] * 8 + [600] + [120] * 3
    points = A.detect_turning_points(turning_frame(values))
    assert points, "示例序列应至少有一个拐点"
    first = points[0]
    assert {"kind", "stat_date", "title", "platform", "z_score", "note"} <= set(first)
    assert first["note"], "应给出可读的归因描述"
    assert first["kind"] in {"spike", "drop", "recover", "fade"}


# ---------------------------------------------------------------------- #
# 整体异常日
# ---------------------------------------------------------------------- #
def test_overall_trend_requires_enough_days():
    trend = [{"stat_date": date(2026, 9, 1), "daily_views": 100}] * 3
    assert A.detect_overall_trend(trend) == []


def test_overall_trend_flags_outlier_day():
    daily = [
        {
            "stat_date": date(2026, 9, 1) + timedelta(days=index),
            "daily_views": 200,
            "engagement_rate": 5.0,
            "health_score": 60.0,
        }
        for index in range(10)
    ]
    daily.append(
        {
            "stat_date": date(2026, 9, 11),
            "daily_views": 3000,
            "engagement_rate": 8.0,
            "health_score": 75.0,
        }
    )
    flagged = A.detect_overall_trend(daily)
    assert flagged, "应识别出异常放量日"
    assert flagged[-1]["stat_date"] == date(2026, 9, 11)
    assert flagged[-1]["direction"] == "up"
    assert flagged[-1]["note"]
