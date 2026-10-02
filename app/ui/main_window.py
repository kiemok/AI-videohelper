"""主窗口：顶部状态条 + 侧边导航（自绘徽标）+ 页面栈 + 底部状态栏。

对应设计稿 `stitch_modular_extensible_ui_platform` 的桌面工作台骨架：
- 顶栏：品牌 Logo + 版本 + 运行状态胶囊（本地库 / 模型 / 上次同步）+ 主操作
- 侧栏：工作台模块导航（含徽标）+ 插件与扩展插槽
- 底栏：本地库体积 / 上次分析 / APScheduler / 线程池状态
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app import __app_name__, __version__
from app.ui.context import AppContext
from app.ui.pages import (
    AiPage,
    AnalysisPage,
    ConsultingPage,
    DashboardPage,
    DataPage,
    DramaPage,
    SettingsPage,
    SkillsPage,
)
from app.ui.theme import COLORS, FONT_MONO, NAV_WIDTH, rgba, tone_color

#: 导航配置：icon 使用符号字体，badge 为右侧小徽标
NAV_ITEMS: tuple[dict[str, str], ...] = (
    {"icon": "▦", "label": "数据看板", "badge": "实时", "tone": "cyan"},
    {"icon": "◍", "label": "内容与评论分析", "badge": "情感", "tone": "coral"},
    {"icon": "✦", "label": "AI 决策助手", "badge": "AI", "tone": "violet"},
    {"icon": "☰", "label": "视频创作咨询", "badge": "规划", "tone": "cyan"},
    {"icon": "▶", "label": "AI 短剧工坊", "badge": "规划", "tone": "violet"},
    {"icon": "⛁", "label": "数据仓库与导入", "badge": "仓库", "tone": "cyan"},
    {"icon": "⛭", "label": "技能与工具", "badge": "MCP", "tone": "violet"},
    {"icon": "⚙", "label": "调度与设置", "badge": "", "tone": "muted"},
)

_TONE_LABELS = ("cyan", "violet", "coral", "green", "muted")


class NavDelegate(QStyledItemDelegate):
    """导航项自绘：图标 + 标签 + 右侧徽标 + 选中左指示条。"""

    def sizeHint(self, option, index) -> QSize:  # noqa: ANN001, N802
        return QSize(0, 36)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: ANN001
        data = index.data(Qt.UserRole) or {}
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if selected or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["surface2"] if selected else COLORS["surface1"]))
            painter.drawRoundedRect(QRectF(rect).adjusted(4, 3, -4, -3), 4, 4)
        if selected:
            painter.setBrush(QColor(COLORS["cyan"]))
            painter.drawRoundedRect(
                QRectF(rect.left() + 1, rect.top() + 8, 2, rect.height() - 16), 1, 1
            )

        icon_font = QFont(option.font)
        icon_font.setFamily("Segoe UI Symbol")
        icon_font.setPointSize(11)
        painter.setFont(icon_font)
        painter.setPen(QColor(COLORS["cyan"] if selected else COLORS["text_muted"]))
        painter.drawText(
            QRectF(rect.left() + 12, rect.top(), 20, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            str(data.get("icon", "•")),
        )

        text_font = QFont(option.font)
        text_font.setPointSize(10)
        text_font.setBold(selected)
        painter.setFont(text_font)
        painter.setPen(QColor(COLORS["text"] if selected else COLORS["text_dim"]))
        badge = str(data.get("badge", ""))
        text_width = rect.width() - (86 if badge else 44)
        painter.drawText(
            QRectF(rect.left() + 38, rect.top(), text_width, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            str(data.get("label", "")),
        )

        if badge:
            tone = tone_color(str(data.get("tone", "muted")))
            badge_font = QFont(option.font)
            badge_font.setPointSize(8)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            width = painter.fontMetrics().horizontalAdvance(badge) + 12
            box = QRectF(rect.right() - width - 8, rect.center().y() - 8, width, 16)
            # 透明底 + 细边框（与内容区标签保持一致）
            painter.setPen(QPen(QColor(rgba(tone, 76)), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor(tone))
            painter.drawText(box, Qt.AlignCenter, badge)

        painter.restore()


class LogoWidget(QWidget):
    """品牌标识：双圆环（B站青 / 抖音珊瑚）+ 紫色脉冲弧 + 星形（对应设计稿 Logo）。"""

    def __init__(self, size: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["logo_bg"]))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 8, 8)

        scale = self.width() / 120.0
        ring = QPen(QColor(COLORS["cyan"]), 6 * scale)
        painter.setPen(ring)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(23 * scale, 28 * scale, 44 * scale, 44 * scale))
        painter.setPen(QPen(QColor(COLORS["coral"]), 6 * scale))
        painter.drawEllipse(QRectF(53 * scale, 28 * scale, 44 * scale, 44 * scale))

        arc = QPen(QColor(COLORS["violet"]), 5 * scale)
        arc.setCapStyle(Qt.RoundCap)
        painter.setPen(arc)
        painter.drawArc(
            QRectF(40 * scale, 62 * scale, 40 * scale, 26 * scale), 200 * 16, 140 * 16
        )

        star = QPainterPathHelper.star(QRectF(50 * scale, 24 * scale, 20 * scale, 20 * scale))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS["violet"]))
        painter.drawPath(star)
        painter.end()


class QPainterPathHelper:
    """小工具：生成四角星路径。"""

    @staticmethod
    def star(rect: QRectF):  # noqa: ANN205
        from PySide6.QtGui import QPainterPath

        cx, cy = rect.center().x(), rect.center().y()
        r = rect.width() / 2
        inner = r * 0.42
        path = QPainterPath()
        for index in range(8):
            import math

            angle = math.pi / 4 * index - math.pi / 2
            radius = r if index % 2 == 0 else inner
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        return path


class TitleBar(QFrame):
    """顶部状态条：品牌 + 运行状态胶囊 + 主操作。"""

    def __init__(self, window: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window_ref = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)

        from app.ui.theme import THEME_LABELS
        from app.ui.widgets.cards import Pill, SegmentBar, StatusDot
        from app.ui.widgets.toolbar import ToolbarRow

        bar = ToolbarRow(spacing=10, margins=(14, 0, 14, 0)).fill_height()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(bar)

        bar.add(LogoWidget(28), ToolbarRow.REQUIRED)
        name = QLabel("DataPulse AI")
        name.setObjectName("AppName")
        bar.add(name, ToolbarRow.REQUIRED)
        caption = QLabel(f"{__app_name__}  v{__version__}")
        caption.setObjectName("AppVersion")
        bar.add(caption, ToolbarRow.LOW)

        divider = QLabel("｜")
        divider.setObjectName("MutedText")
        bar.add(divider, ToolbarRow.NORMAL)

        self.db_dot = StatusDot(COLORS["cyan"])
        self.db_pill = Pill("SQLite 本地单文件", "cyan")
        bar.add(self.db_dot, ToolbarRow.HIGH)
        bar.add(self.db_pill, ToolbarRow.HIGH)

        self.model_dot = StatusDot(COLORS["text_muted"])
        self.model_pill = Pill("模型：本地规则引擎")
        bar.add(self.model_dot, ToolbarRow.HIGH)
        bar.add(self.model_pill, ToolbarRow.HIGH)

        self.sync_pill = Pill("分析时间：暂无")
        bar.add(self.sync_pill, ToolbarRow.NORMAL)
        bar.add_stretch()

        self.theme_bar = SegmentBar(
            [(label, key) for key, label in THEME_LABELS],
            current=window.context.settings.theme,
        )
        self.theme_bar.setToolTip("外观主题：浅黑 / 浅白 / 浅蓝（切换立即生效并保存）")
        self.theme_bar.selected.connect(lambda key: window.context.apply_theme(str(key)))
        bar.add(self.theme_bar, ToolbarRow.HIGH)

        self.sync_button = QPushButton("拉取仓库数据")
        self.sync_button.setToolTip("从你自建的数据仓库拉取最新数据并导入（软件内不爬取）")
        self.sync_button.clicked.connect(lambda: window.context.sync_data_repo())
        bar.add(self.sync_button, ToolbarRow.NORMAL)

        self.chat_button = QPushButton("AI 咨询")
        self.chat_button.setCheckable(True)
        self.chat_button.setChecked(True)
        self.chat_button.setToolTip("在右侧常驻显示 / 隐藏 AI 咨询面板（任意页面都能提问）")
        self.chat_button.toggled.connect(window.toggle_chat_panel)
        bar.add(self.chat_button, ToolbarRow.NORMAL)

        self.analyze_button = QPushButton("一键全量分析")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(lambda: window.context.run_analysis())
        bar.add(self.analyze_button, ToolbarRow.REQUIRED)

    def refresh(self) -> None:
        context = self.window_ref.context
        db_kind = "SQLite 本地" if context.db_url.startswith("sqlite") else "MySQL 已连接"
        self.db_pill.update_pill(f"{db_kind} · 就绪", "cyan")
        model_text, tone = context.model_status()
        self.model_pill.update_pill(model_text, tone)
        self.model_dot.set_color(
            COLORS["violet"] if tone == "violet" else COLORS["text_muted"]
        )
        self.sync_pill.update_pill(context.last_sync_text())
        self.theme_bar.set_current(context.settings.theme or "dark")


class MainWindow(QMainWindow):
    #: 窗口最小高度：页面内容可纵向滚动，保证基本可用即可
    MIN_HEIGHT = 620

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.setWindowTitle(f"{__app_name__}  v{__version__}")
        self._fit_to_screen()

        self._build_pages()
        self._build_layout()
        self._build_menu()

        context.status_message.connect(self._show_status)
        context.data_changed.connect(self._on_data_changed)
        context.settings_changed.connect(self._on_settings_changed)
        context.metrics_updated.connect(self._on_metrics_updated)

        self._on_metrics_updated(context.load_latest_metrics())
        self.refresh_status()
        self._sync_minimum_width()
        if not context.metrics:
            self._show_status("欢迎使用：请先点击顶部「立即同步数据」，再执行分析。")

    # ------------------------------------------------------------------ #
    def _fit_to_screen(self) -> None:
        """按屏幕可用区域自适应初始窗口大小。

        若窗口默认尺寸超过屏幕，系统会把窗口压小，进而把页面内容挤变形；
        这里主动收敛到屏幕内，并留出合理的可用区边距。
        """
        width, height = 1480, 940
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = max(900, min(width, available.width() - 40))
            height = max(620, min(height, available.height() - 60))
        self.resize(width, height)
        # 最小尺寸在 _build_layout 之后由 _sync_minimum_width() 按实际布局需求设置

    def _build_pages(self) -> None:
        self.dashboard_page = DashboardPage(self.context)
        self.analysis_page = AnalysisPage(self.context)
        self.ai_page = AiPage(self.context)
        self.consulting_page = ConsultingPage(self.context)
        self.drama_page = DramaPage(self.context)
        self.data_page = DataPage(self.context)
        self.skills_page = SkillsPage(self.context)
        self.settings_page = SettingsPage(self.context)
        self.pages = (
            self.dashboard_page,
            self.analysis_page,
            self.ai_page,
            self.consulting_page,
            self.drama_page,
            self.data_page,
            self.skills_page,
            self.settings_page,
        )

    def _build_layout(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)

        # 中间工作区 + 右侧常驻 AI 咨询面板（任意页面都能直接提问）
        from app.ui.widgets.ai_chat import AiChatPanel

        self.workspace = QSplitter(Qt.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.setHandleWidth(6)  # 加宽拖动手柄，便于抓取与识别方向
        self.workspace.addWidget(self.stack)
        # 放开页面栈的最小宽度：否则它会把 AI 面板顶在最小宽度上，
        # 表现为「往右拖不动、往左拖没反应」——页面内容超出时用滚动条查看即可。
        self.stack.setMinimumWidth(520)
        self.chat_panel = AiChatPanel(self.context, compact=True)
        self.chat_panel.setMinimumWidth(300)  # 留出双向拖动空间
        self.workspace.addWidget(self.chat_panel)
        self.workspace.setStretchFactor(0, 1)
        self.workspace.setStretchFactor(1, 0)
        self._splitter_ready = False
        layout.addWidget(self.workspace, 1)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)

        self.nav.setCurrentRow(0)
        self._build_status_bar()

    # ------------------------------------------------------------------ #
    def _apply_default_splitter(self) -> None:
        """设定「页面区 : AI 咨询面板」的初始宽度（默认面板 380px）。"""
        if self.workspace.count() < 2:
            return
        total = self.workspace.width() or (self.width() - NAV_WIDTH - 32)
        panel_width = 380 if total >= 1000 else 300
        panel_width = max(300, min(panel_width, max(300, total - 520)))
        self.workspace.setSizes([max(520, total - panel_width), panel_width])

    def _minimum_window_width(self) -> int:
        """窗口最小宽度 = 侧栏 + 页面区最小宽 +（显示时）AI 面板最小宽 + 拖动手柄。

        因此当右侧 AI 咨询面板已经被拖到最小时，窗口就无法继续缩小，
        页面内容与顶部工具栏不会被压缩变形。
        """
        width = NAV_WIDTH + self.stack.minimumWidth()
        if not self.chat_panel.isHidden():
            width += self.chat_panel.minimumWidth() + self.workspace.handleWidth()
        return width

    def _sync_minimum_width(self) -> None:
        """应用最小窗口尺寸（屏幕过小时不超出屏幕可用区，避免窗口大于屏幕）。"""
        minimum = self._minimum_window_width()
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            minimum = min(minimum, max(720, available.width() - 40))
        self.setMinimumSize(minimum, self.MIN_HEIGHT)

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt 命名
        super().resizeEvent(event)
        # 首次拿到真实宽度后再分配：布局未完成时 setSizes 会被忽略
        if not self._splitter_ready and self.workspace.width() > 0:
            self._splitter_ready = True
            QTimer.singleShot(0, self._apply_default_splitter)

    def toggle_chat_panel(self, visible: bool) -> None:
        """显示 / 隐藏右侧常驻 AI 咨询面板（顶栏「AI 咨询」开关）。"""
        self.chat_panel.setVisible(visible)
        if visible:
            sizes = self.workspace.sizes()
            if sizes[1] < 340:
                self.workspace.setSizes([max(420, sizes[0] + sizes[1] - 380), 380])
        # 面板显隐会改变所需最小宽度：收起时允许窗口更窄，打开时收紧下限
        self._sync_minimum_width()
        self.context.status_message.emit(
            "AI 咨询面板已" + ("打开，可在当前页面直接提问" if visible else "收起")
        )

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(NAV_WIDTH)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)

        section = QLabel("工作台模块导航")
        section.setObjectName("NavSection")
        layout.addWidget(section)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setItemDelegate(NavDelegate(self.nav))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setFrameShape(QListWidget.NoFrame)
        for item_data in NAV_ITEMS:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, dict(item_data))
            item.setSizeHint(QSize(0, 36))
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav, 1)

        plugin = QFrame()
        plugin.setObjectName("ModuleCard")
        plugin_layout = QVBoxLayout(plugin)
        plugin_layout.setContentsMargins(10, 10, 10, 10)
        plugin_layout.setSpacing(6)
        title_row = QHBoxLayout()
        title = QLabel("插件与扩展插槽")
        title.setObjectName("CardSubtitle")
        version = QLabel("v1.2")
        version.setObjectName("CardSubtitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(version)
        plugin_layout.addLayout(title_row)
        hint = QLabel("+ 添加新数据源 / 模块扩展")
        hint.setObjectName("HintText")
        plugin_layout.addWidget(hint)
        reserved = QLabel("小红书 / 快手插件预留")
        reserved.setObjectName("MutedText")
        plugin_layout.addWidget(reserved)
        layout.addWidget(plugin)
        return side

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self.status_label = QLabel("就绪")
        bar.addWidget(self.status_label, 1)

        self.db_status = QLabel("")
        self.engine_status = QLabel("")
        self.pool_status = QLabel("QThreadPool: 就绪")
        for widget in (self.db_status, self.engine_status, self.pool_status):
            widget.setObjectName("MutedText")
            bar.addPermanentWidget(widget)

    def _build_menu(self) -> None:
        data_menu = self.menuBar().addMenu("数据(&D)")
        for label, handler in (
            ("拉取 / 更新数据仓库", self.context.sync_data_repo),
            ("仅导入本地仓库目录", self.context.import_repo_local),
            ("生成数据模板", self.context.write_repo_templates),
            ("载入演示数据（离线）", lambda: self.context.sync_sample_data()),
            ("归档指标快照", self.context.archive_data),
            ("重启本地引擎", self.data_page._restart_engine),
            ("清空全部业务数据", self.data_page.confirm_clear),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            data_menu.addAction(action)

        run_menu = self.menuBar().addMenu("运行(&R)")
        for label, handler in (
            ("执行分析（全平台）", lambda: self.context.run_analysis()),
            ("执行分析（B站）", lambda: self.context.run_analysis(platform="bilibili")),
            ("执行分析（抖音）", lambda: self.context.run_analysis(platform="douyin")),
        ):
            action = QAction(label, self)
            action.triggered.connect(handler)
            run_menu.addAction(action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        about = QAction("关于", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    # ------------------------------------------------------------------ #
    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            page = self.stack.widget(row)
            if hasattr(page, "refresh_status"):
                page.refresh_status()
            elif hasattr(page, "refresh"):
                page.refresh()

    def refresh_status(self) -> None:
        """刷新顶栏胶囊与底部状态栏。"""
        self.title_bar.refresh()
        self.db_status.setText(self.context.db_size_text())
        self.engine_status.setText(self.context.engine_status())
        if hasattr(self.ai_page, "refresh_status"):
            self.ai_page.refresh_status()

    def _show_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.refresh_status()

    def _on_data_changed(self) -> None:
        self.data_page.refresh()
        self.consulting_page.refresh()
        self.drama_page.refresh()
        self.refresh_status()

    def _on_settings_changed(self) -> None:
        self.data_page.refresh()
        self.settings_page.refresh_schedule_status()
        self.refresh_status()

    def _on_metrics_updated(self, metrics: dict[str, Any]) -> None:
        self.dashboard_page.render(metrics)
        self.analysis_page.render(metrics)
        self.ai_page.refresh_status()
        self.consulting_page.refresh_status()
        self.refresh_status()

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于",
            f"{__app_name__}\n版本 v{__version__}\n\n"
            "PySide6 桌面端 + SQLAlchemy 统一数据模型 + 本地分析 + 大模型解读。\n"
            f"界面设计：Deep Telemetry & Intelligence Workspace\n"
            f"当前数据库：{self.context.db_url.split('///')[-1]}\n"
            f"字体：{FONT_MONO.split(',')[0]}（数字）/ 系统中文界面字体",
        )
