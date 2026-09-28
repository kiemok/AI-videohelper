"""大模型应用层：调用客户端、提示词模板、解读与建议服务。"""

from app.ai.client import LLMClient, LLMError, LLMResult
from app.ai.insights import REPORT_TYPES, InsightService
from app.ai.prompts import metrics_to_context

__all__ = ["LLMClient", "LLMError", "LLMResult", "InsightService", "REPORT_TYPES", "metrics_to_context"]
