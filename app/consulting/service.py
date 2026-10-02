"""视频创作咨询服务：把数据结论转化为可执行的创作咨询建议。

与 ``app.ai.insights`` 共用同一套大模型客户端与「无 Key 本地回退」策略，
但产出落到 ``consult_session`` / ``consult_record`` 两张表，便于按主题回溯咨询历史。
"""

from __future__ import annotations

from typing import Any

from app.ai.client import LLMClient, LLMError
from app.config import AppSettings
from app.consulting import prompts as P
from app.consulting.repository import add_record, create_session, list_records, list_sessions
from app.consulting.retrieval import format_material, retrieve_material
from app.core.logging_setup import get_logger
from app.db.repository import latest_analysis

logger = get_logger(__name__)


class ConsultService:
    def __init__(self, settings: AppSettings, db_url: str) -> None:
        self.settings = settings
        self.db_url = db_url

    # ------------------------------------------------------------------ #
    @property
    def client(self) -> LLMClient:
        return LLMClient(self.settings.llm, self.settings.http_proxy)

    def status_text(self) -> str:
        llm = self.settings.llm
        if llm.is_configured:
            return f"{llm.provider} / {llm.resolved_model()}"
        return "未配置 API Key（本地规则引擎）"

    def current_metrics(self, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        return metrics or latest_analysis(self.db_url) or {}

    # ------------------------------------------------------------------ #
    def advise(
        self,
        question: str,
        category: str = "general",
        metrics: dict[str, Any] | None = None,
        profile: str = "",
        force_local: bool = False,
        session_id: int | None = None,
        use_rag: bool = True,
    ) -> dict[str, Any]:
        """生成一条咨询建议并落库，返回结果字典。

        ``use_rag`` 为真时先从本地库检索相关作品/评论素材（BM25）注入提示词，
        检索失败或库为空时自动跳过，不影响咨询主流程。
        """
        question = (question or "").strip()
        if not question:
            return {"question": "", "answer": "请输入你的问题。", "highlights": [], "is_fallback": True}

        metrics = self.current_metrics(metrics)
        material_docs = retrieve_material(self.db_url, question, profile) if use_rag else []
        material_text = format_material(material_docs)
        answer = ""
        highlights: list[str] = []
        provider, model, is_fallback = "local", "rule-engine", True
        error = ""

        if force_local or not self.client.is_available:
            answer, highlights = P.local_advice(question, category, metrics, profile)
        else:
            try:
                result = self.client.chat(
                    P.build_advice_messages(question, category, metrics, profile, material_text)
                )
                answer = result.content
                provider, model, is_fallback = result.provider, result.model, False
                highlights = _extract_highlights(answer)
            except LLMError as exc:
                logger.error("咨询生成失败，回退本地规则: %s", exc)
                error = str(exc)
                answer, highlights = P.local_advice(question, category, metrics, profile)
                answer += f"\n\n> ⚠️ 大模型调用失败，已回退本地规则：{exc}"

        if session_id is None:
            session_id = create_session(self.db_url, question[:40], category)
        record_id = add_record(
            self.db_url,
            session_id,
            question=question,
            answer=answer,
            highlights=highlights,
            provider=provider,
            model=model,
            is_fallback=is_fallback,
        )

        return {
            "id": record_id,
            "session_id": session_id,
            "question": question,
            "category": category,
            "answer": answer,
            "highlights": highlights,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
            "materials": [doc.to_dict() for doc in material_docs],
        }

    # ------------------------------------------------------------------ #
    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        return list_records(self.db_url, limit=limit)

    def sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        return list_sessions(self.db_url, limit=limit)


def _extract_highlights(answer: str, limit: int = 6) -> list[str]:
    """从回答里抽取要点（编号列表 / 短句），用于界面上的要点标签。"""
    items: list[str] = []
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for prefix in ("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ", "7. ", "8. ", "9. "):
            if line.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        if 6 <= len(line) <= 60:
            items.append(line)
        if len(items) >= limit:
            break
    return items
