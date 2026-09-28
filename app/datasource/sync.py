"""数据仓库同步：从用户自建的 Git 仓库拉取数据（不再由软件内爬取）。

支持三种获取方式（``DataRepoSettings.mode``）：

- ``git``  ：调用本机 git 执行 ``clone --depth 1`` / ``pull --ff-only``
- ``zip``  ：把仓库网页地址转换为归档地址下载并解压（无 git 环境时使用）
- ``local``：不联网，只读取用户自己 ``git pull`` 过的本地目录
- ``auto`` ：优先 git，失败自动回退 zip（默认）

ZIP 压缩包解压时会自动去掉仓库根目录（``repo-main/`` 这类外层目录）。
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.config import DataRepoSettings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_GIT_TIMEOUT = 300
_ZIP_NAME_RE = re.compile(r"^(?P<repo>.+?)-(?P<ref>[0-9a-zA-Z._-]+)$")


@dataclass
class SyncResult:
    ok: bool = False
    action: str = ""  # clone / pull / zip / local / up-to-date / error
    message: str = ""
    local_dir: Path | None = None
    commit: str = ""
    file_count: int = 0
    error: str = ""
    log: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f"{self.message}（共 {self.file_count} 个数据文件）"
        return self.error or self.message or "同步失败"


# --------------------------------------------------------------------------- #
# 状态查询（不联网）
# --------------------------------------------------------------------------- #
def repository_status(settings: DataRepoSettings) -> dict[str, object]:
    """返回本地仓库状态：是否已同步、commit、文件数、最近更新时间。"""
    local_dir = settings.resolved_local_dir()
    exists = local_dir.exists() and any(local_dir.iterdir()) if local_dir.exists() else False
    files = _count_data_files(local_dir) if exists else 0
    commit = _git_commit(local_dir) if exists else ""
    updated = ""
    if exists:
        try:
            newest = max(f.stat().st_mtime for f in local_dir.rglob("*") if f.is_file())
            updated = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest))
        except (ValueError, OSError):
            updated = ""
    return {
        "configured": settings.is_configured,
        "local_dir": str(local_dir),
        "exists": exists,
        "commit": commit,
        "files": files,
        "updated_at": updated,
        "mode": settings.mode,
        "url": settings.url,
        "branch": settings.branch,
    }


def _count_data_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(
        1
        for f in root.rglob("*")
        if f.is_file() and f.suffix.lower() in {".csv", ".json", ".jsonl", ".ndjson"}
    )


# --------------------------------------------------------------------------- #
# 同步入口
# --------------------------------------------------------------------------- #
def sync_repository(settings: DataRepoSettings, progress=None) -> SyncResult:  # noqa: ANN001
    """按配置拉取/更新数据仓库；返回同步结果（含文件数）。"""
    url = settings.url.strip()
    local_dir = settings.resolved_local_dir()
    mode = (settings.mode or "auto").strip().lower()

    def notify(text: str) -> None:
        logger.info("数据仓库同步：%s", text)
        if progress is not None:
            progress(text)

    if mode == "local" or (not url and local_dir.exists()):
        if not local_dir.exists():
            return SyncResult(ok=False, action="local", error=f"本地目录不存在：{local_dir}")
        notify(f"本地目录模式：{local_dir}")
        return SyncResult(
            ok=True,
            action="local",
            message="已读取本地目录",
            local_dir=local_dir,
            commit=_git_commit(local_dir),
            file_count=_count_data_files(local_dir),
        )

    if not url:
        return SyncResult(ok=False, action="error", error="尚未配置数据仓库地址")

    if mode in ("git", "auto"):
        result = _sync_with_git(url, settings.branch, local_dir, notify)
        if result.ok or mode == "git":
            return result
        notify(f"git 方式失败（{result.error}），尝试 ZIP 下载…")

    if mode in ("zip", "auto"):
        return _sync_with_zip(url, settings.branch, local_dir, notify)

    return SyncResult(ok=False, action="error", error=f"未知的同步模式：{mode}")


# --------------------------------------------------------------------------- #
# git 方式
# --------------------------------------------------------------------------- #
def _sync_with_git(url: str, branch: str, local_dir: Path, notify) -> SyncResult:  # noqa: ANN001
    if not _git_available():
        return SyncResult(ok=False, action="git", error="本机未找到 git 命令")

    is_repo = (local_dir / ".git").exists()
    try:
        if not is_repo:
            if local_dir.exists() and any(local_dir.iterdir()):
                # 目录里是上一次 ZIP 解压的内容，清掉后重新克隆
                shutil.rmtree(local_dir, ignore_errors=True)
            local_dir.parent.mkdir(parents=True, exist_ok=True)
            notify("首次克隆数据仓库…")
            code, out, err = _run_git(
                ["clone", "--depth", "1", "--branch", branch, url, str(local_dir)], cwd=None
            )
            action = "clone"
        else:
            notify("拉取仓库更新…")
            code, out, err = _run_git(["pull", "--ff-only"], cwd=local_dir)
            action = "pull"

        if code != 0:
            return SyncResult(ok=False, action="git", error=(err or out).strip()[:400])
    except OSError as exc:
        return SyncResult(ok=False, action="git", error=str(exc))

    commit = _git_commit(local_dir)
    files = _count_data_files(local_dir)
    if files == 0:
        return SyncResult(
            ok=False,
            action=action,
            local_dir=local_dir,
            commit=commit,
            error="仓库已同步，但未发现 .csv / .json / .jsonl 数据文件",
        )
    return SyncResult(
        ok=True,
        action=action,
        message="仓库已克隆" if action == "clone" else "仓库已更新",
        local_dir=local_dir,
        commit=commit,
        file_count=files,
    )


def _git_available() -> bool:
    try:
        code, _out, _err = _run_git(["--version"], cwd=None)
    except OSError:
        return False
    return code == 0


def _git_commit(local_dir: Path) -> str:
    if not (local_dir / ".git").exists():
        return ""
    try:
        code, out, _err = _run_git(["rev-parse", "--short", "HEAD"], cwd=local_dir)
    except OSError:
        return ""
    return out.strip() if code == 0 else ""


def _run_git(args: list[str], cwd: Path | None) -> tuple[int, str, str]:
    """执行 git 命令（Windows 下不弹控制台窗口）。"""
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(  # noqa: S603 - 参数为内部构造
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT,
        creationflags=creationflags,
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


# --------------------------------------------------------------------------- #
# ZIP 方式
# --------------------------------------------------------------------------- #
def archive_url(url: str, branch: str) -> str:
    """把仓库网页地址转成归档 ZIP 地址（GitHub / Gitee / 通用 GitLab）。"""
    clean = url.strip().rstrip("/")
    if clean.endswith(".zip"):
        return clean
    if clean.endswith(".git"):
        clean = clean[:-4]
    if "github.com" in clean:
        return f"{clean}/archive/refs/heads/{branch}.zip"
    if "gitee.com" in clean:
        return f"{clean}/repository/archive/{branch}.zip"
    if "gitlab" in clean:
        return f"{clean}/-/archive/{branch}/{clean.rstrip('/').split('/')[-1]}-{branch}.zip"
    return f"{clean}/archive/refs/heads/{branch}.zip"


def _sync_with_zip(url: str, branch: str, local_dir: Path, notify) -> SyncResult:  # noqa: ANN001
    target = archive_url(url, branch)
    notify(f"下载仓库归档：{target}")
    try:
        response = requests.get(target, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        return SyncResult(ok=False, action="zip", error=f"下载失败：{exc}")

    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                return SyncResult(ok=False, action="zip", error="压缩包为空")
            prefix = _common_prefix(names)
            if local_dir.exists():
                shutil.rmtree(local_dir, ignore_errors=True)
            local_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                if name.endswith("/"):
                    continue
                relative = name[len(prefix) :] if prefix and name.startswith(prefix) else name
                if not relative or relative.startswith(".."):
                    continue
                out_path = local_dir / relative
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, out_path.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
    except (zipfile.BadZipFile, OSError) as exc:
        return SyncResult(ok=False, action="zip", error=f"解压失败：{exc}")

    files = _count_data_files(local_dir)
    if files == 0:
        return SyncResult(
            ok=False,
            action="zip",
            local_dir=local_dir,
            error="归档已下载，但未发现 .csv / .json / .jsonl 数据文件",
        )
    return SyncResult(
        ok=True,
        action="zip",
        message="已通过 ZIP 归档更新",
        local_dir=local_dir,
        commit="",
        file_count=files,
    )


def _common_prefix(names: list[str]) -> str:
    """取压缩包内的公共顶层目录（如 ``repo-main/``）。"""
    first_parts = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(first_parts) == 1:
        top = first_parts.pop()
        if all(name.startswith(top + "/") for name in names if not name.startswith(top)):
            return ""
        return top + "/"
    return ""
