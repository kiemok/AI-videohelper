"""自适应分栏：窗口够宽时左右并排，太窄时自动改为上下堆叠。

配合 ``ToolbarRow`` 一起，保证窗口缩放时界面里的标签与按钮始终是
「完整显示」或「整体隐藏」，不会出现文字竖排、输入框被压窄、按钮只剩半截字这类变形。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.cards import KpiCard, build_kpi_row


class ResponsiveSplitter(QSplitter):
    """按自身宽度自动切换排列方向的分栏容器。

    - 宽度 ≥ ``threshold``：``Qt.Horizontal``（左右并排）
    - 宽度 < ``threshold``：``Qt.Vertical``（上下堆叠，每一栏都能拿到完整宽度）
    - 切换带 ``HYSTERESIS`` 迟滞，避免在阈值附近来回抖动
    - ``stacked_min_height``：堆叠时给容器一个最小高度，配合页面滚动条使用
    """

    HYSTERESIS = 40

    def __init__(
        self,
        threshold: int = 860,
        horizontal_sizes: list[int] | None = None,
        vertical_sizes: list[int] | None = None,
        stacked_min_height: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._threshold = threshold
        self._horizontal_sizes = horizontal_sizes
        self._vertical_sizes = vertical_sizes
        self._stacked_min_height = stacked_min_height
        self._stacked = False
        self.setChildrenCollapsible(False)
        self.setHandleWidth(6)

    # ------------------------------------------------------------------ #
    # 自适应
    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().resizeEvent(event)
        self._apply()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().showEvent(event)
        self._apply()

    def _apply(self) -> None:
        if self.count() < 2:
            return
        width = self.width()
        if width <= 0:
            return
        if self._stacked:
            if width > self._threshold + self.HYSTERESIS:
                self._switch(False)
        elif width < self._threshold:
            self._switch(True)

    def _switch(self, stacked: bool) -> None:
        self._stacked = stacked
        self.setOrientation(Qt.Vertical if stacked else Qt.Horizontal)
        self.setMinimumHeight(self._stacked_min_height if stacked else 0)
        # 方向切换后布局才稳定，延后一拍设置尺寸
        QTimer.singleShot(0, self._restore_sizes)

    def _restore_sizes(self) -> None:
        sizes = self._vertical_sizes if self._stacked else self._horizontal_sizes
        if sizes and len(sizes) == self.count():
            self.setSizes(sizes)


class PageScrollArea(QScrollArea):
    """页面滚动容器：容器宽度**始终等于视口宽度**。

    普通 ``QScrollArea`` 在 ``widgetResizable=True`` 时仍会被内容的最小宽度撑开，
    导致内部 ``ResponsiveSplitter`` 测到的宽度过大而不切换为上下堆叠（内容还会被裁切）。
    这里强制把容器宽度钉在视口宽度上，于是「窄窗口 → 上下堆叠」能稳定生效，
    只保留纵向滚动。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().resizeEvent(event)
        widget = self.widget()
        if widget is None:
            return
        width = self.viewport().width()
        if width > 0 and widget.width() != width:
            widget.setFixedWidth(width)


class ResponsiveKpiRow(QWidget):
    """KPI 卡片行：够宽时一行 ``wide_columns`` 张，窄时自动换成 ``narrow_columns`` 张。

    换列数后每张卡都拿到更大宽度，卡片标题不会被裁切、也不会挤压变形。
    """

    HYSTERESIS = 40

    def __init__(
        self,
        cards: list[KpiCard],
        wide_columns: int = 4,
        narrow_columns: int = 2,
        threshold: int = 820,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cards = cards
        self._wide_columns = wide_columns
        self._narrow_columns = narrow_columns
        self._threshold = threshold
        self._columns = wide_columns
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(0)
        self._row = build_kpi_row(cards, columns=wide_columns)
        self._box.addWidget(self._row)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        width = self.width()
        if width <= 0:
            return
        if width < self._threshold and self._columns != self._narrow_columns:
            self._rebuild(self._narrow_columns)
        elif width > self._threshold + self.HYSTERESIS and self._columns != self._wide_columns:
            self._rebuild(self._wide_columns)

    def _rebuild(self, columns: int) -> None:
        # 先让新网格接管卡片（reparent），再销毁旧容器
        new_row = build_kpi_row(self._cards, columns=columns)
        self._box.addWidget(new_row)
        old_row = self._row
        self._row = new_row
        self._columns = columns
        self._box.removeWidget(old_row)
        old_row.deleteLater()
