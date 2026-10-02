"""页面顶部工具栏组件：控件尺寸固定、空间不足时整体隐藏，绝不挤压或变形。

对应需求：窗口缩放 / 最大化时，顶部的标签与按钮**大小和位置都不变**，
空间不足时只有「完整显示」与「不显示」两种状态，不允许出现半截文字、截断或拉伸变形。

做法：
1. 放入工具栏的控件横向尺寸固定为其自然尺寸（``sizeHint``），布局无法压缩或拉伸它；
2. 宽度不足时按 ``priority`` 从低到高**整体隐藏**控件（一次隐藏一个完整控件，绝不裁切）；
3. 必需控件（标题、主操作按钮）永不隐藏，因此不会残缺。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)


class ToolbarRow(QWidget):
    """一行自适应工具栏。

    用法::

        bar = ToolbarRow()
        bar.add(title, priority=ToolbarRow.REQUIRED)
        bar.add(platform_bar, priority=ToolbarRow.HIGH)
        bar.add(search_edit, priority=ToolbarRow.NORMAL)
        bar.add_stretch()
        bar.add(analyze_button, priority=ToolbarRow.REQUIRED)
    """

    #: 优先级：数字越小越重要（先隐藏数字大的）
    REQUIRED = 0  # 必需：始终保持显示（标题、主操作）
    HIGH = 20  # 重要：仅在很窄时隐藏
    NORMAL = 50  # 常规：空间紧张时隐藏
    LOW = 80  # 次要：最先隐藏（辅助说明、路径提示等）

    def __init__(
        self,
        spacing: int = 10,
        margins: tuple[int, int, int, int] = (0, 0, 0, 0),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._box = QHBoxLayout(self)
        self._box.setContentsMargins(*margins)
        self._box.setSpacing(spacing)
        self._box.setSizeConstraint(QLayout.SetNoConstraint)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._entries: list[tuple[int, QWidget]] = []
        self._spacer: QSpacerItem | None = None
        self._spacing = spacing
        self._applying = False

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    def add(self, widget: QWidget, priority: int = NORMAL) -> QWidget:
        """加入控件；控件横向尺寸固定为其自然尺寸，不会被压缩或拉伸。"""
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        widget.installEventFilter(self)  # 文本变化 → 自动重算显示策略
        self._entries.append((priority, widget))
        if self._spacer is None:
            self._box.addWidget(widget)
        else:
            self._box.insertWidget(self._box.count() - 1, widget)
        return widget

    def add_stretch(self) -> ToolbarRow:
        """加入弹性空隙（让其后加入的控件靠右排列）。"""
        if self._spacer is None:
            self._spacer = QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)
            self._box.addSpacerItem(self._spacer)
        return self

    def fill_height(self) -> ToolbarRow:
        """让工具栏填满父容器高度（用于顶栏这类固定高度的容器）。"""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return self

    def refresh(self) -> None:
        """控件文本变化后调用：按新的自然尺寸重新计算显示策略。"""
        self._apply()

    # ------------------------------------------------------------------ #
    # 自适应
    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().resizeEvent(event)
        self._apply()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        super().showEvent(event)
        self._apply()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt 命名约定
        """控件文本 / 尺寸变化时重新计算显示策略。"""
        if event.type() == QEvent.LayoutRequest and not self._applying:
            QTimer.singleShot(0, self._apply)
        return False

    @staticmethod
    def _is_fixed_width(widget: QWidget) -> bool:
        """控件是否已自行固定宽度（状态点、固定宽输入框）。"""
        return widget.minimumWidth() > 0 and widget.minimumWidth() == widget.maximumWidth()

    @staticmethod
    def _natural_width(widget: QWidget) -> int:
        """控件在「不变形」前提下的最小宽度。"""
        if ToolbarRow._is_fixed_width(widget):
            return widget.minimumWidth()
        return max(widget.sizeHint().width(), widget.minimumSizeHint().width())

    def _apply(self) -> None:
        """按可用宽度决定每个控件显示与否：只整体隐藏，不压缩。"""
        if self._applying:
            return
        entries = self._entries
        if not entries:
            return
        self._applying = True
        try:
            available = self.width()
            hidden: set[int] = set()
            # 从最不重要（priority 数值最大，同级时更靠右）开始逐个整体隐藏，直到放得下
            order = sorted(range(len(entries)), key=lambda i: (-entries[i][0], -i))
            for index in order:
                if self._needed_width(hidden) <= available:
                    break
                if entries[index][0] <= self.REQUIRED:
                    break  # 必需控件不隐藏：由页面最小宽度保证一定放得下
                hidden.add(index)

            for position, (_priority, widget) in enumerate(entries):
                should_show = position not in hidden
                if widget.isVisible() != should_show:
                    widget.setVisible(should_show)
                elif should_show and not self._is_fixed_width(widget):
                    # 锁死自然宽度：布局无法把它压窄，从而不会出现半截文字或变形
                    natural = self._natural_width(widget)
                    if widget.minimumWidth() != natural:
                        widget.setMinimumWidth(natural)
        finally:
            self._applying = False

    def _needed_width(self, hidden: set[int]) -> int:
        """隐藏指定控件后，放得下所有可见控件所需的总宽度。"""
        widths = [
            self._natural_width(widget)
            for position, (_priority, widget) in enumerate(self._entries)
            if position not in hidden
        ]
        if not widths:
            return 0
        return sum(widths) + self._spacing * (len(widths) - 1)
