"""统一数据模型（数据融合层的落点）。

双平台（B站 / 抖音）的异构字段在采集适配层按 *平台原始字段 → 本模型字段*
的映射规则归一化后写入这里，上层分析与 AI 模块只面向本模型，无需关心平台差异。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有表的基类。"""


def now() -> datetime:
    """本地时间（桌面单机应用，统一使用 naive 本地时间）。"""
    return datetime.now()


class Account(Base):
    """创作者账号（B站 UP主 / 抖音作者）。"""

    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("platform", "platform_account_id", name="uq_account_platform_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    platform_account_id: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[str] = mapped_column(String(128), default="")
    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    total_favorite: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    signature: Mapped[str] = mapped_column(String(255), default="")
    home_url: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(32), default="manual")  # sample / crawler / manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    videos: Mapped[list["Video"]] = relationship(back_populates="account")


class Video(Base):
    """作品（视频/图文），双平台统一字段。"""

    __tablename__ = "video"
    __table_args__ = (
        UniqueConstraint("platform", "platform_video_id", name="uq_video_platform_id"),
        Index("ix_video_publish_time", "publish_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    platform_video_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    content_type: Mapped[str] = mapped_column(String(32), default="video")  # video / image_text
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cover_url: Mapped[str] = mapped_column(String(255), default="")
    video_url: Mapped[str] = mapped_column(String(255), default="")
    topic: Mapped[str] = mapped_column(String(128), default="")  # 采集关键词/榜单来源
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    account: Mapped[Account | None] = relationship(back_populates="videos")
    snapshots: Mapped[list["VideoMetricSnapshot"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class VideoMetricSnapshot(Base):
    """作品指标时序快照（每日一条），是趋势/增长/拐点分析的基础。"""

    __tablename__ = "video_metric_snapshot"
    __table_args__ = (
        UniqueConstraint("video_id", "stat_date", name="uq_snapshot_video_date"),
        Index("ix_snapshot_platform_date", "platform", "stat_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(16), index=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)

    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    danmaku_count: Mapped[int] = mapped_column(Integer, default=0)
    follower_gain: Mapped[int] = mapped_column(Integer, default=0)  # 当日带动涨粉
    raw: Mapped[dict] = mapped_column(JSON, default=dict)  # 平台原始字段留档

    video: Mapped[Video] = relationship(back_populates="snapshots")


class Comment(Base):
    """评论/弹幕文本，用于情感倾向与选题挖掘。"""

    __tablename__ = "comment"
    __table_args__ = (
        UniqueConstraint("platform", "platform_comment_id", name="uq_comment_platform_id"),
        Index("ix_comment_video", "video_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    platform_comment_id: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("video.id", ondelete="CASCADE"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    user_nickname: Mapped[str] = mapped_column(String(128), default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # [-1, 1]
    sentiment_label: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    video: Mapped[Video | None] = relationship(back_populates="comments")


class AnalysisResult(Base):
    """本地分析结果（按日期 + 平台 + 口径保存一份，供看板与 AI 复用）。"""

    __tablename__ = "analysis_result"
    __table_args__ = (
        UniqueConstraint("stat_date", "platform", "scope_key", name="uq_analysis_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    platform: Mapped[str] = mapped_column(String(16), default="")  # 空字符串表示全平台口径
    scope_key: Mapped[str] = mapped_column(String(64), default="all")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AIReport(Base):
    """大模型生成的解读文案 / 建议。"""

    __tablename__ = "ai_report"
    __table_args__ = (Index("ix_report_date_type", "stat_date", "report_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    report_type: Mapped[str] = mapped_column(String(32), default="daily_brief")
    platform: Mapped[str] = mapped_column(String(16), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="local")
    model: Mapped[str] = mapped_column(String(64), default="")
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)  # True 表示本地模板生成
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ChatSession(Base):
    """AI 问答会话。"""

    __tablename__ = "chat_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """AI 问答消息（role: user / assistant / system）。"""

    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class CollectTask(Base):
    """数据同步/导入操作记录。

    早期版本用于记录爬取任务；自 v0.3 起软件内不再爬取，
    本表改用于记录「数据仓库同步」等操作，便于界面与日志追溯。
    """

    __tablename__ = "collect_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16))
    target_type: Mapped[str] = mapped_column(String(16), default="account")  # repository/account/keyword
    target_value: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    message: Mapped[str] = mapped_column(String(255), default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- #
# 扩展方向一：视频创作咨询（Consulting）
# --------------------------------------------------------------------------- #
class ConsultSession(Base):
    """创作咨询会话（围绕某个主题/账号方向的一次咨询）。"""

    __tablename__ = "consult_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), default="新咨询")
    category: Mapped[str] = mapped_column(String(32), default="general")  # 见 consulting.CATEGORIES
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    records: Mapped[list["ConsultRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ConsultRecord(Base):
    """一次咨询问答：问题 + 建议正文 + 结构化要点（JSON）。"""

    __tablename__ = "consult_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("consult_session.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    highlights: Mapped[list] = mapped_column(JSON, default=list)  # 建议要点
    provider: Mapped[str] = mapped_column(String(32), default="local")
    model: Mapped[str] = mapped_column(String(64), default="")
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    session: Mapped[ConsultSession] = relationship(back_populates="records")


# --------------------------------------------------------------------------- #
# 扩展方向二：AI 短剧（AI Short Drama）
# --------------------------------------------------------------------------- #
class DramaProject(Base):
    """短剧项目：一次创作的最小管理单元。"""

    __tablename__ = "drama_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), default="未命名短剧")
    genre: Mapped[str] = mapped_column(String(32), default="都市逆袭")
    target_platform: Mapped[str] = mapped_column(String(16), default="douyin")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="9:16")
    logline: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(128), default="")  # 视觉风格/画风描述
    episode_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/outlined/scripted/storyboarded
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    episodes: Mapped[list["DramaEpisode"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class DramaEpisode(Base):
    """剧集分集：大纲 → 剧本。"""

    __tablename__ = "drama_episode"
    __table_args__ = (UniqueConstraint("project_id", "episode_no", name="uq_drama_episode_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("drama_project.id", ondelete="CASCADE"))
    episode_no: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(128), default="")
    hook: Mapped[str] = mapped_column(Text, default="")  # 前 3 秒钩子
    outline: Mapped[str] = mapped_column(Text, default="")
    script: Mapped[str] = mapped_column(Text, default="")
    cliffhanger: Mapped[str] = mapped_column(Text, default="")  # 结尾悬念
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    project: Mapped[DramaProject] = relationship(back_populates="episodes")
    scenes: Mapped[list["DramaScene"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )


class DramaScene(Base):
    """分镜：镜头描述 + 台词 + 多模态提示词（预留文生图/文生视频）。"""

    __tablename__ = "drama_scene"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("drama_episode.id", ondelete="CASCADE"))
    scene_no: Mapped[int] = mapped_column(Integer, default=1)
    shot_type: Mapped[str] = mapped_column(String(32), default="中景")
    duration_sec: Mapped[int] = mapped_column(Integer, default=3)
    description: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[str] = mapped_column(Text, default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")  # 预留：文生图
    video_prompt: Mapped[str] = mapped_column(Text, default="")  # 预留：文生视频
    asset_path: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    episode: Mapped[DramaEpisode] = relationship(back_populates="scenes")
