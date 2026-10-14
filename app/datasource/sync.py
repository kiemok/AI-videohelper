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
import os
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

#: git 命令总超时（秒）：网络受限时尽快失败，避免界面长时间无响应
_GIT_TIMEOUT = 90
#: HTTP 连接 / 读取超时（秒）
_CONNECT_TIMEOUT = 8
_READ_TIMEOUT = 45
#: 常见的 GitHub 加速前缀（仅在直连失败时使用，仅对归档 ZIP 下载生效）
GITHUB_MIRRORS: tuple[str, ...] = (
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
)
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
def sync_repository(
    settings: DataRepoSettings,
    progress=None,  # noqa: ANN001
    proxy: str = "",
) -> SyncResult:
    """按配置拉取/更新数据仓库；返回同步结果（含文件数）。

    网络受限时的兜底顺序：git → 归档 ZIP（直连）→ 归档 ZIP（加速镜像）→ 本地已有数据。
    ``proxy`` 由调用方从应用配置传入（例如 ``http://127.0.0.1:7890``）。
    """
    url = settings.url.strip()
    local_dir = settings.resolved_local_dir()
    mode = (settings.mode or "auto").strip().lower()
    proxy = (proxy or "").strip()
    mirror = (getattr(settings, "mirror_prefix", "") or "").strip()

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

    failures: list[str] = []

    if mode in ("git", "auto"):
        result = _sync_with_git(url, settings.branch, local_dir, notify, proxy=proxy)
        if result.ok:
            return result
        failures.append(result.error or "")
        if mode == "git":
            return _fallback_or_error(local_dir, failures, notify)
        notify(f"git 方式失败（{result.error}），尝试 ZIP 下载…")

    if mode in ("zip", "auto"):
        result = _sync_with_zip(url, settings.branch, local_dir, notify, proxy=proxy)
        if result.ok:
            return result
        failures.append(result.error or "")
        for prefix in ([mirror] if mirror else list(GITHUB_MIRRORS)):
            if not prefix:
                continue
            notify(f"直连失败，尝试加速镜像：{prefix}")
            mirrored = _sync_with_zip(
                url, settings.branch, local_dir, notify, proxy=proxy, mirror=prefix
            )
            if mirrored.ok:
                mirrored.message = f"{mirrored.message}（经镜像 {prefix}）"
                return mirrored
            failures.append(mirrored.error or "")
        return _fallback_or_error(local_dir, failures, notify)

    return SyncResult(ok=False, action="error", error=f"未知的同步模式：{mode}")


# --------------------------------------------------------------------------- #
# git 方式
# --------------------------------------------------------------------------- #
def _fallback_or_error(local_dir: Path, failures: list[str], notify) -> SyncResult:  # noqa: ANN001
    """拉取全部失败时的收尾：本地已有数据就离线使用，否则给出可操作建议。"""
    files = _count_data_files(local_dir) if local_dir.exists() else 0
    if files:
        notify(f"网络不可用，改用本地已有数据（{files} 个文件）：{local_dir}")
        return SyncResult(
            ok=True,
            action="local",
            message=f"网络不可用，已改用本地已有数据（{files} 个文件）",
            local_dir=local_dir,
            commit=_git_commit(local_dir),
            file_count=files,
        )
    return SyncResult(ok=False, action="error", error=_network_hint(failures))


def _network_hint(failures: list[str]) -> str:
    """把拉取失败整理成「原因 + 可操作建议」。"""
    raw = "；".join(part for part in failures if part).strip()[:400] or "拉取失败"
    joined = " ".join(failures).lower()
    looks_like_network = any(
        key in joined
        for key in (
            "failed to connect",
            "timed out",
            "timeout",
            "connection",
            "max retries",
            "could not resolve",
            "network is unreachable",
            # 中文提示（git 超时等场景）
            "超时",
            "网络不通",
            "无法连接",
            "连接失败",
        )
    )
    if not looks_like_network:
        return raw
    return (
        f"{raw}\n\n原因：无法连接数据仓库所在站点（网络受限）。可任选一种方式继续：\n"
        "① 设置页填写 HTTP 代理（例如 http://127.0.0.1:7890）后重试；\n"
        "② 在「数据仓库与导入」页填写「加速镜像前缀」（例如 https://ghfast.top/）后重试；\n"
        "③ 把仓库数据复制到本机文件夹，用「本地缓存目录 + 仅本地目录」离线导入（无需网络）。"
    )


def _sync_with_git(
    url: str,
    branch: str,
    local_dir: Path,
    notify,  # noqa: ANN001
    proxy: str = "",
) -> SyncResult:
    if not _git_available():
        return SyncResult(ok=False, action="git", error="本机未找到 git 命令")

    # 网络受限时快速中断（20 秒内低于 1KB/s 即放弃），避免界面长时间无响应
    net_opts = ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20"]
    is_repo = (local_dir / ".git").exists()
    try:
        if not is_repo:
            if local_dir.exists() and any(local_dir.iterdir()):
                # 目录里是上一次 ZIP 解压的内容，清掉后重新克隆
                shutil.rmtree(local_dir, ignore_errors=True)
            local_dir.parent.mkdir(parents=True, exist_ok=True)
            notify("首次克隆数据仓库…")
            code, out, err = _run_git(
                [*net_opts, "clone", "--depth", "1", "--branch", branch, url, str(local_dir)],
                cwd=None,
                proxy=proxy,
            )
            action = "clone"
        else:
            notify("拉取仓库更新…")
            code, out, err = _run_git([*net_opts, "pull", "--ff-only"], cwd=local_dir, proxy=proxy)
            action = "pull"

        if code != 0:
            return SyncResult(ok=False, action="git", error=(err or out).strip()[:400])
    except OSError as exc:
        return SyncResult(ok=False, action="git", error=str(exc))
    except subprocess.TimeoutExpired:
        return SyncResult(
            ok=False, action="git", error=f"git 执行超时（{_GIT_TIMEOUT} 秒），可能是网络不通"
        )

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


def _run_git(args: list[str], cwd: Path | None, proxy: str = "") -> tuple[int, str, str]:
    """执行 git 命令（Windows 下不弹控制台窗口；可选注入 HTTP 代理）。"""
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = None
    if proxy:
        env = {
            **os.environ,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
        }
    completed = subprocess.run(  # noqa: S603 - 参数为内部构造
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_TIMEOUT,
        creationflags=creationflags,
        env=env,
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


# --------------------------------------------------------------------------- #
# ZIP 方式
# --------------------------------------------------------------------------- #
def archive_url(url: str, branch: str, mirror: str = "") -> str:
    """把仓库网页地址转成归档 ZIP 地址（GitHub / Gitee / 通用 GitLab）。

    ``mirror`` 非空时在前面拼加速前缀（例如 ``https://ghfast.top/``），用于直连失败的场景。
    """
    clean = url.strip().rstrip("/")
    if clean.endswith(".zip"):
        target = clean
    else:
        if clean.endswith(".git"):
            clean = clean[:-4]
        if "github.com" in clean:
            target = f"{clean}/archive/refs/heads/{branch}.zip"
        elif "gitee.com" in clean:
            target = f"{clean}/repository/archive/{branch}.zip"
        elif "gitlab" in clean:
            target = f"{clean}/-/archive/{branch}/{clean.rstrip('/').split('/')[-1]}-{branch}.zip"
        else:
            target = f"{clean}/archive/refs/heads/{branch}.zip"
    if mirror and not target.startswith(mirror):
        return mirror.rstrip("/") + "/" + target
    return target


def _sync_with_zip(
    url: str,
    branch: str,
    local_dir: Path,
    notify,  # noqa: ANN001
    proxy: str = "",
    mirror: str = "",
) -> SyncResult:
    target = archive_url(url, branch, mirror)
    notify(f"下载仓库归档：{target}")
    try:
        response = requests.get(
            target,
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            proxies={"http": proxy, "https": proxy} if proxy else None,
        )
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
    """取压缩包内的公共顶层目录（如 ``repo-main/``）；没有统一顶层时返回空串。

    注意：判断条件必须是「**所有**条目都位于该顶层目录下」——GitHub 归档的典型结构是
    ``repo-branch/`` 下含全部文件，此时应返回该前缀并剥离；若归档里混有顶层文件
    （如 ``LICENSE``）或多个顶层目录，则不可剥离。
    """
    first_parts = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(first_parts) != 1:
        return ""
    top = first_parts.pop()
    if all(name == top or name.startswith(top + "/") for name in names):
        return top + "/"
    return ""
