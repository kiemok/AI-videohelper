"""表格模型与单元格绘制：把 dict 列表渲染成 QTableView。

设计系统要求（见 theme.py）：无斑马纹、行底 1px 细分隔线、hover 变亮、
字号 12px 等宽数字、平台列用彩色胶囊标识。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QTableView

from app.config import platform_label
from app.ui.theme import COLORS, PLATFORM_COLORS, rgba

#: 自定义 role：把平台的原始 key 暴露给 delegate
PlatformRole = Qt.UserRole + 1


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


@dataclass
class Column:
    """列定义：key 取行数据字段，formatter 负责显示格式。"""

    key: str
    label: str
    width: int = 110
    formatter: Callable[[Any], str] | None = None
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter


class DictTableModel(QAbstractTableModel):
    """dict 列表 → 表格模型。"""

    def __init__(self, columns: list[Column], rows: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.columns = columns
        self.rows: list[dict[str, Any]] = rows or []

    # ------------------------------------------------------------------ #
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = list(rows or [])
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section].label
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        column = self.columns[index.column()]
        row = self.rows[index.row()]
        value = row.get(column.key)

        if role == PlatformRole:
            return row.get("platform")
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            if column.formatter:
                return column.formatter(value)
            if isinstance(value, bool):
                return "是" if value else "否"
            if isinstance(value, int):
                return _fmt_int(value)
            if isinstance(value, float):
                return _fmt_float(value)
            if isinstance(value, list):
                return "、".join(str(v) for v in value)
            return "" if value is None else str(value)
        if role == Qt.TextAlignmentRole:
            return int(column.align)
        if role == Qt.ForegroundRole and column.key == "platform":
            return QColor(PLATFORM_COLORS.get(str(value), COLORS["text"]))
        return None

    def row_at(self, row_index: int) -> dict[str, Any] | None:
        if 0 <= row_index < len(self.rows):
            return self.rows[row_index]
        return None


class PlatformBadgeDelegate(QStyledItemDelegate):
    """把平台列画成彩色胶囊（B站=青 / 抖音=珊瑚）。"""

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        key = index.data(PlatformRole)
        if not key:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & getattr(option.state.__class__, "State_Selected", 0):
            painter.fillRect(option.rect, QColor(rgba(COLORS["cyan"], 20)))
        elif option.state & getattr(option.state.__class__, "State_MouseOver", 0):
            painter.fillRect(option.rect, QColor(COLORS["surface2"]))

        color = QColor(PLATFORM_COLORS.get(str(key), COLORS["cyan"]))
        text = platform_label(str(key))
        font = QFont(option.font)
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 14
        rect = QRectF(
            option.rect.left() + 8,
            option.rect.center().y() - 9,
            min(width, option.rect.width() - 12),
            18,
        )
        painter.setPen(QPen(QColor(rgba(color.name(), 90)), 1))
        painter.setBrush(QColor(rgba(color.name(), 34)))
        painter.drawRoundedRect(rect, 9, 9)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


def configure_table(
    table: QTableView,
    *,
    row_height: int = 30,
    stretch_column: int | None = None,
    platform_column: int | None = None,
    header_height: int = 28,
) -> None:
    """统一表格观感：无网格、无斑马纹、选择整行、平台列胶囊。"""
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.horizontalHeader().setFixedHeight(header_height)
    table.horizontalHeader().setHighlightSections(False)
    table.setFrameShape(QTableView.NoFrame)
    if stretch_column is not None:
        table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.Stretch)
    if platform_column is not None:
        table.setItemDelegateForColumn(platform_column, PlatformBadgeDelegate(table))


# 常用列定义 ---------------------------------------------------------------- #
VIDEO_COLUMNS = [
    Column("platform", "平台", 64),
    Column("title", "作品标题", 300),
    Column("account", "账号", 110),
    Column("publish_time", "发布时间", 130, lambda v: str(v)[:16] if v else "—"),
    Column("view_count", "累计播放", 96, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("like_count", "点赞", 80, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("comment_count", "评论", 72, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("favorite_count", "收藏", 72, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("share_count", "分享", 72, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
]

ACCOUNT_COLUMNS = [
    Column("platform", "平台", 64),
    Column("username", "账号", 150),
    Column("follower_count", "粉丝数", 110, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("verified", "认证", 60, lambda v: "已认证" if v else "—"),
    Column("updated_at", "更新时间", 140, lambda v: str(v)[:16] if v else "—"),
]

ANOMALY_COLUMNS = [
    Column("stat_date", "日期", 96),
    Column("platform", "平台", 64),
    Column("title", "作品", 260),
    Column(
        "kind",
        "类型",
        72,
        lambda v: {"spike": "异常放量", "drop": "衰减预警", "recover": "长尾回温", "fade": "增长转负"}.get(
            str(v), str(v)
        ),
    ),
    Column("daily_views", "当日播放", 96, _fmt_int, Qt.AlignRight | Qt.AlignVCenter),
    Column("growth_rate", "环比%", 76, _fmt_float, Qt.AlignRight | Qt.AlignVCenter),
    Column("z_score", "z 值", 64, _fmt_float, Qt.AlignRight | Qt.AlignVCenter),
    Column("note", "AI 归因", 320),
]
