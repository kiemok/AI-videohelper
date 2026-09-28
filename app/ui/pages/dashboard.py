"""数据看板页（对齐设计稿 `_1 数据看板`）。

结构：顶部工具条（平台/时间范围分段 + 刷新 + 导出）→ KPI 四卡（带迷你趋势）
→ 双平台趋势（左） + 平台流量与价值转化漏斗（右）
→ 异常拐点检测日志（左） + AI 快速创作洞察摘要（右）→ 作品表现 TOP。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config import platform_label
from app.ui.context import AppContext
from app.ui.theme import COLORS, tone_color
from app.ui.widgets.cards import (
    KpiCard,
    ModuleCard,
    SegmentBar,
    build_kpi_row,
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

_KIND_TONE = {
    "spike": ("异常放量", "coral"),
    "drop": ("衰减预警", "amber"),
    "recover": ("长尾回温", "green"),
    "fade": ("增长转负", "violet"),
}


class DashboardPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._build()
        context.metrics_updated.connect(self.render)
        context.report_updated.connect(self._render_brief)

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        root.addWidget(self._build_toolbar())

        self.kpi_cards = [
            KpiCard("双平台总播放量 · TOTAL VIEWS", "次", accent=COLORS["cyan"]),
            KpiCard("综合互动率 · AVG ENGAGEMENT", "%", accent=COLORS["violet"]),
            KpiCard("当日净增粉丝 · NET GROWTH", "人", accent=COLORS["coral"]),
            KpiCard("传播健康度 · HEALTH SCORE", "/100", accent=COLORS["green"]),
        ]
        root.addWidget(build_kpi_row(self.kpi_cards, columns=4))

        middle = QSplitter(Qt.Horizontal)
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
        root.addWidget(middle, 3)

        bottom = QSplitter(Qt.Horizontal)
        self.anomaly_card = ModuleCard("近期数据异常与拐点检测日志", "实时监控")
        self.anomaly_list = QListWidget()
        self.anomaly_list.setObjectName("LogList")
        self.anomaly_list.setWordWrap(True)
        self.anomaly_card.add_widget(self.anomaly_list, 1)
        bottom.addWidget(self.anomaly_card)

        self.brief_card = ModuleCard("AI 快速创作洞察摘要")
        self.brief_view = QTextBrowser()
        self.brief_card.add_widget(self.brief_view, 1)
        self.brief_action = QPushButton("进入 AI 助手深入解读 →")
        self.brief_action.setObjectName("AiButton")
        self.brief_action.clicked.connect(self._goto_ai)
        self.brief_card.add_widget(self.brief_action)
        bottom.addWidget(self.brief_card)
        bottom.setSizes([740, 620])
        root.addWidget(bottom, 2)

        self.top_card = ModuleCard("作品表现 TOP")
        self.top_model = DictTableModel(TOP_COLUMNS)
        self.top_table = QTableView()
        self.top_table.setModel(self.top_model)
        configure_table(self.top_table, row_height=30, stretch_column=1, platform_column=0)
        self.top_card.add_widget(self.top_table, 1)
        root.addWidget(self.top_card, 2)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("数据看板")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        self.platform_bar = SegmentBar(
            [
                ("全部平台", ""),
                (platform_label("bilibili"), "bilibili"),
                (platform_label("douyin"), "douyin"),
            ],
            current="",
        )
        self.platform_bar.selected.connect(self._on_platform_changed)
        layout.addWidget(self.platform_bar)

        self.range_bar = SegmentBar([("近 7 天", 7), ("近 30 天", 30), ("近 90 天", 90)], current=30)
        layout.addWidget(self.range_bar)

        self.date_hint = muted_label("尚未载入分析结果")
        layout.addWidget(self.date_hint, 1)

        self.refresh_button = QPushButton("刷新分析结果")
        self.refresh_button.clicked.connect(self._run_analysis)
        layout.addWidget(self.refresh_button)

        self.export_button = QPushButton("导出分析报表")
        self.export_button.clicked.connect(self.context.export_analysis)
        layout.addWidget(self.export_button)

        self.analyze_button = QPushButton("一键全量分析")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self._run_analysis)
        layout.addWidget(self.analyze_button)
        return bar

    # ------------------------------------------------------------------ #
    def _run_analysis(self) -> None:
        platform = self.platform_bar.current_key() or None
        self.context.run_analysis(platform=platform)

    def _on_platform_changed(self, _key: object) -> None:
        self._run_analysis()

    def _goto_ai(self) -> None:
        window = self.window()
        if hasattr(window, "nav"):
            window.nav.setCurrentRow(2)

    # ------------------------------------------------------------------ #
    def render(self, metrics: dict[str, Any]) -> None:
        if not metrics:
            self.date_hint.setText("尚未载入分析结果：点击「立即同步数据」后再执行分析")
            self.trend_chart.set_data([])
            self.funnel_bars.set_rows([])
            self.top_model.set_rows([])
            self.anomaly_list.clear()
            self._render_brief()
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
        self._render_anomalies(metrics)
        self.top_model.set_rows(metrics.get("top_videos") or [])
        self.top_card.set_subtitle(f"按当日新增播放排序｜共 {len(metrics.get('top_videos') or [])} 条")
        self._render_brief()

    def _render_anomalies(self, metrics: dict[str, Any]) -> None:
        self.anomaly_list.clear()
        items = list(metrics.get("anomalies") or [])[:12]
        if not items:
            self.anomaly_list.addItem(QListWidgetItem("近 30 天未检测到显著异常拐点"))
            self.anomaly_card.set_subtitle("实时监控")
            return
        for item in items:
            label, tone = _KIND_TONE.get(str(item.get("kind")), ("异常", "muted"))
            entry = QListWidgetItem(
                f"【{label}】{item.get('stat_date')}  {platform_label(str(item.get('platform', '')))}平台  "
                f"《{item.get('title')}》\n"
                f"    {item.get('note')}（当日播放 {int(item.get('daily_views', 0)):,}，"
                f"环比 {item.get('growth_rate')}%）"
            )
            entry.setForeground(QColor(tone_color(tone)))
            self.anomaly_list.addItem(entry)
        self.anomaly_card.set_subtitle(f"共 {len(items)} 条")

    def _render_brief(self) -> None:
        report = self.context.latest_brief()
        if report and report.get("content"):
            source = (
                "本地规则引擎"
                if report.get("is_fallback")
                else f"{report.get('provider')}/{report.get('model')}"
            )
            self.brief_view.setMarkdown(report["content"])
            self.brief_card.set_subtitle(f"{str(report.get('generated_at'))[:16]}｜{source}")
        else:
            self.brief_view.setPlainText(
                "还没有 AI 洞察：到「AI 决策助手」页点击「智能数据决策简报」生成，结果会自动回显在这里。"
            )
            self.brief_card.set_subtitle("")
