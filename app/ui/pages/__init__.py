"""功能页面：看板 / 分析 / AI 决策 / 创作咨询 / AI 短剧 / 数据仓库 / 技能与工具 / 设置。"""

from app.ui.pages.ai_page import AiPage
from app.ui.pages.analysis_page import AnalysisPage
from app.ui.pages.consulting_page import ConsultingPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.data_page import DataPage
from app.ui.pages.drama_page import DramaPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.skills_page import SkillsPage

__all__ = [
    "AiPage",
    "AnalysisPage",
    "ConsultingPage",
    "DashboardPage",
    "DataPage",
    "DramaPage",
    "SettingsPage",
    "SkillsPage",
]
