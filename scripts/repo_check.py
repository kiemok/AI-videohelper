"""数据仓库端到端验证：建仓库 → 写入两种格式数据 → 拉取 → 导入 → 校验。

覆盖：
1. 标准 CSV 结构（accounts / videos / snapshots 按日分片 / comments 按日分片）
2. 平台原始 JSON（bilibili / douyin 的 raw 字段 + 内嵌 snapshots 数组）
3. git 拉取链路（本地路径仓库，等价于远程仓库）
4. 幂等性（重复拉取导入不产生重复记录）

不触碰主数据库：使用系统临时目录下的独立 SQLite 库。

用法：
    .venv\\Scripts\\python.exe scripts\\repo_check.py
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DataRepoSettings  # noqa: E402
from app.datasource import (  # noqa: E402
    archive_url,
    import_repository,
    read_rows,
    repository_status,
    scan_repository,
    sync_repository,
)
from app.db.base import init_db  # noqa: E402
from app.db.repository import data_overview, list_repo_sync_logs  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def _git(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def build_repo(root: Path) -> None:
    """构造一个同时包含两种格式的数据仓库。"""
    repo = root / "demo-data-repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)

    today = date.today()
    days = [today - timedelta(days=offset) for offset in (0, 1, 2)]

    # ---------- A. 标准 CSV ----------
    with (repo / "videos.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "platform", "platform_video_id", "account_platform_id", "title", "description",
                "tags", "content_type", "duration_sec", "publish_time", "cover_url", "video_url", "topic",
            ]
        )
        for index in range(1, 4):
            writer.writerow(
                ["bilibili", f"BVCSV{index}", "100001", f"CSV 作品 {index}", "来自数据仓库的 CSV 数据",
                 "数码|实测", "video", 200 + index, f"{days[-1]} 20:0{index}:00", "", "", "数码测评"]
            )

    with (repo / "accounts.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["platform", "platform_account_id", "nickname", "follower_count", "following_count",
             "total_favorite", "verified", "signature", "home_url"]
        )
        writer.writerow(["bilibili", "100001", "科技老张", 132000, 120, 86000, 1, "数码测评", ""])
        writer.writerow(["douyin", "200001", "老张说科技", 286000, 90, 112000, 1, "30秒讲明白", ""])

    snapshot_dir = repo / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)
    for offset, day in enumerate(days):
        with (snapshot_dir / f"{day.isoformat()}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["platform", "platform_video_id", "stat_date", "view_count", "like_count",
                 "comment_count", "share_count", "favorite_count", "danmaku_count", "follower_gain"]
            )
            for index in range(1, 4):
                base = 41000 + index * 1500
                writer.writerow(
                    ["bilibili", f"BVCSV{index}", day.isoformat(),
                     base * (offset + 1), int(base * 0.08) * (offset + 1), 60 * (offset + 1),
                     40 * (offset + 1), 300 * (offset + 1), 120 * (offset + 1), 20 + offset]
                )

    comment_dir = repo / "comments"
    comment_dir.mkdir(exist_ok=True)
    for day in days[:1]:
        with (comment_dir / f"{day.isoformat()}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["platform", "platform_comment_id", "platform_video_id", "content",
                 "user_nickname", "like_count", "publish_time"]
            )
            writer.writerow(["bilibili", "bi_csv_c1", "BVCSV1", "讲得太清楚了", "路过的风", 88, f"{day} 21:00:00"])
            writer.writerow(["bilibili", "bi_csv_c2", "BVCSV1", "价格虚高，劝退", "打工人小陈", 12, f"{day} 21:05:00"])

    # ---------- B. 平台原始 JSON ----------
    bil = repo / "bilibili"
    bil.mkdir(exist_ok=True)
    (bil / "videos.json").write_text(
        json.dumps(
            [
                {
                    "bvid": "BVRAW001",
                    "aid": 101,
                    "title": "原始字段：6000元档笔记本怎么选",
                    "desc": "来自仓库的 B站 raw 数据",
                    "tag": ["数码", "实测"],
                    "duration": 320,
                    "pubdate": int(time.time()) - 86400 * 3,
                    "pic": "",
                    "owner": {"mid": "100002", "name": "数码小美", "follower": 48600, "official_verify": False},
                    "stat": {"view": 52000, "like": 4100, "reply": 260, "share": 180, "favorite": 900, "danmaku": 240},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (bil / "comments.jsonl").write_text(
        "\n".join(
            json.dumps(item, ensure_ascii=False)
            for item in (
                {"rpid": "raw_c1", "message": "干货满满", "like": 33, "ctime": int(time.time()) - 3600, "member": {"uname": "晚风"}},
                {"rpid": "raw_c2", "message": "标题党，没讲重点", "like": 8, "ctime": int(time.time()) - 7200, "member": {"uname": "咸鱼翻身"}},
            )
        ),
        encoding="utf-8",
    )

    dy = repo / "douyin"
    dy.mkdir(exist_ok=True)
    (dy / "videos.json").write_text(
        json.dumps(
            [
                {
                    "aweme_id": "7RAW00100",
                    "desc": "原始字段：手机卡顿先关掉这3个开关 #数码",
                    "create_time": int(time.time()) - 86400 * 2,
                    "duration": 42000,
                    "author": {"uid": "200002", "nickname": "美美Vlog", "follower_count": 63500, "favoriting_count": 21000},
                    "statistics": {"play_count": 88000, "digg_count": 6200, "comment_count": 310, "share_count": 420, "collect_count": 1100},
                    "snapshots": [
                        {"stat_date": day.isoformat(), "view_count": 88000 - offset * 20000,
                         "like_count": 6200 - offset * 1500, "comment_count": 310 - offset * 80,
                         "share_count": 420 - offset * 100, "favorite_count": 1100 - offset * 260,
                         "danmaku_count": 0, "follower_gain": 120 - offset * 30}
                        for offset, day in enumerate(days)
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (repo / "README.md").write_text("# 演示数据仓库\n\n仅用于端到端验证。\n", encoding="utf-8")
    _git(["init", "-q", "-b", "main"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["-c", "user.email=check@local", "-c", "user.name=check", "commit", "-qm", "demo data"], cwd=repo)
    log(f"[1/5] 已创建演示数据仓库：{repo}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    workspace = Path(tempfile.mkdtemp(prefix="ccd_repo_check_"))
    repo_root = workspace / "src"
    cache_dir = workspace / "cache"
    db_url = f"sqlite:///{(workspace / 'check.db').as_posix()}"

    log(f"[0/5] 临时工作区：{workspace}")
    build_repo(repo_root)
    init_db(db_url)

    settings = DataRepoSettings(
        url=str(repo_root / "demo-data-repo"),
        branch="main",
        local_dir=str(cache_dir),
        mode="git",
        auto_pull=True,
    )

    log("[2/5] git 拉取数据仓库…")
    result = sync_repository(settings)
    log(f"      -> ok={result.ok} action={result.action} commit={result.commit} files={result.file_count} {result.message or result.error}")
    if not result.ok:
        return 1

    status = repository_status(settings)
    log(f"      仓库状态：{status}")

    scan = scan_repository(result.local_dir, settings.subdir)
    log(f"[3/5] 仓库扫描：{scan.describe()}")
    for kind, paths in scan.files.items():
        log(f"      {kind}: " + "、".join(p.name for p in paths))
    if scan.skipped:
        log("      未识别（已跳过）：" + "、".join(p.name for p in scan.skipped))

    log("[4/5] 导入统一数据模型…")
    imported = import_repository(db_url, scan, source="repo_check")
    log("      " + imported.summary())
    overview = data_overview(db_url)
    log(f"      数据总览：{overview}")
    logs = list_repo_sync_logs(db_url)
    if logs:
        log(f"      同步记录：{logs[0]}")

    log("[5/5] 幂等性复测（再导入一次，行数不应增加）…")
    second = import_repository(db_url, scan, source="repo_check-again")
    overview2 = data_overview(db_url)
    log(f"      第二次导入：{second.summary()}")
    log(f"      数据总览：{overview2}")
    consistent = (
        overview["accounts"] == overview2["accounts"]
        and overview["videos"] == overview2["videos"]
        and overview["snapshots"] == overview2["snapshots"]
        and overview["comments"] == overview2["comments"]
    )

    log(f"      归档地址转换检查：{archive_url('https://github.com/user/repo', 'main')}")
    log(f"      归档地址转换检查：{archive_url('https://gitee.com/user/repo', 'main')}")

    shutil.rmtree(workspace, ignore_errors=True)
    if not consistent:
        log("❌ 幂等性校验失败：重复导入产生了新记录")
        return 1
    log("✅ 数据仓库端到端验证通过（两种格式解析 + git 拉取 + 幂等导入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
