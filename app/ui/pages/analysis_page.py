"""内容与评论分析页（对齐设计稿 `_3 内容与评论分析`）。

- 顶部：平台筛选 + 关键词搜索 + 排序方式
- KPI：双端监控作品数 / 评论语料库容量 / 全域情感极性均值
- 作品综合排行（左） ＋ 评论区情感极性与情绪分布（右上） ＋ 核心热词（右下）
- 底部：作品级异常拐点与 AI 归因
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
from app.ui.widgets.cards import (
    KpiCard,
    ModuleCard,
    SegmentBar,
    build_kpi_row,
    muted_label,
)
from app.ui.widgets.charts import SentimentBar, TopicCloud
from app.ui.widgets.tables import ANOMALY_COLUMNS, Column, DictTableModel, configure_table

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
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)
        root.addWidget(self._build_toolbar())

        self.kpi_cards = [
            KpiCard("双端监控作品总数", "部", accent=COLORS["cyan"]),
            KpiCard("评论语料库容量", "条", accent=COLORS["violet"]),
            KpiCard("全域评论情感极性均值", "%", accent=COLORS["green"]),
        ]
        root.addWidget(build_kpi_row(self.kpi_cards, columns=3))

        middle = QSplitter(Qt.Horizontal)
        self.rank_card = ModuleCard("双平台作品综合排行", "融合数据模型统一视图")
        self.rank_model = DictTableModel(RANK_COLUMNS)
        self.rank_table = QTableView()
        self.rank_table.setModel(self.rank_model)
        configure_table(self.rank_table, row_height=32, stretch_column=1, platform_column=0)
        self.rank_card.add_widget(self.rank_table, 1)
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
        middle.setSizes([880, 460])
        root.addWidget(middle, 3)

        self.anomaly_card = ModuleCard("作品级异常拐点与 AI 归因")
        self.anomaly_model = DictTableModel(ANOMALY_COLUMNS)
        self.anomaly_table = QTableView()
        self.anomaly_table.setModel(self.anomaly_model)
        configure_table(self.anomaly_table, row_height=30, stretch_column=2, platform_column=1)
        self.anomaly_card.add_widget(self.anomaly_table, 1)
        root.addWidget(self.anomaly_card, 2)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("内容与评论分析")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        layout.addWidget(muted_label("作品多维表现 · 评论情感极性 · 高频词云"))

        self.platform_bar = SegmentBar(
            [("全部平台", "")] + [(label, key) for key, label in PLATFORM_LABELS.items()],
            current="",
        )
        self.platform_bar.selected.connect(lambda _key: self._reload())
        layout.addWidget(self.platform_bar)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索作品标题 / 关键词…")
        self.search_edit.setFixedWidth(220)
        self.search_edit.returnPressed.connect(self._reload)
        layout.addWidget(self.search_edit)

        self.sort_bar = SegmentBar([("按播放排序", "views"), ("按点赞排序", "likes")], current="views")
        self.sort_bar.selected.connect(lambda _key: self._reload())
        layout.addWidget(self.sort_bar)
        layout.addStretch(1)

        self.analyze_button = QPushButton("重新分析")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(
            lambda: self.context.run_analysis(platform=self.platform_bar.current_key() or None)
        )
        layout.addWidget(self.analyze_button)
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
    def render(self, metrics: dict[str, Any]) -> None:
        self._metrics = metrics or {}
        self._reload()
        if not metrics:
            for card in self.kpi_cards:
                card.set_data("—")
            self.sentiment_bar.set_data({})
            self.wordcloud.set_words([])
            self.anomaly_model.set_rows([])
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
        self.sentiment_card.set_subtitle(f"样本 {int(sentiment.get('total', 0)):,} 条")

        keywords = metrics.get("keywords") or []
        self.wordcloud.set_words(keywords)
        self.wordcloud_card.set_subtitle(f"共 {len(keywords)} 个高频词")

        self.anomaly_model.set_rows(metrics.get("anomalies") or [])
        self.anomaly_card.set_subtitle(f"共 {len(metrics.get('anomalies') or [])} 条拐点")
