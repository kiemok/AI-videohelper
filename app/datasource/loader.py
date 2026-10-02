"""数据仓库内容的扫描与导入。

约定（两种格式都支持，可混用）：

**A. 标准 CSV（统一模型字段）**::

    accounts.csv                     platform,platform_account_id,nickname,follower_count,...
    videos.csv                       platform,platform_video_id,account_platform_id,title,...
    snapshots/2026-09-28.csv         platform,platform_video_id,stat_date,view_count,...
    comments/2026-09-28.csv          platform,platform_comment_id,platform_video_id,content,...

（也可写成单文件 ``snapshots.csv`` / ``comments.csv``；子目录名与文件名均可识别）

**B. 平台原始字段 JSON / JSONL（爬虫直接导出）**::

    bilibili/accounts.json   [{mid, name, follower, ...}]
    bilibili/videos.json     [{bvid, title, stat:{view,like,...}, owner:{...}}]
    douyin/videos.json       [{aweme_id, desc, statistics:{play_count,...}, author:{...}}]
    douyin/comments.json     [{cid, text, digg_count, user:{...}}]

原始字段会经 ``app/collect/fusion.py`` 归一化为统一数据模型后入库（幂等 upsert）。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.collect.fusion import (
    normalize_account,
    normalize_comment,
    normalize_snapshot,
    normalize_video,
    to_bool,
    to_date,
    to_datetime,
    to_int,
)
from app.collect.contracts import ImportResult
from app.collect.validation import (
    NUMERIC_FIELDS,
    ValidationReport,
    first_value,
    is_number,
    write_report,
)
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

DATA_SUFFIXES = {".csv", ".json", ".jsonl", ".ndjson"}

#: 文件/目录名 → 数据类别（按顺序匹配）
_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("accounts", ("account", "creator", "up", "author", "用户", "账号")),
    ("videos", ("video", "work", "aweme", "post", "作品", "投稿")),
    ("snapshots", ("snapshot", "metric", "stat", "daily", "指标", "快照")),
    ("comments", ("comment", "reply", "danmaku", "评论", "弹幕")),
)

_PLATFORM_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bilibili", ("bilibili", "bili", "bzhan", "b站")),
    ("douyin", ("douyin", "dy", "tiktok", "抖音")),
)

#: 平台原始字段特征（用于判断走融合映射还是统一字段直读）
_RAW_ACCOUNT_KEYS = {"mid", "uid", "official_verify", "favoriting_count", "total_favorited"}
_RAW_VIDEO_KEYS = {"bvid", "aweme_id", "aid", "desc", "stat", "statistics", "pubdate", "create_time"}
_RAW_COMMENT_KEYS = {"rpid", "cid", "member", "message", "digg_count", "ctime"}


@dataclass
class RepoScan:
    """仓库扫描结果：按类别归集的待导入文件。"""

    root: Path
    files: dict[str, list[Path]] = field(default_factory=dict)
    skipped: list[Path] = field(default_factory=list)

    def total(self) -> int:
        return sum(len(paths) for paths in self.files.values())

    def describe(self) -> str:
        parts = [
            f"{name}:{len(self.files.get(name, []))}"
            for name, _keys in _KIND_KEYWORDS
            if self.files.get(name)
        ]
        text = "、".join(parts) if parts else "未发现可识别的数据文件"
        return f"{text}（共 {self.total()} 个文件）"


# --------------------------------------------------------------------------- #
# 扫描
# --------------------------------------------------------------------------- #
def scan_repository(root: Path | str, subdir: str = "") -> RepoScan:
    """扫描仓库目录，按类别归集数据文件。"""
    base = Path(root)
    if subdir.strip():
        base = base / subdir.strip()
    scan = RepoScan(root=base)
    if not base.exists():
        return scan

    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in DATA_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            continue  # 跳过 .git 等隐藏目录
        kind = _classify(path)
        if kind is None:
            scan.skipped.append(path)
            continue
        scan.files.setdefault(kind, []).append(path)
    return scan


def _classify(path: Path) -> str | None:
    """按目录名 → 文件名依次判断数据类别。"""
    candidates = [path.parent.name.lower(), path.stem.lower(), path.name.lower()]
    for text in candidates:
        for kind, keywords in _KIND_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return kind
    # 目录名形如 snapshots/2026-09-28.csv（文件名为纯日期）
    if _looks_like_date(path.stem):
        parent = path.parent.name.lower()
        for kind, keywords in _KIND_KEYWORDS:
            if any(keyword in parent for keyword in keywords):
                return kind
        return "snapshots"
    return None


def _looks_like_date(text: str) -> bool:
    return len(text) >= 10 and text[:4].isdigit() and text[4] in "-_" and text[7] in "-_"


def _date_from_name(path: Path) -> date | None:
    stem = path.stem.replace("_", "-")
    try:
        return date.fromisoformat(stem[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #
def read_rows_checked(path: Path) -> tuple[list[dict[str, Any]], str]:
    """读取 CSV / JSON / JSONL；返回 ``(行列表, 错误信息)``，错误信息为空表示读取成功。"""
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                return [dict(row) for row in csv.DictReader(fh)], ""
        text = path.read_text(encoding="utf-8-sig")
        if suffix in {".jsonl", ".ndjson"}:
            rows: list[dict[str, Any]] = []
            for number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except ValueError as exc:
                    return rows, f"第 {number} 行不是合法 JSON：{exc}"
                if isinstance(item, dict):
                    rows.append(item)
            return rows, ""
        payload = json.loads(text or "[]")
    except (OSError, ValueError, csv.Error) as exc:
        logger.warning("读取数据文件失败 %s: %s", path.name, exc)
        return [], f"无法解析：{exc}"

    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], ""
    if isinstance(payload, dict):
        for key in ("data", "items", "list", "records", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)], ""
        return [payload], ""
    return [], "顶层结构既不是数组也不是对象"


def read_rows(path: Path) -> list[dict[str, Any]]:
    """读取 CSV / JSON / JSONL，统一返回 dict 列表（忽略错误，兼容旧调用）。"""
    rows, _error = read_rows_checked(path)
    return rows


# --------------------------------------------------------------------------- #
# 平台与格式判断
# --------------------------------------------------------------------------- #
def _detect_platform(row: dict[str, Any], path: Path | None = None) -> str:
    if path is not None:
        text = str(path).lower()
        for platform, hints in _PLATFORM_HINTS:
            if any(hint in text for hint in hints):
                return platform
    value = str(row.get("platform") or row.get("_platform") or "").strip().lower()
    if value in {"bilibili", "douyin"}:
        return value
    if {"mid", "bvid", "aid"} & set(row):
        return "bilibili"
    if {"uid", "aweme_id", "statistics"} & set(row):
        return "douyin"
    return "bilibili"


def _is_raw(row: dict[str, Any], keys: set[str]) -> bool:
    return bool(keys & set(row))


def _first(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #
def import_repository(db_url: str, scan: RepoScan, source: str = "数据仓库") -> ImportResult:
    """把扫描到的仓库数据导入统一数据模型（幂等，可重复执行）。

    过程中做三层数据校验（文件 / 行 / 关系），问题写入 ``result.report``
    并在 ``data/export/`` 落一份 Markdown 报告，便于排查自己维护的数据。
    """
    result = ImportResult(source=source)
    report = ValidationReport(source=source)
    result.report = report
    account_ids: dict[tuple[str, str], int] = {}
    video_ids: dict[tuple[str, str], int] = {}
    skipped_snapshots = 0

    # 文件层：统计 + 未识别文件
    for kind, paths in scan.files.items():
        report.files[kind] = len(paths)
    if scan.skipped:
        report.unrecognized_files = [path.name for path in scan.skipped]
        report.warn(
            "文件",
            f"{len(scan.skipped)} 个文件",
            "命名未匹配到账号/作品/快照/评论任何类别，已跳过",
            "按 DATA_FORMAT.md 的约定命名，或放进 accounts / videos / snapshots / comments 目录",
        )
    if not scan.total():
        report.error("文件", str(scan.root), "没有找到可识别的数据文件", "先往仓库里放入 CSV / JSON 数据文件")

    def rows_of(path: Path, table: str) -> list[dict[str, Any]]:
        """读取一个文件并记录读取层问题。"""
        rows, error = read_rows_checked(path)
        if error:
            report.error(table, path.name, error, "确认文件为 UTF-8 编码且格式正确")
        if not rows:
            report.warn(table, path.name, "文件中没有数据行", "确认导出包含表头与至少一行数据")
        return rows

    with session_scope(db_url) as session:
        # 1) 账号
        for path in scan.files.get("accounts", []):
            for number, row in enumerate(rows_of(path, "账号"), 1):
                report.bump("账号", "读取")
                location = f"{path.name}:{number}"
                platform = _detect_platform(row, path)
                payload = (
                    normalize_account(platform, row)
                    if _is_raw(row, _RAW_ACCOUNT_KEYS)
                    else _account_from_unified(row, platform)
                )
                pid = str(payload.get("platform_account_id") or "")
                if not pid:
                    report.error("账号", location, "缺少账号 ID", "补 mid / uid 或 platform_account_id 字段")
                    report.bump("账号", "跳过")
                    continue
                if not str(payload.get("nickname") or "").strip():
                    report.warn("账号", location, f"账号 {pid} 昵称为空", "昵称用于聚合展示，建议补齐")
                account_ids[(platform, pid)] = upsert_account(db_url, payload, session=session)
                result.accounts += 1
                report.bump("账号", "导入")
                _bump(result, platform)

        # 2) 作品（可能内嵌快照）
        embedded_snapshots: list[tuple[str, str, list[dict[str, Any]]]] = []
        for path in scan.files.get("videos", []):
            for number, row in enumerate(rows_of(path, "作品"), 1):
                report.bump("作品", "读取")
                location = f"{path.name}:{number}"
                platform = _detect_platform(row, path)
                payload = (
                    normalize_video(platform, row)
                    if _is_raw(row, _RAW_VIDEO_KEYS)
                    else _video_from_unified(row, platform)
                )
                pvid = str(payload.get("platform_video_id") or "")
                if not pvid:
                    report.error(
                        "作品", location, "缺少作品 ID", "补 bvid / aweme_id 或 platform_video_id 字段"
                    )
                    report.bump("作品", "跳过")
                    continue
                if not str(payload.get("title") or "").strip():
                    report.warn("作品", location, f"作品 {pvid} 标题为空", "标题参与热词与分析展示，建议补齐")
                for key, label in NUMERIC_FIELDS.get("作品", ()):
                    value = first_value(row, key)
                    if str(value).strip() and not is_number(value):
                        report.warn(
                            "作品", location, f"{label}（{key}）不是数字：{value!r}",
                            "该行仍会导入，但该指标按 0 处理",
                        )

                account_pid = str(payload.pop("account_platform_id", "") or "")
                if account_pid and (platform, account_pid) not in account_ids:
                    author = row.get("owner") or row.get("author")
                    if isinstance(author, dict) and author:
                        account_ids[(platform, account_pid)] = upsert_account(
                            db_url, normalize_account(platform, author), session=session
                        )
                        result.accounts += 1
                if account_pid and account_ids.get((platform, account_pid)) is None:
                    report.warn(
                        "作品", location, f"作品 {pvid} 未匹配到账号（{account_pid}）",
                        "先导入 accounts 数据，或在作品里带上 owner / author 字段",
                    )
                payload["platform_video_id"] = pvid
                payload["account_id"] = account_ids.get((platform, account_pid))

                video_db_id = upsert_video(db_url, payload, session=session)
                video_ids[(platform, pvid)] = video_db_id
                result.videos += 1
                report.bump("作品", "导入")
                _bump(result, platform)

                nested = row.get("snapshots") or row.get("stats") or row.get("metrics")
                if isinstance(nested, list) and nested:
                    embedded_snapshots.append((platform, pvid, nested))

        # 3) 内嵌快照
        for platform, pvid, embedded in embedded_snapshots:
            video_db_id = video_ids.get((platform, pvid))
            if not video_db_id:
                report.error(
                    "快照", f"作品 {pvid}", "内嵌快照找不到对应作品",
                    "确认该作品能正常导入（作品 ID 是否缺失）",
                )
                continue
            for row in embedded:
                report.bump("快照", "读取")
                if not isinstance(row, dict):
                    report.warn("快照", f"作品 {pvid}", "快照条目不是对象（dict）", "检查 JSON 结构")
                    report.bump("快照", "跳过")
                    continue
                if not str(first_value(row, "stat_date", "date", "captured_at")).strip():
                    report.warn(
                        "快照", f"作品 {pvid}", "内嵌快照缺少 stat_date",
                        "补 stat_date 字段，或用 snapshots/YYYY-MM-DD.csv 组织快照",
                    )
                for key, label in NUMERIC_FIELDS.get("快照", ()):
                    value = first_value(row, key)
                    if str(value).strip() and not is_number(value):
                        report.warn(
                            "快照", f"作品 {pvid}", f"{label}（{key}）不是数字：{value!r}",
                            "该行仍会导入，但该指标按 0 处理",
                        )
                snapshot = (
                    normalize_snapshot(platform, row)
                    if _is_raw(row, {"stat", "statistics"})
                    else _snapshot_from_unified(row, platform)
                )
                upsert_snapshot(db_url, video_db_id, snapshot, session=session)
                result.snapshots += 1
                report.bump("快照", "导入")

        # 4) 独立快照文件
        for path in scan.files.get("snapshots", []):
            fallback_date = _date_from_name(path)
            for number, row in enumerate(rows_of(path, "快照"), 1):
                report.bump("快照", "读取")
                location = f"{path.name}:{number}"
                platform = _detect_platform(row, path)
                pvid = str(
                    _first(row, "platform_video_id", "bvid", "aweme_id", "video_id", default="")
                )
                if not pvid:
                    report.error("快照", location, "缺少作品 ID，无法关联作品", "补 platform_video_id / bvid / aweme_id")
                    report.bump("快照", "跳过")
                    skipped_snapshots += 1
                    continue
                video_db_id = video_ids.get((platform, pvid)) or get_video_id(
                    db_url, platform, pvid, session=session
                )
                if not video_db_id:
                    skipped_snapshots += 1
                    report.error(
                        "快照", location, f"作品 {pvid} 不在库中（也不在同批作品数据里）",
                        "先导入该作品，或把作品与快照放在同一次导入中",
                    )
                    report.bump("快照", "跳过")
                    continue
                if not fallback_date and not str(
                    first_value(row, "stat_date", "date", "captured_at")
                ).strip():
                    report.warn(
                        "快照", location, "没有统计日期",
                        "补 stat_date 字段，或用 snapshots/YYYY-MM-DD.csv 组织快照",
                    )
                for key, label in NUMERIC_FIELDS.get("快照", ()):
                    value = first_value(row, key)
                    if str(value).strip() and not is_number(value):
                        report.warn(
                            "快照", location, f"{label}（{key}）不是数字：{value!r}",
                            "该行仍会导入，但该指标按 0 处理",
                        )
                snapshot = (
                    normalize_snapshot(platform, row, fallback_date)
                    if _is_raw(row, {"stat", "statistics"})
                    else _snapshot_from_unified(row, platform, fallback_date)
                )
                upsert_snapshot(db_url, video_db_id, snapshot, session=session)
                result.snapshots += 1
                report.bump("快照", "导入")

        # 5) 评论
        for path in scan.files.get("comments", []):
            fallback_time = _date_from_name(path)
            for number, row in enumerate(rows_of(path, "评论"), 1):
                report.bump("评论", "读取")
                location = f"{path.name}:{number}"
                platform = _detect_platform(row, path)
                payload = (
                    normalize_comment(platform, row)
                    if _is_raw(row, _RAW_COMMENT_KEYS)
                    else _comment_from_unified(row, platform, fallback_time)
                )
                cid = str(payload.get("platform_comment_id") or "")
                if not cid:
                    report.error("评论", location, "缺少评论 ID", "补 rpid / cid 或 platform_comment_id")
                    report.bump("评论", "跳过")
                    continue
                if not str(payload.get("content") or "").strip():
                    report.warn("评论", location, f"评论 {cid} 内容为空", "空评论不参与情感分析与热词统计")
                pvid = str(
                    _first(row, "platform_video_id", "bvid", "aweme_id", "video_id", default="")
                )
                if pvid:
                    payload["video_id"] = video_ids.get((platform, pvid)) or get_video_id(
                        db_url, platform, pvid, session=session
                    )
                    if not payload.get("video_id"):
                        report.warn(
                            "评论", location, f"评论 {cid} 关联的作品 {pvid} 不在库中",
                            "先导入作品数据；评论仍会入库，但不会挂到作品上",
                        )
                else:
                    report.warn("评论", location, f"评论 {cid} 未标注所属作品", "补 platform_video_id 字段")
                upsert_comment(db_url, payload, session=session)
                result.comments += 1
                report.bump("评论", "导入")

    if skipped_snapshots:
        logger.warning("有 %d 条快照因缺少对应作品被跳过", skipped_snapshots)
        result.skipped = skipped_snapshots
    if not result.accounts and not result.videos:
        report.error("导入", str(scan.root), "本次没有导入任何账号或作品", "检查文件命名、必填字段与平台列")
    write_report(report)
    logger.info("数据仓库导入完成：%s", result.summary())
    return result


def _bump(result: ImportResult, platform: str) -> None:
    result.platforms[platform] = result.platforms.get(platform, 0) + 1


# --------------------------------------------------------------------------- #
# 统一字段直读（标准 CSV / 规范化 JSON）
# --------------------------------------------------------------------------- #
def _account_from_unified(row: dict[str, Any], platform: str) -> dict[str, Any]:
    return {
        "platform": platform,
        "platform_account_id": str(_first(row, "platform_account_id", "account_id", "id")),
        "nickname": str(_first(row, "nickname", "username", "name")),
        "follower_count": to_int(_first(row, "follower_count", "followers", default=0)),
        "following_count": to_int(_first(row, "following_count", default=0)),
        "total_favorite": to_int(_first(row, "total_favorite", default=0)),
        "verified": to_bool(_first(row, "verified", default=False)),
        "signature": str(_first(row, "signature", "sign")),
        "home_url": str(_first(row, "home_url", default="")),
        "source": "repo",
        "extra": {"raw_provider": platform, "source": "repo"},
    }


def _video_from_unified(row: dict[str, Any], platform: str) -> dict[str, Any]:
    tags = _first(row, "tags", default=[])
    if isinstance(tags, str):
        tags = [t for t in tags.replace("|", ",").split(",") if t.strip()]
    return {
        "platform": platform,
        "platform_video_id": str(_first(row, "platform_video_id", "video_id", "id")),
        "account_platform_id": str(_first(row, "account_platform_id", "platform_account_id", "author_id")),
        "title": str(_first(row, "title", "name")),
        "description": str(_first(row, "description", "desc")),
        "tags": list(tags or []),
        "content_type": str(_first(row, "content_type", default="video")),
        "duration_sec": to_int(_first(row, "duration_sec", "duration", default=0)),
        "publish_time": to_datetime(_first(row, "publish_time", "pubdate", "create_time")),
        "cover_url": str(_first(row, "cover_url", "cover")),
        "video_url": str(_first(row, "video_url", "url")),
        "topic": str(_first(row, "topic", default="")),
        "extra": {"raw_provider": platform, "source": "repo"},
    }


def _snapshot_from_unified(
    row: dict[str, Any], platform: str, fallback_date: date | None = None
) -> dict[str, Any]:
    stat_date = to_date(_first(row, "stat_date", "date")) or fallback_date or date.today()
    return {
        "platform": platform,
        "stat_date": stat_date,
        "view_count": to_int(_first(row, "view_count", "views", "play_count", default=0)),
        "like_count": to_int(_first(row, "like_count", "likes", default=0)),
        "comment_count": to_int(_first(row, "comment_count", "comments", default=0)),
        "share_count": to_int(_first(row, "share_count", "shares", default=0)),
        "favorite_count": to_int(_first(row, "favorite_count", "favorites", "collect_count", default=0)),
        "danmaku_count": to_int(_first(row, "danmaku_count", default=0)),
        "follower_gain": to_int(_first(row, "follower_gain", default=0)),
        "raw": {"provider": platform, "source": "repo"},
    }


def _comment_from_unified(
    row: dict[str, Any], platform: str, fallback_time: date | None = None
) -> dict[str, Any]:
    publish_time = to_datetime(_first(row, "publish_time", "ctime", "create_time"))
    if publish_time is None and fallback_time is not None:
        import datetime as _dt

        publish_time = _dt.datetime.combine(fallback_time, _dt.time.min)
    return {
        "platform": platform,
        "platform_comment_id": str(_first(row, "platform_comment_id", "comment_id", "id")),
        "content": str(_first(row, "content", "text", "message")),
        "user_nickname": str(_first(row, "user_nickname", "username", "nickname")),
        "like_count": to_int(_first(row, "like_count", "likes", default=0)),
        "publish_time": publish_time,
    }


def iter_kinds(scan: RepoScan) -> Iterable[str]:
    for name, _keys in _KIND_KEYWORDS:
        if scan.files.get(name):
            yield name
