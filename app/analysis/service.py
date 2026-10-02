"""分析编排层：把存储层的原始数据跑成一份完整分析结果（并落库复用）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.analysis import anomaly, keywords as kw, metrics as M
from app.analysis import sentiment as S
from app.core.logging_setup import get_logger
from app.db.repository import (
    list_comments,
    list_snapshots,
    save_analysis,
    update_comment_sentiment,
)

logger = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 30


def _native(obj: Any) -> Any:
    """把 numpy / pandas / datetime 类型递归转成 JSON 可序列化的原生类型。"""
    if isinstance(obj, dict):
        return {str(k): _native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def refresh_sentiment(
    db_url: str,
    platform: str | None = None,
    engine: str = "lexicon",
    client: Any | None = None,
) -> dict[str, Any]:
    """对尚未打分的评论做情感分析并回写，再返回聚合结果。

    ``engine`` 取值：

    - ``lexicon``（默认）：离线词典法，零依赖、可解释；
    - ``llm``：大模型批量打标（需要可用的 ``client``），失败或漏答的条目自动回退词典法。

    返回的聚合结果里带 ``engine`` / ``llm_scored`` 字段，界面据此标注实际使用的引擎。
    """
    unscored = list_comments(db_url, platform=platform, only_unscored=True)
    engine_used = "lexicon"
    llm_hits = 0

    if engine == "llm" and client is not None and getattr(client, "is_available", False) and unscored:
        scored, llm_hits, errors = S.score_comments_with_llm(unscored, client)
        if llm_hits:
            engine_used = "llm"
        elif errors:
            logger.warning("大模型打标全部失败，已整体回退词典法：%s", errors[0])
    else:
        scored = S.score_comments(unscored)

    if scored:
        update_comment_sentiment(db_url, scored)
        logger.info(
            "评论情感打分完成: %d 条（引擎 %s，模型命中 %d）", len(scored), engine_used, llm_hits
        )
    result = S.aggregate(list_comments(db_url, platform=platform))
    result["engine"] = engine_used
    result["llm_scored"] = llm_hits
    return result


def run_daily_analysis(
    db_url: str,
    stat_date: date | None = None,
    platform: str | None = None,
    scope_key: str = "all",
    window_days: int = DEFAULT_WINDOW_DAYS,
    with_sentiment: bool = True,
    sentiment_engine: str = "lexicon",
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """执行一次完整分析并保存结果；数据为空时返回 ``{}``。"""
    snapshots = list_snapshots(db_url, platform=platform)
    if not snapshots:
        logger.warning("没有可分析的数据，请先导入/采集数据")
        return {}

    frame = M.snapshots_to_frame(snapshots)
    enriched = M.compute_video_daily(frame)
    last_date = stat_date or max(enriched["stat_date"])
    start_date = last_date - timedelta(days=window_days - 1)
    window_df = enriched[enriched["stat_date"] >= start_date]
    if window_df.empty:
        window_df = enriched

    trend = M.daily_series(enriched)[-window_days:]
    trend_by_platform = {
        key: rows[-window_days:] for key, rows in M.daily_series_by_platform(enriched).items()
    }
    sentiment = (
        refresh_sentiment(db_url, platform, engine=sentiment_engine, client=llm_client)
        if with_sentiment
        else {}
    )
    comment_texts = [c.get("content", "") for c in list_comments(db_url, platform=platform)]
    keyword_source = comment_texts + [str(t) for t in window_df["title"].dropna().unique()]

    metrics: dict[str, Any] = {
        "stat_date": last_date.isoformat(),
        "platform": platform or "",
        "scope_key": scope_key,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": window_days,
        "data_span": {
            "start": str(min(enriched["stat_date"])),
            "end": str(max(enriched["stat_date"])),
            "snapshot_rows": int(len(enriched)),
            "video_count": int(enriched["video_id"].nunique()),
        },
        "headline": M.headline(enriched, last_date),
        "platform_compare": M.platform_compare(enriched, last_date),
        "trend": trend,
        "trend_by_platform": trend_by_platform,
        "funnel": M.funnel_summary(enriched, last_date),
        "top_videos": M.summarize_videos(enriched, last_date),
        "accounts": M.summarize_accounts(enriched, last_date),
        "anomalies": anomaly.detect_turning_points(window_df)[:25],
        "overall_anomalies": anomaly.detect_overall_trend(trend),
        "busiest_dates": anomaly.busiest_dates(window_df),
        "sentiment": sentiment,
        "keywords": kw.extract_keywords(keyword_source, top_n=40),
        "publish_hours": M.publish_hour_distribution(window_df),
    }

    metrics = _native(metrics)
    save_analysis(db_url, last_date, platform or "", scope_key, metrics)
    logger.info(
        "分析完成: %s 平台=%s 作品=%d 快照=%d",
        metrics["stat_date"],
        platform or "全平台",
        metrics["data_span"]["video_count"],
        metrics["data_span"]["snapshot_rows"],
    )
    return metrics


def analysis_date_options(db_url: str, platform: str | None = None) -> list[str]:
    """可选分析日期（倒序）。"""
    from app.db.repository import available_dates

    return [d.isoformat() for d in available_dates(db_url, platform)]
