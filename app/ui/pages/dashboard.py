"""数据看板页（对齐设计稿 `_1 数据看板`）。

结构：顶部工具条（平台/时间范围分段 + 刷新 + 导出）→ KPI 四卡（带迷你趋势）
→ 双平台趋势（左） + 平台流量与价值转化漏斗（右）→ 作品表现 TOP。

说明：AI 洞察摘要已移至「AI 决策助手」页（两页共用同一组件），看板聚焦数据本身。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config import platform_label
from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.widgets.responsive import PageScrollArea, ResponsiveKpiRow, ResponsiveSplitter
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import (
    KpiCard,
    ModuleCard,
    SegmentBar,
    muted_label,
)
from app.ui.widgets.charts import FunnelBars, TrendChart
from app.ui.widgets.tables import Column, DictTableModel, configure_table

TOP_COLUMNS = [
    Column("platform", "平台", 60),
    Column("title", "作品", 260),
    Column("account", "账号", 90),
    Column("daily_views", "当日播放", 96, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("engagement_rate", "互动率", 82, lambda v: f"{float(v):.2f}%", Qt.AlignRight | Qt.AlignVCenter),
    Column("growth_rate", "日增长", 76, lambda v: f"{float(v):.2f}%", Qt.AlignRight | Qt.AlignVCenter),
    Column("health_score", "健康度", 70, lambda v: f"{float(v):.1f}", Qt.AlignRight | Qt.AlignVCenter),
]

class DashboardPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._top_splitter_ready = False
        self._build()
        context.metrics_updated.connect(self.render)

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = PageScrollArea()
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        root.addWidget(self._build_toolbar())

        self.kpi_cards = [
            KpiCard("双平台总播放量 · TOTAL VIEWS", "次", accent=COLORS["cyan"]),
            KpiCard("综合互动率 · AVG ENGAGEMENT", "%", accent=COLORS["violet"]),
            KpiCard("当日净增粉丝 · NET GROWTH", "人", accent=COLORS["coral"]),
            KpiCard("传播健康度 · HEALTH SCORE", "/100", accent=COLORS["green"]),
        ]
        root.addWidget(ResponsiveKpiRow(self.kpi_cards, wide_columns=4, narrow_columns=2, threshold=820))

        middle = ResponsiveSplitter(
            threshold=780,
            horizontal_sizes=[900, 460],
            vertical_sizes=[420, 470],
            stacked_min_height=930,
        )
        self.trend_card = ModuleCard("双平台播放与互动趋势")
        self.trend_card.add_widget(muted_label("每日累计快照采样｜珊瑚点 = 异常拐点｜紫色虚线 = 传播健康度"))
        self.trend_chart = TrendChart()
        self.trend_card.add_widget(self.trend_chart, 1)
        middle.addWidget(self.trend_card)

        self.funnel_card = ModuleCard("平台流量与价值转化漏斗")
        self.funnel_card.setMinimumWidth(360)
        self.funnel_bars = FunnelBars()
        self.funnel_card.add_widget(self.funnel_bars, 1)
        self.funnel_card.add_widget(muted_label("累计口径：曝光 → 点赞 → 深度互动 → 关注转化"))
        middle.addWidget(self.funnel_card)
        middle.setSizes([900, 460])
        # 不直接加入页面：它与「作品表现 TOP」一起放进可上下拖动的 body_splitter

        self.top_card = ModuleCard("作品表现 TOP")
        self.top_model = DictTableModel(TOP_COLUMNS)
        self.top_table = QTableView()
        self.top_table.setModel(self.top_model)
        configure_table(self.top_table, row_height=30, stretch_column=1, platform_column=0)
        self.top_card.add_widget(self.top_table, 1)
        self.top_card.setMinimumHeight(150)  # 缩放下限：不会被拖到看不见内容

        # 上：趋势 + 漏斗；下：作品表现 TOP
        # 中间的分隔条可**上下拖动**，用来缩放 TOP 区域高度（占比自动记住）
        middle.setMinimumHeight(220)  # 上半区缩放下限（趋势图仍可用）
        self.body_splitter = QSplitter(Qt.Vertical)
        self.body_splitter.setObjectName("BodySplitter")
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(6)
        self.body_splitter.setMinimumHeight(560)
        self.body_splitter.addWidget(middle)
        self.body_splitter.addWidget(self.top_card)
        self.body_splitter.setStretchFactor(0, 1)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.splitterMoved.connect(self._on_top_splitter_moved)
        self._top_save_timer = QTimer(self)
        self._top_save_timer.setSingleShot(True)
        self._top_save_timer.setInterval(600)
        self._top_save_timer.timeout.connect(self._persist_top_ratio)
        root.addWidget(self.body_splitter, 1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------ #
    # 作品表现 TOP 区域缩放（上下拖动分隔条，占比持久化）
    # ------------------------------------------------------------------ #
    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt 命名
        super().resizeEvent(event)
        # 首次拿到真实高度后再按保存的比例分配（布局未完成时 setSizes 会被忽略）
        if not self._top_splitter_ready and self.body_splitter.height() > 0:
            self._top_splitter_ready = True
            QTimer.singleShot(0, self._apply_saved_top_ratio)

    def _apply_saved_top_ratio(self) -> None:
        """按配置里的占比恢复 TOP 区域高度（限制在 20%~80%）。"""
        total = self.body_splitter.height()
        if total <= 0:
            return
        ratio = min(0.8, max(0.2, float(self.context.settings.dashboard_top_ratio or 0.45)))
        top = int(total * ratio)
        self.body_splitter.setSizes([total - top, top])

    def _on_top_splitter_moved(self, _position: int) -> None:
        """拖动过程中防抖：松手 600ms 后再写配置，避免频繁写盘。"""
        self._top_save_timer.start()

    def _persist_top_ratio(self) -> None:
        sizes = self.body_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        ratio = round(sizes[1] / total, 4)
        current = float(self.context.settings.dashboard_top_ratio or 0.45)
        if abs(ratio - current) < 0.01:
            return
        self.context.save_preference(dashboard_top_ratio=ratio)
        self.context.status_message.emit(
            f"作品表现 TOP 区域高度已调整为 {ratio:.0%}（下次启动沿用；拖动分隔条可再调）"
        )

    def _build_toolbar(self) -> QWidget:
        bar = ToolbarRow(spacing=10)
        title = bar.add(QLabel("数据看板"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")

        self.platform_bar = SegmentBar(
            [
                ("全部平台", ""),
                (platform_label("bilibili"), "bilibili"),
                (platform_label("douyin"), "douyin"),
            ],
            current="",
        )
        self.platform_bar.selected.connect(self._on_platform_changed)
        bar.add(self.platform_bar, ToolbarRow.HIGH)

        self.range_bar = SegmentBar([("近 7 天", 7), ("近 30 天", 30), ("近 90 天", 90)], current=30)
        bar.add(self.range_bar, ToolbarRow.HIGH)

        self.date_hint = muted_label("尚未载入分析结果")
        self.date_hint.setWordWrap(False)
        bar.add(self.date_hint, ToolbarRow.LOW)
        bar.add_stretch()

        self.refresh_button = QPushButton("刷新分析结果")
        self.refresh_button.clicked.connect(self._run_analysis)
        bar.add(self.refresh_button, ToolbarRow.HIGH)

        self.export_button = QPushButton("导出分析报表")
        self.export_button.clicked.connect(self.context.export_analysis)
        bar.add(self.export_button, ToolbarRow.NORMAL)

        self.analyze_button = QPushButton("一键全量分析")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self._run_analysis)
        bar.add(self.analyze_button, ToolbarRow.REQUIRED)
        return bar

    # ------------------------------------------------------------------ #
    def _run_analysis(self) -> None:
        platform = self.platform_bar.current_key() or None
        self.context.run_analysis(platform=platform)

    def _on_platform_changed(self, _key: object) -> None:
        self._run_analysis()

    # ------------------------------------------------------------------ #
    def render(self, metrics: dict[str, Any]) -> None:
        if not metrics:
            self.date_hint.setText("尚未载入分析结果：点击「立即同步数据」后再执行分析")
            self.trend_chart.set_data([])
            self.funnel_bars.set_rows([])
            self.top_model.set_rows([])
            for card in self.kpi_cards:
                card.set_data("—")
            return

        head = metrics.get("headline", {}) or {}
        span = metrics.get("data_span", {}) or {}
        trend = metrics.get("trend", []) or []
        compare = metrics.get("platform_compare", {}) or {}
        self.date_hint.setText(
            f"{metrics.get('stat_date')}｜{span.get('start')} ~ {span.get('end')}"
            f"｜作品 {span.get('video_count')} 个｜口径 {metrics.get('platform') or '全平台'}"
        )

        growth = float(head.get("daily_views_growth") or 0)
        self.kpi_cards[0].set_data(
            f"{int(head.get('total_views', 0)):,}",
            "次",
            f"↗ {growth:+.2f}% 环比",
            "green" if growth >= 0 else "coral",
            f"当日新增 {int(head.get('daily_views', 0)):,}",
            [float(r.get("daily_views", 0)) for r in trend],
        )
        self.kpi_cards[1].set_data(
            f"{float(head.get('engagement_rate', 0)):.2f}",
            "%",
            f"累计口径 {float(head.get('cum_engagement_rate', 0)):.2f}%",
            "cyan",
            f"当日互动 {int(head.get('daily_engagement', 0)):,}",
            [float(r.get("engagement_rate", 0)) for r in trend],
        )
        self.kpi_cards[2].set_data(
            f"{int(head.get('follower_gain', 0)):,}",
            "人",
            "双平台合计",
            "coral",
            f"活跃作品 {head.get('active_videos', 0)}/{head.get('video_count', 0)}",
            [float(r.get("follower_gain", 0)) for r in trend],
        )
        health = float(head.get("health_score", 0))
        health_tone = "green" if health >= 60 else ("amber" if health >= 40 else "coral")
        self.kpi_cards[3].set_data(
            f"{health:.1f}",
            "/100",
            "互动率·收藏率·分享率·增长率 加权",
            health_tone,
            "≥60 视为健康区间",
            [float(r.get("health_score", 0)) for r in trend],
        )

        self.trend_chart.set_data(
            trend,
            metrics.get("trend_by_platform") or {},
            metrics.get("overall_anomalies") or [],
        )
        compare_text = "｜".join(
            f"{platform_label(k)} 近7日 {int(v.get('week_daily_views', 0)):,}" for k, v in compare.items()
        )
        self.trend_card.set_subtitle(
            f"{len(trend)} 天样本" + (f"｜{compare_text}" if compare_text else "")
        )

        self.funnel_bars.set_rows(
            [(row.get("label", ""), int(row.get("value", 0))) for row in (metrics.get("funnel") or [])]
        )
        self.top_model.set_rows(metrics.get("top_videos") or [])
        self.top_card.set_subtitle(f"按当日新增播放排序｜共 {len(metrics.get('top_videos') or [])} 条")
