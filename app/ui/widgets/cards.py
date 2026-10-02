"""基础组件：模块卡片、KPI 卡片、徽标、状态点、分段控件、状态胶囊。

视觉规范见 ``app/ui/theme.py``（Deep Telemetry 设计系统）：
- 卡片 = surface1 + 1px 结构边框 + 8px 圆角，头部固定 34px + 底部细分隔线
- KPI = 等宽大数字 + 环比 delta + 迷你趋势条
- 徽标 / 状态点用于表达信号色语义（青=数据流、紫=AI、珊瑚=异常）
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLORS, FONT_MONO, rgba, tone_color

_TONE_KEYS = ("cyan", "violet", "coral", "green", "amber", "muted")


def _repolish(widget: QWidget) -> None:
    """属性（如 tone）变化后刷新样式。"""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class Badge(QLabel):
    """小徽标：等宽字体 + 10% 底色 + 30% 边框。"""

    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setProperty("tone", tone if tone in _TONE_KEYS else "muted")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone if tone in _TONE_KEYS else "muted")
        _repolish(self)


class StatusDot(QLabel):
    """6px 状态圆点（实时/推理/告警/空闲）。"""

    def __init__(self, color: str = COLORS["text_muted"], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusDot")
        self.setFixedSize(6, 6)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background-color: {color}; border-radius: 3px;")


class Pill(QLabel):
    """顶部状态胶囊（等宽小字 + 边框）。"""

    def __init__(self, text: str = "", tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Pill")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def update_pill(self, text: str, tone: str = "") -> None:
        self.setText(text)
        self.setProperty("tone", tone)
        _repolish(self)


class SegmentBar(QFrame):
    """分段切换控件（平台筛选、时间范围、排序方式等）。"""

    selected = Signal(object)  # 选中项的 key

    def __init__(
        self,
        options: list[tuple[str, Any]],
        current: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[Any, QPushButton] = {}

        for index, (label, key) in enumerate(options):
            button = QPushButton(label)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.selected.emit(k))
            self._group.addButton(button, index)
            self._buttons[key] = button
            layout.addWidget(button)
            if current is None and index == 0:
                button.setChecked(True)
            elif current is not None and key == current:
                button.setChecked(True)

    def set_current(self, key: Any) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def current_key(self) -> Any:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return None


class ModuleCard(QFrame):
    """模块卡片：34px 卡片头（标题 + 副标题 + 右侧操作区）+ 内容区。"""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
        header: bool = True,
        dense: bool = False,
        spacing: int = 8,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ModuleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header_layout: QHBoxLayout | None = None
        if header:
            header_frame = QFrame()
            header_frame.setObjectName("CardHeader")
            layout = QHBoxLayout(header_frame)
            layout.setContentsMargins(12, 0, 8, 0)
            layout.setSpacing(8)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("CardSubtitle")
            layout.addWidget(self.title_label)
            layout.addWidget(self.subtitle_label)
            layout.addStretch(1)
            self._header_layout = layout
            outer.addWidget(header_frame)

        self.body = QWidget()
        margin = 0 if dense else 12
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(margin, margin, margin, margin)
        self.body_layout.setSpacing(spacing)
        outer.addWidget(self.body, 1)

    # ------------------------------------------------------------------ #
    def set_title(self, text: str) -> None:
        if self._header_layout is not None:
            self.title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        if self._header_layout is not None:
            self.subtitle_label.setText(text)

    def add_header_widget(self, widget: QWidget) -> None:
        """在卡片头右侧追加控件（按钮、徽标等）。"""
        if self._header_layout is not None:
            self._header_layout.addWidget(widget)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:  # noqa: ANN001 - QLayout
        self.body_layout.addLayout(layout)

    def body_margins(self, left: int, top: int, right: int, bottom: int) -> None:
        self.body_layout.setContentsMargins(left, top, right, bottom)


# 兼容旧命名
SectionCard = ModuleCard


class KpiCard(ModuleCard):
    """KPI 卡片：标签 / 大数值 + 单位 / 环比 / 迷你趋势条。"""

    def __init__(
        self,
        label: str = "",
        unit: str = "",
        parent: QWidget | None = None,
        accent: str = COLORS["cyan"],
    ) -> None:
        super().__init__(parent=parent, header=False)
        self.accent = accent
        self.setMinimumHeight(116)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.label_widget = QLabel(label)
        self.label_widget.setObjectName("KpiLabel")
        self.badge = Badge("", "cyan")
        self.badge.hide()
        top.addWidget(self.label_widget, 1)
        top.addWidget(self.badge)
        self.body_layout.addLayout(top)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(6)
        self.value_label = QLabel("—")
        self.value_label.setObjectName("KpiValue")
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("KpiUnit")
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        self.body_layout.addLayout(value_row)

        self.delta_label = QLabel("")
        self.delta_label.setObjectName("KpiDelta")
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("KpiHint")
        delta_row = QHBoxLayout()
        delta_row.setContentsMargins(0, 0, 0, 0)
        delta_row.setSpacing(8)
        delta_row.addWidget(self.delta_label)
        delta_row.addWidget(self.hint_label, 1)
        self.body_layout.addLayout(delta_row)

        from app.ui.widgets.charts import MiniBars  # 延迟导入，避免循环依赖

        self.mini = MiniBars(accent=accent)
        self.body_layout.addWidget(self.mini)
        self.body_layout.addStretch(1)

    # ------------------------------------------------------------------ #
    def set_data(
        self,
        value: str,
        unit: str = "",
        delta: str = "",
        delta_tone: str = "muted",
        hint: str = "",
        series: list[float] | None = None,
        badge: str = "",
        badge_tone: str = "cyan",
        value_color: str | None = None,
    ) -> None:
        self.value_label.setText(value)
        self.unit_label.setText(unit)
        self.delta_label.setText(delta)
        self.delta_label.setStyleSheet(
            f"color: {tone_color(delta_tone)};"
            f" font-family: {FONT_MONO}; font-size: 11px;"
        )
        self.hint_label.setText(hint)
        self.value_label.setStyleSheet(f"color: {value_color};" if value_color else "")
        if badge:
            self.badge.setText(badge)
            self.badge.set_tone(badge_tone)
            self.badge.show()
        else:
            self.badge.hide()
        self.mini.set_values(series or [])

    # 兼容旧接口
    def set_value(self, value: str, hint: str = "", color: str | None = None) -> None:
        self.set_data(value, hint=hint, value_color=color)


class StatRow(QWidget):
    """标签 + 数值的紧凑行（卡片内的次要指标）。"""

    def __init__(
        self, label: str, value: str = "—", tone: str = "text", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.key_label = QLabel(label)
        self.key_label.setObjectName("HintText")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MonoText")
        if tone != "text":
            self.value_label.setStyleSheet(
                f"color: {tone_color(tone)}; font-family: {FONT_MONO};"
            )
        layout.addWidget(self.key_label, 1)
        layout.addWidget(self.value_label)

    def set_value(self, value: str, tone: str | None = None) -> None:
        self.value_label.setText(value)
        if tone:
            self.value_label.setStyleSheet(
                f"color: {tone_color(tone)}; font-family: {FONT_MONO};"
            )


def build_kpi_row(cards: list[KpiCard], columns: int = 4) -> QWidget:
    """把若干 KPI 卡片排成网格。"""
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    for index, card in enumerate(cards):
        grid.addWidget(card, index // columns, index % columns)
    for col in range(columns):
        grid.setColumnStretch(col, 1)
    return container


def hint_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintText")
    label.setWordWrap(True)
    return label


def caption_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("PageCaption")
    return label


def muted_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("MutedText")
    label.setWordWrap(True)
    return label


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def horizontal_line(color: str = "border_subtle") -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {COLORS[color]}; border: none;")
    return line


def vstack(*widgets: QWidget, spacing: int = 8, margins: int = 0) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def hstack(*widgets: QWidget, spacing: int = 8, margins: int = 0) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def chip(text: str, tone: str = "muted") -> QLabel:
    """行内小胶囊（热词、标签）：透明底 + 细边框。"""
    label = QLabel(text)
    color = tone_color(tone)
    label.setStyleSheet(
        f"background-color: transparent; color: {color};"
        f" border: 1px solid {rgba(color, 60)}; padding: 3px 9px;"
        " border-radius: 10px; font-size: 11px;"
    )
    return label
