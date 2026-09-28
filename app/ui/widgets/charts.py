"""图表与数据可视化组件（QtCharts + QPainter 自绘）。

- ``MiniBars``         KPI 卡片底部的迷你柱状趋势
- ``TrendChart``       双平台播放趋势（含传播健康度虚线 + 异常拐点标记）
- ``PlatformBarChart`` 双平台指标分组对比
- ``FunnelBars``       流量与价值转化漏斗（曝光 → 点赞 → 深度互动 → 关注）
- ``SentimentBar``     评论情感极性分布条
- ``TopicCloud``       核心热词标签云（按权重着色/定尺寸）

配色遵循设计系统：B站=青 #00AEEC、抖音=珊瑚 #FE2C55、AI/合成=紫 #8B5CF6。
"""

from __future__ import annotations

import random
from typing import Any

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QDateTimeAxis,
    QLineSeries,
    QPieSeries,
    QScatterSeries,
    QValueAxis,
)
from PySide6.QtCore import QDateTime, QMargins, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.config import platform_label
from app.ui.theme import COLORS, PLATFORM_COLORS, SENTIMENT_COLORS, rgba

def _health_color() -> str:
    """健康度曲线颜色（运行时取值，随主题变化）。"""
    return COLORS["violet"]


def _grid_color() -> QColor:
    return QColor(COLORS["border_subtle"])


def _axis_pen() -> QPen:
    pen = QPen(_grid_color())
    pen.setWidth(1)
    return pen


def _style_chart(chart: QChart, legend: bool = True) -> None:
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setMargins(QMargins(4, 4, 4, 4))
    chart.legend().setVisible(legend)
    chart.legend().setLabelColor(QColor(COLORS["text_dim"]))
    chart.legend().setAlignment(Qt.AlignBottom)
    chart.setAnimationOptions(QChart.NoAnimation)


def _reset_chart(chart: QChart, owner: QWidget) -> None:
    """安全清空图表（刷新数据时调用）。

    不能用 ``QChart.removeAllSeries()``：它会直接销毁底层 C++ 对象，
    而 Python 侧仍持有包装对象，刷新几次后就会触发访问违规崩溃。
    这里逐个解除关联（``removeSeries`` / ``removeAxis`` 只释放所有权、不删除），
    再把对象挂到 owner 名下，由 Qt 父子关系统一回收。
    """
    for series in list(chart.series()):
        for axis in list(chart.axes()):
            try:
                series.detachAxis(axis)
            except RuntimeError:
                pass
        chart.removeSeries(series)
        series.setParent(owner)
    for axis in list(chart.axes()):
        chart.removeAxis(axis)
        axis.setParent(owner)


# --------------------------------------------------------------------------- #
# 自绘：迷你柱状趋势
# --------------------------------------------------------------------------- #
class MiniBars(QWidget):
    """极小柱状趋势（无坐标轴），用于 KPI 卡片底部。"""

    def __init__(self, accent: str = COLORS["cyan"], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._accent = accent
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, values: list[float]) -> None:
        self._values = [float(v or 0) for v in (values or [])][-24:]
        self.update()

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        if not self._values:
            painter.setPen(QPen(QColor(COLORS["text_muted"])))
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, "— 暂无趋势 —")
            painter.end()
            return

        count = len(self._values)
        peak = max(self._values) or 1.0
        gap = 2
        bar_width = max(2.0, (rect.width() - gap * (count - 1)) / count)
        baseline = rect.bottom() - 1
        max_height = rect.height() - 2

        painter.setPen(Qt.NoPen)
        for index, value in enumerate(self._values):
            height = max(2.0, max_height * (value / peak))
            x = rect.left() + index * (bar_width + gap)
            if index >= count - 3:
                color = QColor(self._accent)
                color.setAlpha(230)
            else:
                color = QColor(COLORS["surface3"])
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, baseline - height, bar_width, height), 1.5, 1.5)
        painter.end()


# --------------------------------------------------------------------------- #
# 自绘：漏斗
# --------------------------------------------------------------------------- #
class FunnelBars(QWidget):
    """流量与价值转化漏斗：每行 = 标签 + 横条 + 数值(占比)。"""

    COLORS_SEQUENCE = (
        COLORS["cyan"],
        COLORS["violet"],
        COLORS["amber"],
        COLORS["green"],
        COLORS["coral"],
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, int]] = []
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_rows(self, rows: list[tuple[str, int]]) -> None:
        self._rows = [(str(label), int(value)) for label, value in (rows or [])]
        self.setMinimumHeight(max(160, 38 * len(self._rows) + 12))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 6, 0, -6)
        if not self._rows:
            painter.setPen(QPen(QColor(COLORS["text_muted"])))
            painter.drawText(rect, Qt.AlignCenter, "暂无漏斗数据")
            painter.end()
            return

        total = max(self._rows[0][1], 1)
        label_font = QFont(self.font())
        label_font.setPointSize(10)
        value_font = QFont(self.font())
        value_font.setPointSize(10)
        value_font.setBold(True)

        row_height = rect.height() / len(self._rows)
        bar_height = min(18.0, row_height * 0.46)

        for index, (label, value) in enumerate(self._rows):
            top = rect.top() + index * row_height
            ratio = value / total if total else 0.0
            percent = ratio * 100

            painter.setFont(label_font)
            painter.setPen(QColor(COLORS["text_dim"]))
            text_rect = QRectF(rect.left(), top, rect.width(), row_height * 0.44)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, label)

            painter.setFont(value_font)
            painter.setPen(QColor(COLORS["text"]))
            painter.drawText(
                text_rect, Qt.AlignRight | Qt.AlignVCenter, f"{value:,}  ({percent:.2f}%)"
            )

            track = QRectF(rect.left(), top + row_height * 0.48, rect.width(), bar_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["surface3"]))
            painter.drawRoundedRect(track, 3, 3)

            filled = QRectF(
                track.left(), track.top(), max(3.0, track.width() * ratio), track.height()
            )
            painter.setBrush(QColor(self.COLORS_SEQUENCE[index % len(self.COLORS_SEQUENCE)]))
            painter.drawRoundedRect(filled, 3, 3)

        painter.end()


# --------------------------------------------------------------------------- #
# 自绘：情感极性条
# --------------------------------------------------------------------------- #
class SentimentBar(QWidget):
    """评论情感极性分布：单行分段条 + 图例。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = {"positive": 0, "neutral": 0, "negative": 0}
        self.setFixedHeight(84)

    def set_data(self, sentiment: dict[str, Any]) -> None:
        self._data = {
            "positive": int(sentiment.get("positive") or 0),
            "neutral": int(sentiment.get("neutral") or 0),
            "negative": int(sentiment.get("negative") or 0),
        }
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        total = sum(self._data.values())

        bar = QRectF(rect.left(), rect.top() + 4, rect.width(), 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["surface3"]))
        painter.drawRoundedRect(bar, 5, 5)

        if total:
            x = bar.left()
            for key in ("positive", "neutral", "negative"):
                value = self._data[key]
                if value <= 0:
                    continue
                width = bar.width() * value / total
                painter.setBrush(QColor(SENTIMENT_COLORS[key]))
                painter.drawRoundedRect(QRectF(x, bar.top(), max(2.0, width), bar.height()), 5, 5)
                x += width

        legend_font = QFont(self.font())
        legend_font.setPointSize(10)
        painter.setFont(legend_font)
        y = bar.bottom() + 10
        for key, text in (("positive", "正面"), ("neutral", "中性"), ("negative", "负面")):
            value = self._data[key]
            percent = (value / total * 100) if total else 0.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(SENTIMENT_COLORS[key]))
            painter.drawEllipse(QRectF(rect.left(), y + 4, 7, 7))
            painter.setPen(QColor(COLORS["text_dim"]))
            painter.drawText(
                QRectF(rect.left() + 12, y, rect.width() - 12, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{text} {value:,} 条（{percent:.1f}%）",
            )
            y += 18
        painter.end()


# --------------------------------------------------------------------------- #
# 自绘：热词标签云
# --------------------------------------------------------------------------- #
class TopicCloud(QWidget):
    """核心热词：按权重着色与定尺寸的胶囊标签，贪心排布避免重叠。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(200)
        self._words: list[dict[str, Any]] = []
        self._items: list[tuple[str, QRectF, QFont, QColor]] = []

    def set_words(self, words: list[dict[str, Any]]) -> None:
        self._words = list(words or [])
        self._relayout()

    # 兼容旧接口名
    def set_data(self, words: list[dict[str, Any]]) -> None:
        self.set_words(words)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        self._items.clear()
        words = self._words[:40]
        if not words or self.width() < 60 or self.height() < 40:
            self.update()
            return

        rng = random.Random(11)
        width, height = self.width(), self.height()
        max_count = max(int(w.get("count", 1)) for w in words) or 1
        palette = [
            COLORS["cyan"],
            COLORS["violet"],
            COLORS["coral"],
            COLORS["green"],
            COLORS["amber"],
        ]
        occupied: list[QRectF] = []

        for index, item in enumerate(words):
            word = str(item.get("word", ""))
            count = int(item.get("count", 1))
            if not word:
                continue
            weight = count / max_count
            size = int(11 + 13 * (weight ** 0.6))
            font = QFont(self.font())
            font.setPointSize(size)
            font.setBold(weight > 0.5)
            metrics = QFontMetrics(font)
            box = QRectF(0, 0, metrics.horizontalAdvance(word) + 38, size + 16)

            for _ in range(600):
                x = rng.uniform(0, max(0.0, width - box.width()))
                y = rng.uniform(0, max(0.0, height - box.height()))
                candidate = QRectF(x, y, box.width(), box.height())
                if all(not candidate.intersects(other) for other in occupied):
                    occupied.append(candidate)
                    if weight > 0.55:
                        color = QColor(COLORS["cyan"] if index % 2 else COLORS["violet"])
                    elif weight > 0.28:
                        color = QColor(palette[index % len(palette)])
                    else:
                        color = QColor(COLORS["text_dim"])
                    self._items.append((f"{word} {count}", candidate, font, color))
                    break
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self._items:
            painter.setPen(QPen(QColor(COLORS["text_muted"])))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无热词数据")
            painter.end()
            return
        for text, rect, font, color in self._items:
            painter.setPen(QPen(QColor(rgba(color.name(), 80)), 1))
            painter.setBrush(QColor(rgba(color.name(), 26)))
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            painter.drawPath(path)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignCenter, text)
        painter.end()


class WordCloudWidget(TopicCloud):
    """向后兼容别名（早期版本命名）。"""


# --------------------------------------------------------------------------- #
# QtCharts：双平台趋势
# --------------------------------------------------------------------------- #
class TrendChart(QChartView):
    """双平台播放趋势 + 传播健康度（虚线，右轴）+ 异常拐点标记。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        chart = QChart()
        super().__init__(chart, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(280)
        _style_chart(chart)

    def set_data(
        self,
        trend: list[dict[str, Any]],
        by_platform: dict[str, list[dict[str, Any]]] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
    ) -> None:
        chart = self.chart()
        _reset_chart(chart, self)
        if not trend:
            chart.legend().setVisible(False)
            return
        chart.legend().setVisible(True)

        series_list: list[QLineSeries] = []
        for platform, rows in (by_platform or {}).items():
            if not rows:
                continue
            serie = QLineSeries()
            serie.setName(platform_label(platform))
            serie.setPen(QPen(QColor(PLATFORM_COLORS.get(platform, COLORS["cyan"])), 2))
            for row in rows:
                stamp = QDateTime.fromString(
                    str(row["stat_date"]), "yyyy-MM-dd"
                ).toMSecsSinceEpoch()
                serie.append(stamp, float(row.get("daily_views", 0)))
            series_list.append(serie)

        health = QLineSeries()
        health.setName("传播健康度")
        health.setPen(QPen(QColor(_health_color()), 2, Qt.DashLine))
        for row in trend:
            stamp = QDateTime.fromString(str(row["stat_date"]), "yyyy-MM-dd").toMSecsSinceEpoch()
            health.append(stamp, float(row.get("health_score", 0)))

        for serie in series_list:
            chart.addSeries(serie)
        chart.addSeries(health)

        axis_x = QDateTimeAxis()
        axis_x.setFormat("MM-dd")
        axis_x.setTickCount(min(8, max(2, len(trend))))
        axis_x.setLabelsColor(QColor(COLORS["text_muted"]))
        axis_x.setGridLineColor(_grid_color())
        axis_x.setLinePen(_axis_pen())
        chart.addAxis(axis_x, Qt.AlignBottom)

        left = QValueAxis()
        left.setTitleText("新增播放")
        left.setLabelFormat("%.0f")
        left.setLabelsColor(QColor(COLORS["text_muted"]))
        left.setGridLineColor(_grid_color())
        left.setLinePen(_axis_pen())
        peak = max(
            [float(r.get("daily_views", 0)) for r in trend]
            + [
                float(r.get("daily_views", 0))
                for rows in (by_platform or {}).values()
                for r in rows
            ]
            + [1.0]
        )
        left.setRange(0, peak * 1.18)
        chart.addAxis(left, Qt.AlignLeft)

        right = QValueAxis()
        right.setTitleText("健康度")
        right.setRange(0, 100)
        right.setLabelsColor(QColor(COLORS["text_muted"]))
        right.setGridLineColor(QColor(0, 0, 0, 0))
        right.setLinePen(_axis_pen())
        chart.addAxis(right, Qt.AlignRight)

        for serie in series_list:
            serie.attachAxis(axis_x)
            serie.attachAxis(left)
        health.attachAxis(axis_x)
        health.attachAxis(right)

        points_by_date = {str(row["stat_date"]): float(row.get("daily_views", 0)) for row in trend}
        markers = QScatterSeries()
        markers.setName("异常拐点")
        markers.setMarkerSize(9.0)
        markers.setColor(QColor(COLORS["coral"]))
        markers.setBorderColor(QColor(COLORS["surface1"]))
        added = False
        for item in (anomalies or [])[:8]:
            date_key = str(item.get("stat_date"))
            if date_key in points_by_date:
                stamp = QDateTime.fromString(date_key, "yyyy-MM-dd").toMSecsSinceEpoch()
                markers.append(stamp, points_by_date[date_key])
                added = True
        if added:
            chart.addSeries(markers)
            markers.attachAxis(axis_x)
            markers.attachAxis(left)

        axis_x.setRange(
            QDateTime.fromString(str(trend[0]["stat_date"]), "yyyy-MM-dd"),
            QDateTime.fromString(str(trend[-1]["stat_date"]), "yyyy-MM-dd"),
        )


# --------------------------------------------------------------------------- #
# QtCharts：平台对比柱状 / 情感环形
# --------------------------------------------------------------------------- #
class PlatformBarChart(QChartView):
    """双平台分组柱状对比。"""

    METRICS: tuple[tuple[str, str], ...] = (
        ("daily_views", "当日新增播放"),
        ("daily_engagement", "当日互动"),
        ("follower_gain", "当日涨粉"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        chart = QChart()
        super().__init__(chart, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(240)
        _style_chart(chart)

    def set_data(self, compare: dict[str, dict[str, Any]]) -> None:
        chart = self.chart()
        _reset_chart(chart, self)
        if not compare:
            chart.legend().setVisible(False)
            return
        chart.legend().setVisible(True)

        series = QBarSeries()
        for platform, data in compare.items():
            bar_set = QBarSet(platform_label(platform))
            bar_set.setColor(QColor(PLATFORM_COLORS.get(platform, COLORS["cyan"])))
            bar_set.setBorderColor(QColor(COLORS["surface1"]))
            for key, _label in self.METRICS:
                bar_set.append(float(data.get(key, 0) or 0))
            series.append(bar_set)

        chart.addSeries(series)
        axis_x = QBarCategoryAxis()
        axis_x.append([label for _key, label in self.METRICS])
        axis_x.setLabelsColor(QColor(COLORS["text_muted"]))
        axis_x.setGridLineVisible(False)
        axis_x.setLinePen(_axis_pen())
        chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        axis_y.setLabelsColor(QColor(COLORS["text_muted"]))
        axis_y.setGridLineColor(_grid_color())
        axis_y.setLinePen(_axis_pen())
        max_value = max(
            (
                float(data.get(key, 0) or 0)
                for data in compare.values()
                for key, _label in self.METRICS
            ),
            default=1,
        )
        axis_y.setRange(0, max_value * 1.2)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)


class SentimentPie(QChartView):
    """评论情感环形图。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        chart = QChart()
        super().__init__(chart, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(200)
        _style_chart(chart)

    def set_data(self, sentiment: dict[str, Any]) -> None:
        chart = self.chart()
        _reset_chart(chart, self)
        total = int(sentiment.get("total") or 0)
        if not total:
            chart.legend().setVisible(False)
            return
        chart.legend().setVisible(True)
        series = QPieSeries()
        series.setHoleSize(0.55)
        for key, label in (("positive", "正面"), ("neutral", "中性"), ("negative", "负面")):
            count = int(sentiment.get(key) or 0)
            if count <= 0:
                continue
            slice_ = series.append(f"{label} {count}", count)
            slice_.setColor(QColor(SENTIMENT_COLORS[key]))
            slice_.setBorderColor(QColor(COLORS["surface1"]))
            slice_.setLabelColor(QColor(COLORS["text_dim"]))
        chart.addSeries(series)


__all__ = [
    "MiniBars",
    "FunnelBars",
    "SentimentBar",
    "TopicCloud",
    "WordCloudWidget",
    "TrendChart",
    "PlatformBarChart",
    "SentimentPie",
]
