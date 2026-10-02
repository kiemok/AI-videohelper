"""外观主题系统：Deep Telemetry & Intelligence Workspace（支持多主题切换）。

三套内置主题（设计令牌完全参数化，切换即全局生效）：

- ``dark`` （**浅黑**，默认）：深灰黑画布 + 青/紫/珊瑚信号色
- ``light``（**浅白**）：白底卡片 + 深色文字 + 同族信号色
- ``blue`` （**浅蓝**）：浅蓝画布 + 白底卡片 + 深色文字

实现要点：

1. **令牌可变**：``COLORS`` 等字典在 ``apply_theme()`` 中**原地更新**，
   因此所有 ``from app.ui.theme import COLORS`` 的模块都能拿到新值
   （前提是运行时取色，不要在模块级缓存颜色字符串）。
2. **背景融合**：全局 ``QWidget`` 背景设为 **transparent**，只给窗口、侧栏、顶栏、
   卡片、输入框、表格等**需要底色的容器**显式设色。这样标签/容器不会再给文字
   铺一块与卡片不融合的深色方块。
3. **样式重建**：``apply_theme_to_app()`` 会重建 QSS 并重绘全部控件；
   图表/自绘组件在页面 refresh 时按新令牌重新着色。
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# 三套主题的设计令牌
# --------------------------------------------------------------------------- #
THEMES: dict[str, dict[str, str]] = {
    # 浅黑（默认）：深灰黑画布，适合长时间盯屏
    "dark": {
        "canvas": "#101319",
        "surface1": "#171B24",
        "surface2": "#1E232E",
        "surface3": "#262C39",
        "border": "#2C3341",
        "border_subtle": "#212734",
        "border_hover": "#3A4356",
        "text": "#F1F5F9",
        "text_dim": "#94A3B8",
        "text_muted": "#64748B",
        "on_accent": "#0B0F16",
        "cyan": "#00AEEC",
        "cyan_hover": "#33BEF0",
        "cyan_active": "#0098CF",
        "violet": "#8B5CF6",
        "coral": "#FE2C55",
        "green": "#22C55E",
        "amber": "#F59E0B",
        "bilibili": "#00AEEC",
        "douyin": "#FE2C55",
        "positive": "#22C55E",
        "neutral": "#64748B",
        "negative": "#FE2C55",
        "logo_bg": "#141824",
    },
    # 浅白：白底卡片 + 深色文字
    "light": {
        "canvas": "#F4F6FA",
        "surface1": "#FFFFFF",
        "surface2": "#EDF1F8",
        "surface3": "#E1E7F1",
        "border": "#D3DAE6",
        "border_subtle": "#E7EBF3",
        "border_hover": "#B7C1D1",
        "text": "#1A2231",
        "text_dim": "#566073",
        "text_muted": "#8A93A5",
        "on_accent": "#FFFFFF",
        "cyan": "#0B84C7",
        "cyan_hover": "#2699D6",
        "cyan_active": "#0A6FA8",
        "violet": "#6D3BE2",
        "coral": "#DC2C4E",
        "green": "#12A150",
        "amber": "#C77700",
        "bilibili": "#0B84C7",
        "douyin": "#DC2C4E",
        "positive": "#12A150",
        "neutral": "#8A93A5",
        "negative": "#DC2C4E",
        "logo_bg": "#E9EEF7",
    },
    # 浅蓝：浅蓝画布 + 白底卡片
    "blue": {
        "canvas": "#E9F2FB",
        "surface1": "#F8FBFF",
        "surface2": "#DCEAF8",
        "surface3": "#C9DDF2",
        "border": "#B6D1EA",
        "border_subtle": "#D5E6F6",
        "border_hover": "#8FB6D8",
        "text": "#11253A",
        "text_dim": "#44607C",
        "text_muted": "#7A93AA",
        "on_accent": "#FFFFFF",
        "cyan": "#0A7CC0",
        "cyan_hover": "#2A93D0",
        "cyan_active": "#08699F",
        "violet": "#6741D9",
        "coral": "#D62F52",
        "green": "#108A4B",
        "amber": "#B8730A",
        "bilibili": "#0A7CC0",
        "douyin": "#D62F52",
        "positive": "#108A4B",
        "neutral": "#7A93AA",
        "negative": "#D62F52",
        "logo_bg": "#DCEAF8",
    },
}

THEME_LABELS: tuple[tuple[str, str], ...] = (
    ("dark", "浅黑"),
    ("light", "浅白"),
    ("blue", "浅蓝"),
)

#: 浅色系主题（用于放大半透明填充，保证在亮底上依然可辨）
LIGHT_THEMES: frozenset[str] = frozenset({"light", "blue"})

# --------------------------------------------------------------------------- #
# 当前令牌（原地更新，供全局运行时读取）
# --------------------------------------------------------------------------- #
COLORS: dict[str, str] = {}
PLATFORM_COLORS: dict[str, str] = {}
SENTIMENT_COLORS: dict[str, str] = {}
TONE_COLORS: dict[str, str] = {}

_current_theme = "dark"

FONT_UI = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'

RADIUS_CARD = 8
RADIUS_CONTROL = 4
ROW_HEIGHT = 30
TOOLBAR_HEIGHT = 28
TITLEBAR_HEIGHT = 48
NAV_WIDTH = 232
STATUSBAR_HEIGHT = 30


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def rgba(hex_color: str, alpha: int) -> str:
    """``#RRGGBB`` + 0~255 alpha → QSS 可用的 ``rgba(...)``。"""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _alpha(base: int) -> int:
    """浅色主题下把半透明填充适度加强，避免在亮底上看不见。"""
    return min(255, int(base * 1.8)) if _current_theme in LIGHT_THEMES else base


def tone_color(tone: str) -> str:
    """语义色调 → 颜色（运行时取值，支持主题切换）。"""
    return TONE_COLORS.get(tone, COLORS.get("text_dim", "#94A3B8"))


def current_theme() -> str:
    return _current_theme


def theme_label(name: str) -> str:
    return dict(THEME_LABELS).get(name, name)


# --------------------------------------------------------------------------- #
# 应用主题
# --------------------------------------------------------------------------- #
def apply_theme(name: str) -> str:
    """切换主题令牌（原地更新字典，并重建 QSS）。返回实际生效的主题名。"""
    global _current_theme, STYLESHEET

    theme_name = name if name in THEMES else "dark"
    tokens = THEMES[theme_name]
    _current_theme = theme_name

    COLORS.clear()
    COLORS.update(tokens)
    # 兼容旧键名
    COLORS.update(
        {
            "bg": COLORS["canvas"],
            "panel": COLORS["surface1"],
            "panel_alt": COLORS["surface2"],
            "primary": COLORS["cyan"],
            "warn": COLORS["amber"],
        }
    )
    PLATFORM_COLORS.clear()
    PLATFORM_COLORS.update({"bilibili": COLORS["bilibili"], "douyin": COLORS["douyin"]})
    SENTIMENT_COLORS.clear()
    SENTIMENT_COLORS.update(
        {
            "positive": COLORS["positive"],
            "neutral": COLORS["neutral"],
            "negative": COLORS["negative"],
        }
    )
    TONE_COLORS.clear()
    TONE_COLORS.update(
        {
            "cyan": COLORS["cyan"],
            "violet": COLORS["violet"],
            "coral": COLORS["coral"],
            "green": COLORS["green"],
            "amber": COLORS["amber"],
            "muted": COLORS["text_dim"],
        }
    )
    STYLESHEET = build_stylesheet()
    return _current_theme


def current_stylesheet() -> str:
    """当前主题的全局 QSS（``apply_theme`` 时已按新令牌重建）。"""
    return STYLESHEET


def apply_theme_to_app(name: str) -> str:
    """切换主题并让正在运行的界面立即生效（重建 QSS + 重绘所有控件）。"""
    applied = apply_theme(name)
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # 无 Qt 环境（如纯后端自检）
        return applied
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(STYLESHEET)
        for widget in app.allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
    return applied


# --------------------------------------------------------------------------- #
# 样式表
# --------------------------------------------------------------------------- #
def build_stylesheet() -> str:
    """按当前令牌生成全局 QSS。"""
    c = COLORS
    return f"""
/* 基础：控件默认透明背景 —— 标签/容器不再给文字铺一层与卡片不融合的深色块 */
QWidget {{
    background-color: transparent;
    color: {c["text"]};
    font-family: {FONT_UI};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {c["canvas"]}; }}
QMenuBar {{ background-color: {c["canvas"]}; color: {c["text_dim"]}; }}
QToolTip {{
    background-color: {c["surface2"]};
    color: {c["text"]};
    border: 1px solid {c["cyan"]};
    padding: 4px 8px;
}}

/* ---------- 顶部标题栏 ---------- */
QFrame#TitleBar {{
    background-color: {c["canvas"]};
    border-bottom: 1px solid {c["border"]};
}}
QLabel#AppName {{ font-size: 15px; font-weight: 600; letter-spacing: -0.2px; }}
QLabel#AppVersion {{ color: {c["text_muted"]}; font-size: 11px; font-family: {FONT_MONO}; }}
QLabel#Pill {{
    background-color: transparent;
    border: 1px solid {c["border"]};
    border-radius: 12px;
    padding: 3px 10px;
    color: {c["text_dim"]};
    font-size: 11px;
    font-family: {FONT_MONO};
}}
QLabel#Pill[tone="cyan"] {{ color: {c["cyan"]}; border-color: {rgba(c["cyan"], _alpha(90))}; }}
QLabel#Pill[tone="violet"] {{ color: {c["violet"]}; border-color: {rgba(c["violet"], _alpha(90))}; }}
QLabel#Pill[tone="coral"] {{ color: {c["coral"]}; border-color: {rgba(c["coral"], _alpha(90))}; }}

/* ---------- 侧边导航 ---------- */
QFrame#SideBar {{
    background-color: {c["canvas"]};
    border-right: 1px solid {c["border"]};
}}
QLabel#NavSection {{
    color: {c["text_muted"]};
    font-size: 10px;
    font-family: {FONT_MONO};
    letter-spacing: 1px;
    padding: 8px 10px 2px 10px;
}}
QListWidget#NavList {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QListWidget#NavList::item {{
    color: {c["text_dim"]};
    padding: 9px 10px;
    margin: 1px 0;
    border-left: 2px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
}}
QListWidget#NavList::item:hover:!selected {{ background-color: {c["surface1"]}; color: {c["text"]}; }}
QListWidget#NavList::item:selected {{
    background-color: {c["surface2"]};
    border-left: 2px solid {c["cyan"]};
    color: {c["text"]};
    font-weight: 600;
}}

/* ---------- 卡片 ---------- */
QFrame#ModuleCard {{
    background-color: {c["surface1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ModuleCard:hover {{ border-color: {c["border_hover"]}; }}
QFrame#CardHeader {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {c["border_subtle"]};
    min-height: 34px;
    max-height: 34px;
}}
QLabel#CardTitle {{ font-size: 13px; font-weight: 600; color: {c["text"]}; }}
QLabel#CardSubtitle {{ font-size: 11px; color: {c["text_muted"]}; font-family: {FONT_MONO}; }}

/* ---------- KPI ---------- */
QLabel#KpiLabel {{
    color: {c["text_dim"]};
    font-size: 10px;
    font-family: {FONT_MONO};
    letter-spacing: 0.6px;
}}
QLabel#KpiValue {{ font-size: 24px; font-weight: 600; font-family: {FONT_MONO}; }}
QLabel#KpiUnit {{ font-size: 12px; color: {c["text_dim"]}; }}
QLabel#KpiDelta {{ font-size: 11px; font-family: {FONT_MONO}; }}
QLabel#KpiHint {{ font-size: 11px; color: {c["text_muted"]}; }}

/* ---------- 徽标 / 状态点（透明底，仅保留细边框与文字色） ---------- */
QLabel#Badge {{
    font-family: {FONT_MONO};
    font-size: 10px;
    letter-spacing: 0.4px;
    padding: 2px 6px;
    border-radius: {RADIUS_CONTROL}px;
    background-color: transparent;
    color: {c["text_dim"]};
    border: 1px solid {c["border"]};
}}
QLabel#Badge[tone="cyan"] {{
    background-color: transparent;
    color: {c["cyan"]};
    border: 1px solid {rgba(c["cyan"], _alpha(76))};
}}
QLabel#Badge[tone="violet"] {{
    background-color: transparent;
    color: {c["violet"]};
    border: 1px solid {rgba(c["violet"], _alpha(76))};
}}
QLabel#Badge[tone="coral"] {{
    background-color: transparent;
    color: {c["coral"]};
    border: 1px solid {rgba(c["coral"], _alpha(76))};
}}
QLabel#Badge[tone="green"] {{
    background-color: transparent;
    color: {c["green"]};
    border: 1px solid {rgba(c["green"], _alpha(76))};
}}
QLabel#StatusDot {{
    border-radius: 3px;
    min-width: 6px; max-width: 6px;
    min-height: 6px; max-height: 6px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background-color: {c["surface2"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CONTROL}px;
    padding: 5px 12px;
    color: {c["text"]};
}}
QPushButton:hover {{ background-color: {c["surface3"]}; border-color: {c["border_hover"]}; }}
QPushButton:disabled {{ color: {c["text_muted"]}; border-color: {c["border_subtle"]}; }}
QPushButton#PrimaryButton {{
    background-color: {c["cyan"]};
    border: 1px solid {c["cyan"]};
    color: {c["on_accent"]};
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{ background-color: {c["cyan_hover"]}; border-color: {c["cyan_hover"]}; }}
QPushButton#PrimaryButton:disabled {{
    background-color: {rgba(c["cyan"], _alpha(70))};
    color: {c["text_muted"]};
}}
QPushButton#AiButton {{
    background-color: {rgba(c["violet"], _alpha(30))};
    border: 1px solid {c["violet"]};
    color: {c["violet"]};
    font-weight: 600;
}}
QPushButton#AiButton:hover {{ background-color: {rgba(c["violet"], _alpha(60))}; }}
QPushButton#DangerButton {{
    background-color: {rgba(c["coral"], _alpha(30))};
    border: 1px solid {c["coral"]};
    color: {c["coral"]};
}}
QPushButton#DangerButton:hover {{ background-color: {rgba(c["coral"], _alpha(60))}; }}
QPushButton#Segment {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
    color: {c["text_dim"]};
    padding: 3px 10px;
    font-size: 12px;
}}
QPushButton#Segment:hover {{ color: {c["text"]}; }}
QPushButton#Segment:checked {{
    background-color: {c["surface2"]};
    border: 1px solid {c["border"]};
    color: {c["text"]};
    font-weight: 600;
}}
QFrame#SegmentBar {{
    background-color: {c["canvas"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
    background-color: {c["surface1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CONTROL}px;
    padding: 5px 9px;
    color: {c["text"]};
    selection-background-color: {c["cyan"]};
    selection-color: {c["on_accent"]};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c["cyan"]};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {c["surface1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CONTROL}px;
    selection-background-color: {rgba(c["cyan"], _alpha(46))};
    color: {c["text"]};
    outline: none;
}}
QTextEdit, QPlainTextEdit, QTextBrowser {{
    background-color: {c["surface1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CARD}px;
    padding: 8px;
    color: {c["text"]};
    selection-background-color: {c["cyan"]};
    selection-color: {c["on_accent"]};
}}
QCheckBox, QRadioButton {{ spacing: 6px; color: {c["text_dim"]}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {c["border"]};
    background-color: {c["canvas"]};
    border-radius: 3px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {c["cyan"]};
    border-color: {c["cyan"]};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c["cyan"]}; }}

/* ---------- 表格 ---------- */
QTableView, QTableWidget {{
    background-color: {c["surface1"]};
    alternate-background-color: {c["surface1"]};
    gridline-color: transparent;
    border: none;
    color: {c["text"]};
    selection-background-color: {rgba(c["cyan"], _alpha(20))};
    selection-color: {c["text"]};
    font-family: {FONT_MONO};
    font-size: 12px;
}}
QTableView::item, QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {c["border_subtle"]}; }}
QTableView::item:hover, QTableWidget::item:hover {{ background-color: {rgba(c["cyan"], _alpha(14))}; }}
QHeaderView {{ background-color: {c["surface1"]}; }}
QHeaderView::section {{
    background-color: {c["surface1"]};
    color: {c["text_muted"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    padding: 6px 8px;
    font-family: {FONT_MONO};
    font-size: 10px;
    letter-spacing: 0.5px;
}}
QTableCornerButton::section {{ background-color: {c["surface1"]}; border: none; }}

/* ---------- 列表 ---------- */
QListWidget#LogList, QListWidget#PlainList {{
    background-color: {c["surface1"]};
    border: none;
    outline: none;
}}
QListWidget#LogList::item, QListWidget#PlainList::item {{
    color: {c["text"]};
    padding: 7px 8px;
    border-bottom: 1px solid {c["border_subtle"]};
}}
QListWidget#LogList::item:hover, QListWidget#PlainList::item:hover {{
    background-color: {rgba(c["cyan"], _alpha(14))};
}}
QListWidget#LogList::item:selected, QListWidget#PlainList::item:selected {{
    background-color: {rgba(c["cyan"], _alpha(20))};
    color: {c["text"]};
}}

/* ---------- 分组框 / 标签页 / 分割器 ---------- */
QGroupBox {{
    background-color: {c["surface1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CARD}px;
    margin-top: 16px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {c["text_dim"]};
    font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CARD}px;
    background-color: {c["surface1"]};
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {c["text_dim"]};
    padding: 6px 14px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: {RADIUS_CONTROL}px;
    border-top-right-radius: {RADIUS_CONTROL}px;
    font-size: 12px;
}}
QTabBar::tab:hover {{ color: {c["text"]}; }}
QTabBar::tab:selected {{
    background-color: {c["surface2"]};
    border: 1px solid {c["border"]};
    color: {c["text"]};
    font-weight: 600;
}}
QSplitter::handle {{ background-color: {c["border"]}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}
QSplitter::handle:hover {{ background-color: {rgba(c["cyan"], _alpha(140))}; }}
QSplitter::handle:pressed {{ background-color: {c["cyan"]}; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c["surface3"]}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {c["border_hover"]}; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; }}
QScrollBar::handle:horizontal {{ background: {c["surface3"]}; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background-color: transparent; }}

/* ---------- 菜单 ---------- */
QMenuBar::item {{ padding: 5px 10px; background: transparent; color: {c["text_dim"]}; }}
QMenuBar::item:selected {{ background-color: {c["surface2"]}; color: {c["text"]}; }}
QMenu {{
    background-color: {c["surface1"]};
    border: 1px solid {rgba(c["cyan"], _alpha(100))};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: {RADIUS_CONTROL}px; color: {c["text"]}; }}
QMenu::item:selected {{ background-color: {rgba(c["cyan"], _alpha(46))}; }}

/* ---------- 文本辅助 ---------- */
QLabel#PageTitle {{ font-size: 17px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel#PageCaption {{ color: {c["text_muted"]}; font-size: 11px; font-family: {FONT_MONO}; }}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#HintText {{ color: {c["text_dim"]}; font-size: 12px; }}
QLabel#MonoText {{ font-family: {FONT_MONO}; font-size: 12px; color: {c["text_dim"]}; }}
QLabel#MutedText {{ color: {c["text_muted"]}; font-size: 11px; }}

/* ---------- 进度条 / 状态栏 ---------- */
QProgressBar {{
    background-color: {c["surface3"]};
    border: none;
    border-radius: 3px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {c["cyan"]}; border-radius: 3px; }}
QStatusBar {{
    background-color: {c["canvas"]};
    border-top: 1px solid {c["border"]};
    color: {c["text_muted"]};
    font-family: {FONT_MONO};
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
"""


def badge_qss(tone: str) -> str:
    """行内徽标样式（运行时生成；透明底 + 细边框，支持主题切换）。"""
    color = tone_color(tone)
    return (
        f"background-color: transparent; color: {color};"
        f" border: 1px solid {rgba(color, _alpha(76))}; border-radius: 4px;"
        f" padding: 1px 6px; font-family: {FONT_MONO}; font-size: 10px;"
    )


# 初始化默认主题（浅黑）
apply_theme("dark")
STYLESHEET: str = build_stylesheet()
