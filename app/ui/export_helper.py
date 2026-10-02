"""统一的导出与复制能力：让每个页面生成的内容都能「带走」。

三种出口：

- **复制到剪贴板**：一键复制 Markdown，随处粘贴；
- **导出 Markdown**：写入 ``data/export/``（可在对话框里改路径），自动带元信息头
  （标题 + 生成时间 + 所用模型 + 数据口径），可直接贴进论文或交付文档；
- **导出 CSV**：表格类数据（作品排行等），Excel 可直接打开。

各页面只需提供一个 ``provider`` 回调返回 :class:`ExportPayload`，界面用 :class:`ExportActions`
按钮组挂在卡片头部即可，无需重复实现文件对话框与剪贴板逻辑。
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QWidget

from app.config import DATA_DIR
from app.core.logging_setup import get_logger
from app.ui.widgets.toolbar import ToolbarRow

logger = get_logger(__name__)


def export_dir() -> Path:
    """默认导出目录：``data/export``（首次使用时自动创建）。"""
    path = Path(DATA_DIR) / "export"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class ExportPayload:
    """一次导出的内容。"""

    title: str
    stem: str  # 文件名主干（不含扩展名与时间戳）
    body: str  # Markdown / 纯文本正文
    meta: dict[str, str] = field(default_factory=dict)  # 元信息：模型、数据口径等
    csv_columns: list[tuple[str, str]] = field(default_factory=list)  # (数据字段, 表头)
    csv_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_csv(self) -> bool:
        return bool(self.csv_columns and self.csv_rows)

    def markdown(self) -> str:
        """带元信息头的 Markdown：标题 + 元信息 + 分隔线 + 正文。"""
        meta = dict(self.meta)
        meta["导出时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"# {self.title}", ""]
        lines.extend(f"- **{key}**：{value}" for key, value in meta.items())
        lines.extend(["", "---", "", (self.body or "").strip(), ""])
        return "\n".join(lines)


# ---------------------------------------------------------------------- #
# 基础动作
# ---------------------------------------------------------------------- #
def copy_to_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text or "")


def _timestamped(directory: Path, stem: str, suffix: str) -> Path:
    safe = "".join(ch for ch in stem if ch not in '\\/:*?"<>|').strip() or "export"
    return directory / f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}{suffix}"


def save_markdown(
    parent: QWidget | None, payload: ExportPayload, directory: Path | None = None
) -> Path | None:
    """弹出保存对话框并写出 Markdown；用户取消返回 ``None``。"""
    target = _timestamped(directory or export_dir(), payload.stem, ".md")
    path_text, _ = QFileDialog.getSaveFileName(
        parent, "导出 Markdown", str(target), "Markdown 文件 (*.md);;所有文件 (*)"
    )
    if not path_text:
        return None
    path = Path(path_text)
    try:
        path.write_text(payload.markdown(), encoding="utf-8")
    except OSError as exc:
        QMessageBox.warning(parent, "导出失败", f"写入文件失败：{exc}")
        return None
    logger.info("已导出 Markdown：%s", path)
    return path


def save_csv(
    parent: QWidget | None, payload: ExportPayload, directory: Path | None = None
) -> Path | None:
    """弹出保存对话框并写出 CSV（UTF-8-BOM，Excel 打开不乱码）。"""
    target = _timestamped(directory or export_dir(), payload.stem, ".csv")
    path_text, _ = QFileDialog.getSaveFileName(
        parent, "导出 CSV", str(target), "CSV 文件 (*.csv);;所有文件 (*)"
    )
    if not path_text:
        return None
    path = Path(path_text)
    try:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([label for _key, label in payload.csv_columns])
            for row in payload.csv_rows:
                writer.writerow([row.get(key, "") for key, _label in payload.csv_columns])
    except OSError as exc:
        QMessageBox.warning(parent, "导出失败", f"写入文件失败：{exc}")
        return None
    logger.info("已导出 CSV：%s", path)
    return path


def open_export_dir(parent: QWidget | None = None) -> str:
    """在资源管理器中打开导出目录；返回目录路径（失败时返回错误说明）。"""
    directory = export_dir()
    try:
        import os

        os.startfile(str(directory))  # noqa: S606 - Windows 桌面端打开目录
    except OSError as exc:
        QMessageBox.warning(parent, "打开失败", f"无法打开目录：{exc}")
        return f"打开目录失败：{exc}"
    return str(directory)


# ---------------------------------------------------------------------- #
# 可复用的导出按钮组
# ---------------------------------------------------------------------- #
class ExportActions(ToolbarRow):
    """卡片头部/底部的导出动作组：复制 / 导出 MD /（可选）导出 CSV / 打开目录。

    ``provider`` 返回 :class:`ExportPayload`，暂无内容时返回 ``None``；
    ``notify`` 用于把结果反馈到状态栏（通常传 ``context.status_message.emit``）。
    """

    def __init__(
        self,
        provider: Callable[[], ExportPayload | None],
        notify: Callable[[str], None] | None = None,
        with_csv: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(spacing=6, parent=parent)
        self._provider = provider
        self._notify = notify or (lambda _message: None)
        self._with_csv = with_csv

        copy_button = QPushButton("复制")
        copy_button.setToolTip("把当前内容以 Markdown 复制到剪贴板")
        copy_button.clicked.connect(self._copy)
        self.add(copy_button, ToolbarRow.HIGH)

        md_button = QPushButton("导出 MD")
        md_button.setToolTip("导出为 Markdown 文件（自动附带生成时间、模型与数据口径）")
        md_button.clicked.connect(self._export_markdown)
        self.add(md_button, ToolbarRow.HIGH)

        if with_csv:
            csv_button = QPushButton("导出 CSV")
            csv_button.setToolTip("把表格数据导出为 CSV（Excel 可直接打开）")
            csv_button.clicked.connect(self._export_csv)
            self.add(csv_button, ToolbarRow.NORMAL)

        open_button = QPushButton("打开目录")
        open_button.setToolTip("在资源管理器中打开导出目录")
        open_button.clicked.connect(self._open_dir)
        self.add(open_button, ToolbarRow.LOW)
        self.add_stretch()

    # ------------------------------------------------------------------ #
    def _payload(self, need_csv: bool = False) -> ExportPayload | None:
        payload = self._provider()
        if payload is None:
            self._notify("暂无可导出的内容，请先生成")
            return None
        if need_csv and not payload.has_csv:
            self._notify("当前内容不含表格数据，无法导出 CSV")
            return None
        return payload

    def _copy(self) -> None:
        payload = self._payload()
        if payload is None:
            return
        copy_to_clipboard(payload.markdown())
        self._notify(f"已复制「{payload.title}」到剪贴板（Markdown 格式）")

    def _export_markdown(self) -> None:
        payload = self._payload()
        if payload is None:
            return
        path = save_markdown(self, payload)
        if path is not None:
            self._notify(f"已导出 Markdown：{path.name}（{path.parent}）")

    def _export_csv(self) -> None:
        payload = self._payload(need_csv=True)
        if payload is None:
            return
        path = save_csv(self, payload)
        if path is not None:
            self._notify(f"已导出 CSV：{path.name}（共 {len(payload.csv_rows)} 行）")

    def _open_dir(self) -> None:
        directory = open_export_dir(self)
        if directory.startswith("打开目录失败"):
            self._notify(directory)
        else:
            self._notify(f"导出目录：{directory}")
