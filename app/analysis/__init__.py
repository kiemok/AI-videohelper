"""本地数据分析层：指标计算、异常拐点检测、评论情感与关键词。"""

from app.analysis.anomaly import detect_overall_trend, detect_turning_points
from app.analysis.keywords import extract_keywords
from app.analysis.metrics import (
    active_mean_health,
    compute_video_daily,
    daily_series,
    headline,
    health_score,
    platform_capabilities,
    platform_compare,
    platform_has_views,
    platform_missing_metrics,
    safe_div,
    snapshots_to_frame,
    summarize_accounts,
    summarize_videos,
)
from app.analysis.sentiment import (
    analyze_text,
    aggregate,
    build_llm_messages,
    parse_llm_scores,
    score_comments,
    score_comments_with_llm,
)
from app.analysis.service import analysis_date_options, refresh_sentiment, run_daily_analysis

__all__ = [
    "detect_overall_trend",
    "detect_turning_points",
    "extract_keywords",
    "active_mean_health",
    "compute_video_daily",
    "daily_series",
    "headline",
    "health_score",
    "platform_capabilities",
    "platform_compare",
    "platform_has_views",
    "platform_missing_metrics",
    "safe_div",
    "snapshots_to_frame",
    "summarize_accounts",
    "summarize_videos",
    "analyze_text",
    "aggregate",
    "build_llm_messages",
    "parse_llm_scores",
    "score_comments",
    "score_comments_with_llm",
    "analysis_date_options",
    "refresh_sentiment",
    "run_daily_analysis",
]
