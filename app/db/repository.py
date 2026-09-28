"""数据访问层：统一模型上的增删改查与聚合查询。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.logging_setup import get_logger
from app.db.base import session_scope
from app.db.models import (
    AIReport,
    Account,
    AnalysisResult,
    ChatMessage,
    ChatSession,
    CollectTask,
    Comment,
    Video,
    VideoMetricSnapshot,
    now,
)

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# 写入（融合层调用）
# --------------------------------------------------------------------------- #
@contextmanager
def _use_session(db_url: str, session: Session | None) -> Iterator[Session]:
    """批量导入时复用外部会话（减少频繁提交），否则自建事务会话。"""
    if session is not None:
        yield session
    else:
        with session_scope(db_url) as s:
            yield s


def upsert_account(
    db_url: str, payload: dict[str, Any], session: Session | None = None
) -> int:
    """按 (platform, platform_account_id) 幂等写入账号，返回主键。"""
    with _use_session(db_url, session) as s:
        row = s.scalar(
            select(Account).where(
                Account.platform == payload["platform"],
                Account.platform_account_id == str(payload["platform_account_id"]),
            )
        )
        if row is None:
            row = Account(
                platform=payload["platform"],
                platform_account_id=str(payload["platform_account_id"]),
            )
            s.add(row)
        for key in (
            "nickname",
            "follower_count",
            "following_count",
            "total_favorite",
            "verified",
            "signature",
            "home_url",
            "source",
            "extra",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        s.flush()
        return row.id


def upsert_video(db_url: str, payload: dict[str, Any], session: Session | None = None) -> int:
    """按 (platform, platform_video_id) 幂等写入作品，返回主键。"""
    with _use_session(db_url, session) as s:
        row = s.scalar(
            select(Video).where(
                Video.platform == payload["platform"],
                Video.platform_video_id == str(payload["platform_video_id"]),
            )
        )
        if row is None:
            row = Video(
                platform=payload["platform"],
                platform_video_id=str(payload["platform_video_id"]),
            )
            s.add(row)
        for key in (
            "account_id",
            "title",
            "description",
            "tags",
            "content_type",
            "duration_sec",
            "publish_time",
            "cover_url",
            "video_url",
            "topic",
            "extra",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])
        s.flush()
        return row.id


def upsert_snapshot(
    db_url: str, video_id: int, payload: dict[str, Any], session: Session | None = None
) -> None:
    """按 (video_id, stat_date) 幂等写入指标快照。"""
    stat_date = payload["stat_date"]
    if isinstance(stat_date, datetime):
        stat_date = stat_date.date()
    with _use_session(db_url, session) as s:
        row = s.scalar(
            select(VideoMetricSnapshot).where(
                VideoMetricSnapshot.video_id == video_id,
                VideoMetricSnapshot.stat_date == stat_date,
            )
        )
        if row is None:
            row = VideoMetricSnapshot(
                video_id=video_id,
                platform=payload["platform"],
                stat_date=stat_date,
            )
            s.add(row)
        for key in (
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
            "favorite_count",
            "danmaku_count",
            "follower_gain",
            "raw",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])


def upsert_comment(
    db_url: str, payload: dict[str, Any], session: Session | None = None
) -> None:
    """按 (platform, platform_comment_id) 幂等写入评论。"""
    with _use_session(db_url, session) as s:
        row = s.scalar(
            select(Comment).where(
                Comment.platform == payload["platform"],
                Comment.platform_comment_id == str(payload["platform_comment_id"]),
            )
        )
        if row is None:
            row = Comment(
                platform=payload["platform"],
                platform_comment_id=str(payload["platform_comment_id"]),
            )
            s.add(row)
        for key in (
            "video_id",
            "content",
            "user_nickname",
            "like_count",
            "publish_time",
            "sentiment_score",
            "sentiment_label",
        ):
            if key in payload and payload[key] is not None:
                setattr(row, key, payload[key])


def update_comment_sentiment(
    db_url: str, results: Iterable[tuple[int, float, str]]
) -> int:
    """批量回写评论情感分析结果。"""
    count = 0
    with session_scope(db_url) as s:
        for comment_id, score, label in results:
            row = s.get(Comment, comment_id)
            if row is not None:
                row.sentiment_score = score
                row.sentiment_label = label
                count += 1
    return count


def save_analysis(
    db_url: str, stat_date: date, platform: str, scope_key: str, metrics: dict[str, Any]
) -> None:
    """保存/覆盖某口径下的分析结果。"""
    with session_scope(db_url) as s:
        row = s.scalar(
            select(AnalysisResult).where(
                AnalysisResult.stat_date == stat_date,
                AnalysisResult.platform == platform,
                AnalysisResult.scope_key == scope_key,
            )
        )
        if row is None:
            row = AnalysisResult(stat_date=stat_date, platform=platform, scope_key=scope_key)
            s.add(row)
        row.metrics = metrics
        row.created_at = now()


def save_report(db_url: str, payload: dict[str, Any]) -> int:
    with session_scope(db_url) as s:
        row = AIReport(**payload)
        s.add(row)
        s.flush()
        return row.id


def create_chat_session(db_url: str, title: str = "新会话") -> int:
    with session_scope(db_url) as s:
        row = ChatSession(title=title)
        s.add(row)
        s.flush()
        return row.id


def add_chat_message(
    db_url: str, session_id: int, role: str, content: str, is_fallback: bool = False
) -> int:
    with session_scope(db_url) as s:
        row = ChatMessage(
            session_id=session_id, role=role, content=content, is_fallback=is_fallback
        )
        s.add(row)
        s.flush()
        return row.id


def create_repo_sync_log(db_url: str, action: str, message: str, file_count: int = 0) -> None:
    """记录一次数据仓库同步结果（沿用 collect_task 表，便于历史追溯）。"""
    with session_scope(db_url) as s:
        row = CollectTask(
            platform="repo",
            target_type="repository",
            target_value=action[:120],
            status="success" if "失败" not in message else "failed",
            message=message[:255],
            item_count=file_count,
            finished_at=now(),
        )
        s.add(row)


# --------------------------------------------------------------------------- #
# 查询（分析层 / 界面调用）
# --------------------------------------------------------------------------- #
def list_repo_sync_logs(db_url: str, limit: int = 20) -> list[dict[str, Any]]:
    """数据仓库同步/导入记录（写入 collect_task 表）。"""
    with session_scope(db_url) as s:
        rows = s.scalars(select(CollectTask).order_by(CollectTask.id.desc()).limit(limit)).all()
        return [
            {
                "finished_at": r.finished_at or r.started_at,
                "action": r.target_value,
                "message": r.message,
                "item_count": r.item_count,
                "status": r.status,
            }
            for r in rows
        ]


def get_video_id(
    db_url: str, platform: str, platform_video_id: str, session: Session | None = None
) -> int | None:
    """按平台作品 ID 查本地主键（CSV 导入时用于关联快照/评论）。"""
    with _use_session(db_url, session) as s:
        return s.scalar(
            select(Video.id).where(
                Video.platform == platform,
                Video.platform_video_id == str(platform_video_id),
            )
        )


def list_accounts(db_url: str, platform: str | None = None) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        stmt = select(Account).order_by(Account.platform, Account.follower_count.desc())
        if platform:
            stmt = stmt.where(Account.platform == platform)
        return [
            {
                "id": a.id,
                "platform": a.platform,
                "username": a.nickname,
                "follower_count": a.follower_count,
                "verified": a.verified,
                "updated_at": a.updated_at,
            }
            for a in s.scalars(stmt)
        ]


def list_videos(
    db_url: str,
    platform: str | None = None,
    keyword: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """作品列表（附带最新一日指标与账号昵称）。"""
    with session_scope(db_url) as s:
        latest = (
            select(
                VideoMetricSnapshot.video_id.label("video_id"),
                func.max(VideoMetricSnapshot.stat_date).label("stat_date"),
            )
            .group_by(VideoMetricSnapshot.video_id)
            .subquery()
        )
        stmt = (
            select(Video, Account.nickname, VideoMetricSnapshot)
            .outerjoin(Account, Video.account_id == Account.id)
            .outerjoin(latest, latest.c.video_id == Video.id)
            .outerjoin(
                VideoMetricSnapshot,
                (VideoMetricSnapshot.video_id == latest.c.video_id)
                & (VideoMetricSnapshot.stat_date == latest.c.stat_date),
            )
            .order_by(Video.publish_time.desc().nullslast(), Video.id.desc())
        )
        if platform:
            stmt = stmt.where(Video.platform == platform)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(Video.title.like(like))
        if limit:
            stmt = stmt.limit(limit)

        rows: list[dict[str, Any]] = []
        for video, nickname, snap in s.execute(stmt).all():
            rows.append(
                {
                    "id": video.id,
                    "platform": video.platform,
                    "video_id": video.platform_video_id,
                    "title": video.title,
                    "account": nickname or "",
                    "publish_time": video.publish_time,
                    "duration_sec": video.duration_sec,
                    "tags": video.tags or [],
                    "topic": video.topic,
                    "stat_date": snap.stat_date if snap else None,
                    "view_count": snap.view_count if snap else 0,
                    "like_count": snap.like_count if snap else 0,
                    "comment_count": snap.comment_count if snap else 0,
                    "share_count": snap.share_count if snap else 0,
                    "favorite_count": snap.favorite_count if snap else 0,
                    "danmaku_count": snap.danmaku_count if snap else 0,
                }
            )
        return rows


def list_snapshots(
    db_url: str,
    platform: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    """扁平化快照列表（每行含 video_id / 平台 / 日期 / 各指标 / 账号）。"""
    with session_scope(db_url) as s:
        stmt = (
            select(VideoMetricSnapshot, Video.platform_video_id, Video.title, Account.nickname)
            .join(Video, Video.id == VideoMetricSnapshot.video_id)
            .outerjoin(Account, Account.id == Video.account_id)
            .order_by(VideoMetricSnapshot.stat_date)
        )
        if platform:
            stmt = stmt.where(VideoMetricSnapshot.platform == platform)
        if start:
            stmt = stmt.where(VideoMetricSnapshot.stat_date >= start)
        if end:
            stmt = stmt.where(VideoMetricSnapshot.stat_date <= end)
        return [
            {
                "snapshot_id": snap.id,
                "video_id": snap.video_id,
                "platform_video_id": pvid,
                "title": title,
                "account": nickname or "",
                "platform": snap.platform,
                "stat_date": snap.stat_date,
                "view_count": snap.view_count,
                "like_count": snap.like_count,
                "comment_count": snap.comment_count,
                "share_count": snap.share_count,
                "favorite_count": snap.favorite_count,
                "danmaku_count": snap.danmaku_count,
                "follower_gain": snap.follower_gain,
            }
            for snap, pvid, title, nickname in s.execute(stmt).all()
        ]


def list_comments(
    db_url: str,
    platform: str | None = None,
    video_id: int | None = None,
    only_unscored: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        stmt = select(Comment).order_by(Comment.publish_time.desc().nullslast(), Comment.id.desc())
        if platform:
            stmt = stmt.where(Comment.platform == platform)
        if video_id:
            stmt = stmt.where(Comment.video_id == video_id)
        if only_unscored:
            stmt = stmt.where(Comment.sentiment_label.is_(None))
        if limit:
            stmt = stmt.limit(limit)
        return [
            {
                "id": c.id,
                "platform": c.platform,
                "video_id": c.video_id,
                "content": c.content,
                "user_nickname": c.user_nickname,
                "like_count": c.like_count,
                "publish_time": c.publish_time,
                "sentiment_score": c.sentiment_score,
                "sentiment_label": c.sentiment_label,
            }
            for c in s.scalars(stmt)
        ]


def get_analysis(db_url: str, stat_date: date, platform: str = "", scope_key: str = "all") -> dict | None:
    with session_scope(db_url) as s:
        row = s.scalar(
            select(AnalysisResult).where(
                AnalysisResult.stat_date == stat_date,
                AnalysisResult.platform == platform,
                AnalysisResult.scope_key == scope_key,
            )
        )
        return dict(row.metrics) if row and row.metrics else None


def latest_analysis(db_url: str, platform: str = "", scope_key: str = "all") -> dict | None:
    with session_scope(db_url) as s:
        row = s.scalar(
            select(AnalysisResult)
            .where(AnalysisResult.platform == platform, AnalysisResult.scope_key == scope_key)
            .order_by(AnalysisResult.stat_date.desc())
            .limit(1)
        )
        return dict(row.metrics) if row and row.metrics else None


def list_reports(db_url: str, limit: int = 20) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        stmt = select(AIReport).order_by(AIReport.generated_at.desc(), AIReport.id.desc()).limit(limit)
        return [
            {
                "id": r.id,
                "stat_date": r.stat_date,
                "report_type": r.report_type,
                "platform": r.platform,
                "content": r.content,
                "provider": r.provider,
                "model": r.model,
                "is_fallback": r.is_fallback,
                "generated_at": r.generated_at,
            }
            for r in s.scalars(stmt)
        ]


def latest_report(db_url: str, report_type: str | None = None) -> dict | None:
    with session_scope(db_url) as s:
        stmt = select(AIReport).order_by(AIReport.generated_at.desc(), AIReport.id.desc())
        if report_type:
            stmt = stmt.where(AIReport.report_type == report_type)
        row = s.scalars(stmt.limit(1)).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "stat_date": row.stat_date,
            "report_type": row.report_type,
            "content": row.content,
            "provider": row.provider,
            "model": row.model,
            "is_fallback": row.is_fallback,
            "generated_at": row.generated_at,
        }


def chat_history(db_url: str, session_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
            .limit(limit)
        )
        return [
            {"role": m.role, "content": m.content, "is_fallback": m.is_fallback}
            for m in s.scalars(stmt)
        ]


def data_overview(db_url: str) -> dict[str, Any]:
    """数据总览：各表行数与日期范围，用于看板顶部与数据页。"""
    with session_scope(db_url) as s:
        return {
            "accounts": s.scalar(select(func.count()).select_from(Account)) or 0,
            "videos": s.scalar(select(func.count()).select_from(Video)) or 0,
            "snapshots": s.scalar(select(func.count()).select_from(VideoMetricSnapshot)) or 0,
            "comments": s.scalar(select(func.count()).select_from(Comment)) or 0,
            "reports": s.scalar(select(func.count()).select_from(AIReport)) or 0,
            "date_min": s.scalar(select(func.min(VideoMetricSnapshot.stat_date))),
            "date_max": s.scalar(select(func.max(VideoMetricSnapshot.stat_date))),
        }


def distinct_platforms(db_url: str) -> list[str]:
    with session_scope(db_url) as s:
        rows = s.execute(
            select(VideoMetricSnapshot.platform).distinct().order_by(VideoMetricSnapshot.platform)
        ).all()
        return [r[0] for r in rows]


def clear_all_data(db_url: str, keep_config_reports: bool = False) -> None:
    """清空业务数据（用于重新导入样例或换库前的清理）。"""
    with session_scope(db_url) as s:
        s.execute(delete(ChatMessage))
        s.execute(delete(ChatSession))
        s.execute(delete(Comment))
        s.execute(delete(VideoMetricSnapshot))
        s.execute(delete(Video))
        s.execute(delete(Account))
        s.execute(delete(CollectTask))
        if not keep_config_reports:
            s.execute(delete(AIReport))
            s.execute(delete(AnalysisResult))


def available_dates(db_url: str, platform: str | None = None) -> Sequence[date]:
    with session_scope(db_url) as s:
        stmt = select(VideoMetricSnapshot.stat_date).distinct().order_by(
            VideoMetricSnapshot.stat_date.desc()
        )
        if platform:
            stmt = stmt.where(VideoMetricSnapshot.platform == platform)
        return [r[0] for r in s.execute(stmt).all()]
