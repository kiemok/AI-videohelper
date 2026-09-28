"""数据导入契约与融合导入流水线。

**数据来源已改为「用户自建的数据仓库」**（见 ``app/datasource``）：
软件内不再包含任何爬取逻辑，采集/爬取由用户在外部完成后推送到仓库。
本模块只保留两件事：

1. ``RawBatch`` / ``ImportResult`` —— 数据在软件内部的传输与统计契约；
2. 导入函数 —— 把（平台原始字段或统一字段的）数据写入统一数据模型。

对外入口：
- ``import_batch``         ：导入一批原始数据（平台原始字段 → fusion 归一化）
- ``import_csv_dir``       ：导入统一字段的 CSV 目录（手工/历史数据）
- ``sync_sample_data``     ：载入**演示数据**（离线生成，用于无仓库时的体验与自检）
- ``archive_snapshots_csv``：指标快照归档
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.collect.contracts import ImportResult, RawBatch
from app.collect.fusion import (
    normalize_account,
    normalize_comment,
    normalize_snapshot,
    normalize_video,
    to_date,
    to_datetime,
    to_int,
)
from app.collect.sample_source import build_sample_batch, export_sample_csv
from app.config import ARCHIVE_DIR, SAMPLE_DIR
from app.core.logging_setup import get_logger
from app.db.base import session_scope
from app.db.repository import (
    get_video_id,
    upsert_account,
    upsert_comment,
    upsert_snapshot,
    upsert_video,
)

logger = get_logger(__name__)


def _detect_platform(raw: dict[str, Any], default: str = "") -> str:
    if "bvid" in raw or "mid" in raw:
        return "bilibili"
    if "aweme_id" in raw or "uid" in raw:
        return "douyin"
    return default or "bilibili"


def import_batch(db_url: str, batch: RawBatch, archive_csv: bool = False) -> ImportResult:
    """把一批原始数据融合归一化后写入统一模型（幂等，可重复执行）。"""
    result = ImportResult(source=batch.source or batch.platform)
    account_ids: dict[tuple[str, str], int] = {}
    video_ids: dict[tuple[str, str], int] = {}

    def bump(platform: str) -> None:
        result.platforms[platform] = result.platforms.get(platform, 0) + 1

    with session_scope(db_url) as s:
        for raw in batch.accounts:
            platform = _detect_platform(raw, batch.platform)
            payload = normalize_account(platform, raw)
            if not payload["platform_account_id"]:
                continue
            account_ids[(platform, payload["platform_account_id"])] = upsert_account(
                db_url, payload, session=s
            )
            result.accounts += 1
            bump(platform)

        for item in batch.videos:
            raw_video = item.get("video") or {}
            platform = _detect_platform(raw_video, batch.platform)
            video_payload = normalize_video(platform, raw_video)

            # 视频里若自带作者字段，且账号未入库，则补写账号
            account_pid = str(video_payload.pop("account_platform_id", "") or "")
            key = (platform, account_pid)
            if account_pid and key not in account_ids:
                author_raw = raw_video.get("owner") or raw_video.get("author")
                if isinstance(author_raw, dict) and author_raw:
                    account_ids[key] = upsert_account(
                        db_url, normalize_account(platform, author_raw), session=s
                    )
                    result.accounts += 1
            video_payload["account_id"] = account_ids.get(key)

            video_db_id = upsert_video(db_url, video_payload, session=s)
            video_ids[(platform, video_payload["platform_video_id"])] = video_db_id
            result.videos += 1
            bump(platform)

            prev_followers: int | None = None
            for raw_snap in item.get("snapshots", []):
                snap = normalize_snapshot(platform, raw_snap, raw_snap.get("stat_date"))
                followers_now = snap.pop("follower_count", None)
                if followers_now is not None:
                    # 平台给的是累计粉丝数时，用相邻两天差值补出涨粉
                    if not snap.get("follower_gain") and prev_followers is not None:
                        snap["follower_gain"] = max(0, int(followers_now) - prev_followers)
                    prev_followers = int(followers_now)
                upsert_snapshot(db_url, video_db_id, snap, session=s)
                result.snapshots += 1

            for raw_comment in item.get("comments", []):
                comment_payload = normalize_comment(platform, raw_comment)
                if not comment_payload["platform_comment_id"]:
                    continue
                comment_payload["video_id"] = video_db_id
                upsert_comment(db_url, comment_payload, session=s)
                result.comments += 1

    if archive_csv:
        try:
            written = export_sample_csv(batch)
            result.csv_files = {k: str(v) for k, v in written.items()}
        except (OSError, ValueError) as exc:  # 导出失败不影响入库结果
            logger.warning("导出样例 CSV 失败: %s", exc)

    logger.info("数据导入完成: %s", result.summary())
    return result


def sync_sample_data(
    db_url: str,
    days: int = 30,
    seed: int = 2024,
    platforms: tuple[str, ...] | None = None,
    export_csv: bool = True,
) -> ImportResult:
    """载入离线**演示数据**（无数据仓库时用于体验与自检，非真实数据）。"""
    batch = build_sample_batch(days=days, seed=seed, platforms=platforms)
    batch.source = "演示数据"
    return import_batch(db_url, batch, archive_csv=export_csv)


# --------------------------------------------------------------------------- #
# CSV 导入 / 归档
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return to_datetime(value)
    return None


def import_csv_dir(db_url: str, directory: Path | str | None = None) -> ImportResult:
    """从 CSV 目录导入统一字段数据（字段定义见 sample_source._CSV_FIELDS）。"""
    directory = Path(directory or SAMPLE_DIR)
    result = ImportResult(source=f"CSV:{directory.name}")
    account_ids: dict[tuple[str, str], int] = {}
    video_ids: dict[tuple[str, str], int] = {}

    account_rows = _read_csv(directory / "accounts.csv")
    video_rows = _read_csv(directory / "videos.csv")
    snapshot_rows = _read_csv(directory / "snapshots.csv")
    comment_rows = _read_csv(directory / "comments.csv")

    if not (account_rows or video_rows):
        logger.warning("CSV 目录中没有可用数据: %s", directory)

    with session_scope(db_url) as s:
        for row in account_rows:
            platform = row.get("platform") or "bilibili"
            pid = str(row.get("platform_account_id") or "")
            if not pid:
                continue
            account_ids[(platform, pid)] = upsert_account(
                db_url,
                {
                    "platform": platform,
                    "platform_account_id": pid,
                    "nickname": row.get("nickname", ""),
                    "follower_count": to_int(row.get("follower_count")),
                    "following_count": to_int(row.get("following_count")),
                    "total_favorite": to_int(row.get("total_favorite")),
                    "verified": str(row.get("verified", "")).strip() in {"1", "True", "true"},
                    "signature": row.get("signature", ""),
                    "home_url": row.get("home_url", ""),
                    "source": "csv",
                },
                session=s,
            )
            result.accounts += 1
            result.platforms[platform] = result.platforms.get(platform, 0) + 1

        for row in video_rows:
            platform = row.get("platform") or "bilibili"
            pvid = str(row.get("platform_video_id") or "")
            if not pvid:
                continue
            video_db_id = upsert_video(
                db_url,
                {
                    "platform": platform,
                    "platform_video_id": pvid,
                    "account_id": account_ids.get(
                        (platform, str(row.get("account_platform_id") or ""))
                    ),
                    "title": row.get("title", ""),
                    "description": row.get("description", ""),
                    "tags": [t for t in str(row.get("tags", "")).split("|") if t],
                    "content_type": row.get("content_type") or "video",
                    "duration_sec": to_int(row.get("duration_sec")),
                    "publish_time": _parse_dt(row.get("publish_time")),
                    "cover_url": row.get("cover_url", ""),
                    "video_url": row.get("video_url", ""),
                    "topic": row.get("topic", ""),
                },
                session=s,
            )
            video_ids[(platform, pvid)] = video_db_id
            result.videos += 1
            result.platforms[platform] = result.platforms.get(platform, 0) + 1

        for row in snapshot_rows:
            platform = row.get("platform") or "bilibili"
            pvid = str(row.get("platform_video_id") or "")
            video_db_id = video_ids.get((platform, pvid)) or get_video_id(
                db_url, platform, pvid, session=s
            )
            stat_date = to_date(row.get("stat_date"))
            if not video_db_id or not stat_date:
                continue
            if (platform, pvid) not in video_ids:
                video_ids[(platform, pvid)] = video_db_id
            upsert_snapshot(
                db_url,
                video_db_id,
                {
                    "platform": platform,
                    "stat_date": stat_date,
                    "view_count": to_int(row.get("view_count")),
                    "like_count": to_int(row.get("like_count")),
                    "comment_count": to_int(row.get("comment_count")),
                    "share_count": to_int(row.get("share_count")),
                    "favorite_count": to_int(row.get("favorite_count")),
                    "danmaku_count": to_int(row.get("danmaku_count")),
                    "follower_gain": to_int(row.get("follower_gain")),
                    "raw": {"provider": "csv"},
                },
                session=s,
            )
            result.snapshots += 1

        for row in comment_rows:
            platform = row.get("platform") or "bilibili"
            pvid = str(row.get("platform_video_id") or "")
            video_db_id = video_ids.get((platform, pvid)) or get_video_id(
                db_url, platform, pvid, session=s
            )
            cid = str(row.get("platform_comment_id") or "")
            if not cid:
                continue
            upsert_comment(
                db_url,
                {
                    "platform": platform,
                    "platform_comment_id": cid,
                    "video_id": video_db_id,
                    "content": row.get("content", ""),
                    "user_nickname": row.get("user_nickname", ""),
                    "like_count": to_int(row.get("like_count")),
                    "publish_time": _parse_dt(row.get("publish_time")),
                },
                session=s,
            )
            result.comments += 1

    logger.info("CSV 导入完成: %s", result.summary())
    return result


def archive_snapshots_csv(db_url: str, out_dir: Path | str | None = None) -> Path | None:
    """把指标快照按日期归档为 CSV（历史归档，后续可切 Parquet）。"""
    import pandas as pd

    from app.db.repository import list_snapshots

    rows = list_snapshots(db_url)
    if not rows:
        return None
    out_dir = Path(out_dir or ARCHIVE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"snapshots_{date.today().isoformat()}.csv"
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("快照已归档: %s (%d 行)", path, len(rows))
    return path
