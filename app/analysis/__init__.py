"""本地数据分析层：指标计算、异常拐点检测、评论情感与关键词。"""

from app.analysis.anomaly import detect_overall_trend, detect_turning_points
from app.analysis.keywords import extract_keywords
from app.analysis.metrics import (
    compute_video_daily,
    daily_series,
    headline,
    health_score,
    platform_compare,
    safe_div,
    snapshots_to_frame,
    summarize_accounts,
    summarize_videos,
)
from app.analysis.sentiment import analyze_text, aggregate, score_comments
from app.analysis.service import analysis_date_options, refresh_sentiment, run_daily_analysis

__all__ = [
    "detect_overall_trend",
    "detect_turning_points",
    "extract_keywords",
    "compute_video_daily",
    "daily_series",
    "headline",
    "health_score",
    "platform_compare",
    "safe_div",
    "snapshots_to_frame",
    "summarize_accounts",
    "summarize_videos",
    "analyze_text",
    "aggregate",
    "score_comments",
    "analysis_date_options",
    "refresh_sentiment",
    "run_daily_analysis",
]
