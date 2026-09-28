"""数据契约：软件内部传递数据用的轻量结构（与具体来源解耦）。

- ``RawBatch``    ：一批平台原始字段数据（账号 / 作品 + 内嵌快照与评论）
- ``ImportResult``：一次导入的统计结果（界面与日志统一使用）

数据来源既可以是**用户的数据仓库**（``app/datasource``），也可以是演示数据或手工 CSV，
它们都通过这些契约与导入流水线（``app/collect/pipeline.py``）对接。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawBatch:
    """一批待导入的数据（平台原始字段，尚未归一化）。"""

    platform: str = ""
    accounts: list[dict[str, Any]] = field(default_factory=list)
    # 每个元素形如 {"video": {...}, "snapshots": [...], "comments": [...]}
    videos: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""

    def is_empty(self) -> bool:
        return not self.accounts and not self.videos

    def counts(self) -> dict[str, int]:
        return {
            "accounts": len(self.accounts),
            "videos": len(self.videos),
            "snapshots": sum(len(v.get("snapshots", [])) for v in self.videos),
            "comments": sum(len(v.get("comments", [])) for v in self.videos),
        }


@dataclass
class ImportResult:
    """一次导入的统计结果。"""

    source: str = ""
    accounts: int = 0
    videos: int = 0
    snapshots: int = 0
    comments: int = 0
    skipped: int = 0
    platforms: dict[str, int] = field(default_factory=dict)
    csv_files: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        detail = "，".join(f"{k}:{v}" for k, v in sorted(self.platforms.items()))
        base = (
            f"来源 {self.source}｜账号 {self.accounts}｜作品 {self.videos}｜"
            f"指标快照 {self.snapshots}｜评论 {self.comments}"
        )
        if self.skipped:
            base += f"｜跳过 {self.skipped}"
        return f"{base}｜平台分布 {detail}" if detail else base
