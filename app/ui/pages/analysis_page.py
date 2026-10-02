"""内容与评论分析页（对齐设计稿 `_3 内容与评论分析`）。

- 顶部：平台筛选 + 关键词搜索 + 排序方式
- KPI：双端监控作品数 / 评论语料库容量 / 全域情感极性均值
- 作品综合排行（左） ＋ 评论区情感极性与情绪分布（右上） ＋ 核心热词（右下）
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config import PLATFORM_LABELS, platform_label
from app.db.repository import list_videos
from app.ui.context import AppContext
from app.ui.theme import COLORS
from app.ui.export_helper import ExportActions, ExportPayload
from app.ui.widgets.responsive import PageScrollArea, ResponsiveKpiRow, ResponsiveSplitter
from app.ui.widgets.toolbar import ToolbarRow
from app.ui.widgets.cards import (
    KpiCard,
    ModuleCard,
    SegmentBar,
    muted_label,
)
from app.ui.widgets.charts import SentimentBar, TopicCloud
from app.ui.widgets.tables import Column, DictTableModel, configure_table

RANK_COLUMNS = [
    Column("platform", "平台", 56),
    Column("title", "作品标题", 320),
    Column("account", "账号", 76),
    Column("publish_time", "发布日期", 96, lambda v: str(v)[:10] if v else "—"),
    Column("view_count", "累计播放", 88, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("like_count", "点赞", 68, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("comment_count", "评论", 62, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
    Column("favorite_count", "收藏", 62, lambda v: f"{int(v):,}", Qt.AlignRight | Qt.AlignVCenter),
]

_EMOTION_ROWS = (
    ("positive", "赞赏与技术认同"),
    ("neutral", "期待更新与实操催更"),
    ("negative", "质疑与体验争议"),
)


class AnalysisPage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._videos: list[dict[str, Any]] = []
        self._metrics: dict[str, Any] = {}
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
            KpiCard("双端监控作品总数", "部", accent=COLORS["cyan"]),
            KpiCard("评论语料库容量", "条", accent=COLORS["violet"]),
            KpiCard("全域评论情感极性均值", "%", accent=COLORS["green"]),
        ]
        root.addWidget(ResponsiveKpiRow(self.kpi_cards, wide_columns=3, narrow_columns=2, threshold=760))

        middle = ResponsiveSplitter(
            threshold=780,
            horizontal_sizes=[880, 460],
            vertical_sizes=[460, 500],
            stacked_min_height=1000,
        )
        self.rank_card = ModuleCard("双平台作品综合排行", "融合数据模型统一视图")
        self.rank_model = DictTableModel(RANK_COLUMNS)
        self.rank_table = QTableView()
        self.rank_table.setModel(self.rank_model)
        configure_table(self.rank_table, row_height=32, stretch_column=1, platform_column=0)
        self.rank_card.add_widget(self.rank_table, 1)
        self.rank_card.add_widget(
            ExportActions(self._export_payload, self.context.status_message.emit, with_csv=True)
        )
        middle.addWidget(self.rank_card)

        right = QSplitter(Qt.Vertical)
        self.sentiment_card = ModuleCard("评论区情感极性与情绪分布")
        self.sentiment_bar = SentimentBar()
        self.sentiment_card.add_widget(self.sentiment_bar)
        self.emotion_row = QHBoxLayout()
        self.emotion_row.setContentsMargins(0, 0, 0, 0)
        self.emotion_row.setSpacing(8)
        self.emotion_labels: dict[str, QLabel] = {}
        emotion_widget = QWidget()
        emotion_layout = QVBoxLayout(emotion_widget)
        emotion_layout.setContentsMargins(0, 0, 0, 0)
        emotion_layout.setSpacing(4)
        for key, label in _EMOTION_ROWS:
            row = QLabel(f"{label}：—")
            row.setObjectName("HintText")
            self.emotion_labels[key] = row
            emotion_layout.addWidget(row)
        self.sentiment_card.add_widget(emotion_widget)
        right.addWidget(self.sentiment_card)

        self.wordcloud_card = ModuleCard("核心热词词云与高频焦点")
        self.wordcloud = TopicCloud()
        self.wordcloud_card.add_widget(self.wordcloud, 1)
        right.addWidget(self.wordcloud_card)
        right.setSizes([220, 320])
        middle.addWidget(right)
        root.addWidget(middle, 1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_toolbar(self) -> QWidget:
        bar = ToolbarRow(spacing=10)
        title = bar.add(QLabel("内容与评论分析"), ToolbarRow.REQUIRED)
        title.setObjectName("PageTitle")
        summary = muted_label("作品 · 评论 · 热词")
        summary.setWordWrap(False)  # 只整体显示或隐藏：不换行、不压缩
        bar.add(summary, ToolbarRow.LOW)

        self.platform_bar = SegmentBar(
            [("全部平台", "")] + [(label, key) for key, label in PLATFORM_LABELS.items()],
            current="",
        )
        self.platform_bar.selected.connect(lambda _key: self._reload())
        bar.add(self.platform_bar, ToolbarRow.HIGH)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索作品标题 / 关键词…")
        self.search_edit.setFixedWidth(220)
        self.search_edit.returnPressed.connect(self._reload)
        bar.add(self.search_edit, ToolbarRow.NORMAL)

        self.sort_bar = SegmentBar([("按播放排序", "views"), ("按点赞排序", "likes")], current="views")
        self.sort_bar.selected.connect(lambda _key: self._reload())
        bar.add(self.sort_bar, ToolbarRow.NORMAL)
        bar.add_stretch()

        self.analyze_button = QPushButton("重新分析")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(
            lambda: self.context.run_analysis(platform=self.platform_bar.current_key() or None)
        )
        bar.add(self.analyze_button, ToolbarRow.REQUIRED)
        return bar

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        platform = self.platform_bar.current_key() or None
        keyword = self.search_edit.text().strip() or None
        self._videos = list_videos(self.context.db_url, platform=platform, keyword=keyword)
        key = "like_count" if self.sort_bar.current_key() == "likes" else "view_count"
        self._videos.sort(key=lambda row: row.get(key) or 0, reverse=True)
        self.rank_model.set_rows(self._videos)
        self.rank_card.set_subtitle(f"共 {len(self._videos)} 条记录")

    def refresh_status(self) -> None:
        self.refresh()

    # ------------------------------------------------------------------ #
    # 导出：正文为分析摘要（Markdown），随附作品行为 CSV
    # ------------------------------------------------------------------ #
    def _export_payload(self) -> ExportPayload | None:
        metrics = self._metrics or {}
        if not metrics and not self._videos:
            return None
        sentiment = metrics.get("sentiment") or {}
        engine = "大模型打标" if sentiment.get("engine") == "llm" else "离线词典法"
        lines = [
            "## 数据口径",
            f"- 统计日期：{metrics.get('stat_date') or '—'}",
            f"- 数据窗口：近 {metrics.get('window_days') or '—'} 天",
            f"- 数据区间：{(metrics.get('data_span') or {}).get('start', '—')} ~ {(metrics.get('data_span') or {}).get('end', '—')}",
            "",
            "## 作品综合排行（Top 10，完整数据见随附 CSV）",
        ]
        for index, video in enumerate(self._videos[:10], 1):
            views = int(video.get("view_count") or 0)
            likes = int(video.get("like_count") or 0)
            lines.append(
                f"{index}. 《{video.get('title')}》（{video.get('account') or '未知账号'}）"
                f"｜播放 {views:,}｜点赞 {likes:,}"
            )
        lines.extend(
            [
                "",
                "## 评论情感分布",
                f"- 样本 {int(sentiment.get('total') or 0):,} 条"
                f"：正面 {sentiment.get('positive_ratio', 0)}%"
                f"｜中性 {round(100 - float(sentiment.get('positive_ratio') or 0) - float(sentiment.get('negative_ratio') or 0), 2)}%"
                f"｜负面 {sentiment.get('negative_ratio', 0)}%",
                f"- 平均情感分 {sentiment.get('avg_score', 0)}｜分析引擎：{engine}",
            ]
        )
        keywords = metrics.get("keywords") or []
        if keywords:
            lines.extend(
                [
                    "",
                    "## 核心热词",
                    "、".join(f"{item.get('word')}({item.get('count')})" for item in keywords[:15]),
                ]
            )
        return ExportPayload(
            title="内容与评论分析摘要",
            stem=f"内容评论分析_{metrics.get('stat_date') or '最新'}",
            body="\n".join(lines),
            meta={
                "统计日期": str(metrics.get("stat_date") or "—"),
                "数据窗口": f"近 {metrics.get('window_days') or '—'} 天",
                "情感引擎": engine,
            },
            csv_columns=[(column.key, column.label) for column in RANK_COLUMNS],
            csv_rows=list(self._videos),
        )

    # ------------------------------------------------------------------ #
    def render(self, metrics: dict[str, Any]) -> None:
        self._metrics = metrics or {}
        self._reload()
        if not metrics:
            for card in self.kpi_cards:
                card.set_data("—")
            self.sentiment_bar.set_data({})
            self.wordcloud.set_words([])
            return

        span = metrics.get("data_span", {}) or {}
        sentiment = metrics.get("sentiment") or {}
        videos = self._videos
        self.kpi_cards[0].set_data(
            f"{int(span.get('video_count', 0))}",
            "部",
            f"指标快照 {int(span.get('snapshot_rows', 0)):,} 条",
            "cyan",
            f"{span.get('start')} ~ {span.get('end')}",
            [float(r.get("view_count", 0)) for r in videos[:12]][::-1],
        )
        self.kpi_cards[1].set_data(
            f"{int(sentiment.get('total', 0)):,}",
            "条",
            "已完成情感打分",
            "violet",
            f"正面占比 {sentiment.get('positive_ratio', 0)}%",
            [],
        )
        self.kpi_cards[2].set_data(
            f"{float(sentiment.get('positive_ratio', 0)):.1f}",
            "%",
            f"平均情感分 {sentiment.get('avg_score', 0)}",
            "green" if float(sentiment.get("avg_score") or 0) >= 0 else "coral",
            f"负面占比 {sentiment.get('negative_ratio', 0)}%",
            [],
        )

        self.sentiment_bar.set_data(sentiment)
        for key, label in _EMOTION_ROWS:
            count = int(sentiment.get(key) or 0)
            total = int(sentiment.get("total") or 0)
            percent = (count / total * 100) if total else 0.0
            self.emotion_labels[key].setText(f"{label}：{count:,} 条（{percent:.1f}%）")
        self.sentiment_card.set_subtitle(
            f"样本 {int(sentiment.get('total', 0)):,} 条｜引擎："
            + ("大模型打标" if sentiment.get("engine") == "llm" else "离线词典法")
        )

        keywords = metrics.get("keywords") or []
        self.wordcloud.set_words(keywords)
        self.wordcloud_card.set_subtitle(f"共 {len(keywords)} 个高频词")
