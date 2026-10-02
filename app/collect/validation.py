"""导入校验：把「静默跳过」变成可读的数据质量报告。

三层校验：

1. **文件层** —— 未识别的文件（命名不符合约定）、无法解析的文件（编码/格式错误）；
2. **行层** —— 必填字段缺失、数值字段非法；
3. **关系层** —— 快照/评论找不到对应作品、同一作品同一统计日期的重复快照。

报告既随导入结果回传界面（``ImportResult.report``），也可写出为
``data/export/import_report_<时间戳>.md`` 供留档与排查。数据源由用户自己维护时，
这份报告就是「为什么我的数据没进来」的答案。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging_setup import get_logger

logger = get_logger(__name__)

ERROR = "error"
WARNING = "warning"

#: 应为数字的字段（非数字只警告，仍会导入）
NUMERIC_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "作品": (
        ("view_count", "播放量"),
        ("like_count", "点赞量"),
        ("comment_count", "评论量"),
    ),
    "快照": (
        ("view_count", "播放量"),
        ("like_count", "点赞量"),
        ("comment_count", "评论量"),
        ("share_count", "分享量"),
        ("favorite_count", "收藏量"),
    ),
}


def first_value(row: dict[str, Any], *names: str) -> Any:
    """取第一个非空字段值（与导入逻辑保持一致的宽松取值）。"""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def is_number(value: Any) -> bool:
    """判断是否可当数字使用（允许字符串数字与千分位）。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value or "").strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


@dataclass
class Issue:
    """一条数据问题。"""

    level: str
    table: str
    location: str
    message: str
    suggestion: str = ""

    def line(self) -> str:
        mark = "❌" if self.level == ERROR else "⚠️"
        text = f"{mark} [{self.table}] {self.location}：{self.message}"
        return f"{text} → {self.suggestion}" if self.suggestion else text


@dataclass
class ValidationReport:
    """一次导入的校验结果。"""

    source: str = ""
    issues: list[Issue] = field(default_factory=list)
    #: 表 → {"读取": n, "导入": n, "跳过": n}
    stats: dict[str, dict[str, int]] = field(default_factory=dict)
    #: 类别 → 文件数
    files: dict[str, int] = field(default_factory=dict)
    unrecognized_files: list[str] = field(default_factory=list)
    report_path: Path | None = None
    #: 需要人工确认的重复键（同作品同日期的快照），仅记录不阻断
    duplicates: int = 0

    # ------------------------------------------------------------------ #
    def add(self, level: str, table: str, location: str, message: str, suggestion: str = "") -> None:
        self.issues.append(Issue(level, table, location, message, suggestion))

    def error(self, table: str, location: str, message: str, suggestion: str = "") -> None:
        self.add(ERROR, table, location, message, suggestion)

    def warn(self, table: str, location: str, message: str, suggestion: str = "") -> None:
        self.add(WARNING, table, location, message, suggestion)

    def bump(self, table: str, key: str, amount: int = 1) -> None:
        bucket = self.stats.setdefault(table, {"读取": 0, "导入": 0, "跳过": 0})
        bucket[key] = bucket.get(key, 0) + amount

    # ------------------------------------------------------------------ #
    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == WARNING]

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.is_clean:
            return "数据校验通过：未发现问题"
        parts: list[str] = []
        if self.errors:
            parts.append(f"错误 {len(self.errors)} 处")
        if self.warnings:
            parts.append(f"警告 {len(self.warnings)} 处")
        return "数据校验：" + "，".join(parts)

    # ------------------------------------------------------------------ #
    def to_markdown(self, max_issues: int = 200) -> str:
        lines = [
            "# 导入校验报告",
            "",
            f"- **数据来源**：{self.source or '—'}",
            f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **结论**：{'✅ 未发现问题' if self.is_clean else self.summary()}",
            "",
        ]
        if self.files:
            lines.extend(["## 文件统计", ""])
            for kind, count in sorted(self.files.items()):
                lines.append(f"- {kind}：{count} 个")
            if self.unrecognized_files:
                preview = "、".join(self.unrecognized_files[:6])
                more = f"（另有 {len(self.unrecognized_files) - 6} 个）" if len(self.unrecognized_files) > 6 else ""
                lines.append(f"- 未识别：{len(self.unrecognized_files)} 个 — {preview}{more}")
            lines.append("")
        if self.stats:
            lines.extend(["## 行统计", "", "| 数据表 | 读取 | 导入 | 跳过 |", "| --- | --- | --- | --- |"])
            for table, bucket in self.stats.items():
                lines.append(
                    f"| {table} | {bucket.get('读取', 0)} | {bucket.get('导入', 0)} | {bucket.get('跳过', 0)} |"
                )
            lines.append("")
        lines.extend(["## 问题清单", ""])
        if self.issues:
            for index, issue in enumerate(self.issues[:max_issues], 1):
                lines.append(f"{index}. {issue.line()}")
            if len(self.issues) > max_issues:
                lines.append(f"…另有 {len(self.issues) - max_issues} 条未列出")
        else:
            lines.append("无")
        lines.extend(
            [
                "",
                "---",
                "",
                "> 提示：修正数据后重新导入即可 —— 导入按「平台 + 平台内 ID + 统计日期」做 upsert，",
                "> 重复导入不会产生重复数据。",
            ]
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """给界面用的精简结构。"""
        return {
            "summary": self.summary(),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [issue.line() for issue in self.errors[:40]],
            "warnings": [issue.line() for issue in self.warnings[:40]],
            "stats": self.stats,
            "files": self.files,
            "unrecognized": self.unrecognized_files,
            "report_path": str(self.report_path) if self.report_path else "",
        }


def write_report(report: ValidationReport, directory: Path | None = None) -> Path | None:
    """把报告写到 ``data/export/import_report_<时间戳>.md``；失败返回 ``None``。"""
    from app.config import DATA_DIR

    base = Path(directory) if directory else Path(DATA_DIR) / "export"
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"import_report_{time.strftime('%Y%m%d_%H%M%S')}.md"
        path.write_text(report.to_markdown(), encoding="utf-8")
    except OSError as exc:
        logger.warning("写入导入校验报告失败：%s", exc)
        return None
    report.report_path = path
    logger.info("导入校验报告：%s", path)
    return path
