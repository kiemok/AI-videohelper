"""视频创作咨询模块（扩展方向一）。

定位：把「数据分析结论」进一步转化为「可执行的创作咨询」——
围绕账号定位、脚本结构、标题封面、增长策略、商业化等主题给出建议，
既可用大模型生成，也可在无 Key 时用本地规则给出结构化方案。
"""

from app.consulting.prompts import CATEGORIES, CATEGORY_LABELS, category_label
from app.consulting.repository import (
    add_record,
    create_session,
    delete_session,
    list_records,
    list_sessions,
)
from app.consulting.service import ConsultService

__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "category_label",
    "ConsultService",
    "add_record",
    "create_session",
    "delete_session",
    "list_records",
    "list_sessions",
]
