"""AI 解读与建议服务：提示词 → 大模型调用 → 本地回退 → 结果落库。"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any, Callable

from app.ai import prompts as P
from app.ai.client import LLMClient, LLMError
from app.config import PROVIDER_PRESETS, AppSettings
from app.core.logging_setup import get_logger
from app.db.repository import (
    add_chat_message,
    create_chat_session,
    latest_analysis,
    save_report,
)
from app.skills import build_skill_prompt

logger = get_logger(__name__)

REPORT_TYPES = {
    "daily_brief": "数据简报",
    "topic_suggestion": "选题建议",
    "title_optimize": "标题优化",
    "publish_time": "发布时间建议",
    "chat": "问答",
}


class InsightService:
    """对外统一入口：界面层只调用这里的方法。"""

    def __init__(self, settings: AppSettings, db_url: str) -> None:
        self.settings = settings
        self.db_url = db_url

    # ------------------------------------------------------------------ #
    @property
    def client(self) -> LLMClient:
        return LLMClient(self.settings.llm, self.settings.http_proxy)

    def status(self) -> dict[str, Any]:
        llm = self.settings.llm
        label = PROVIDER_PRESETS.get(llm.provider, {}).get("label", llm.provider)
        return {
            "configured": llm.is_configured,
            "provider": llm.provider,
            "provider_label": label,
            "model": llm.resolved_model() or "（未设置）",
            "base_url": llm.resolved_base_url() or "（未设置）",
            "text": (
                f"已配置：{label} / {llm.resolved_model()}"
                if llm.is_configured
                else "未配置 API Key，将使用本地规则引擎生成解读"
            ),
        }

    def current_metrics(self, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        """优先使用传入的（当前界面显示）分析结果，否则读数据库最近一次。"""
        if metrics:
            return metrics
        return latest_analysis(self.db_url) or {}

    # ------------------------------------------------------------------ #
    def _generate(
        self,
        report_type: str,
        messages: list[dict[str, str]],
        fallback: Callable[[], str],
        metrics: dict[str, Any],
        force_local: bool = False,
    ) -> dict[str, Any]:
        """统一执行：能用大模型就用，否则（或失败时）回退本地规则，并落库。"""
        client = self.client
        stat_date = self._stat_date(metrics)
        content = ""
        provider, model, is_fallback = "local", "rule-engine", True
        error = ""

        if force_local or not client.is_available:
            content = fallback()
        else:
            try:
                result = client.chat(messages)
                content, provider, model, is_fallback = (
                    result.content,
                    result.provider,
                    result.model,
                    False,
                )
            except LLMError as exc:
                error = str(exc)
                logger.error("大模型生成失败，已回退本地规则: %s", exc)
                content = fallback() + f"\n\n> ⚠️ 大模型调用失败，已回退本地规则：{exc}"

        if report_type != "chat":
            try:
                save_report(
                    self.db_url,
                    {
                        "stat_date": stat_date,
                        "report_type": report_type,
                        "platform": metrics.get("platform", "") if metrics else "",
                        "prompt": messages[-1]["content"][:2000],
                        "content": content,
                        "provider": provider,
                        "model": model,
                        "is_fallback": is_fallback,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - 落库失败不影响展示
                logger.warning("保存 AI 报告失败: %s", exc)

        return {
            "content": content,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
            "report_type": report_type,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def _stat_date(metrics: dict[str, Any]) -> date:
        raw = (metrics or {}).get("stat_date")
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                pass
        if isinstance(raw, date):
            return raw
        return date.today()

    # ------------------------------------------------------------------ #
    def daily_brief(
        self, metrics: dict[str, Any] | None = None, force_local: bool = False
    ) -> dict[str, Any]:
        metrics = self.current_metrics(metrics)
        return self._generate(
            "daily_brief",
            P.daily_brief_messages(metrics),
            lambda: P.local_daily_brief(metrics),
            metrics,
            force_local,
        )

    def suggest_topics(
        self, metrics: dict[str, Any] | None = None, force_local: bool = False
    ) -> dict[str, Any]:
        metrics = self.current_metrics(metrics)
        return self._generate(
            "topic_suggestion",
            P.topic_suggestion_messages(metrics),
            lambda: P.local_topic_suggestions(metrics),
            metrics,
            force_local,
        )

    def optimize_titles(
        self,
        titles: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        force_local: bool = False,
    ) -> dict[str, Any]:
        metrics = self.current_metrics(metrics)
        titles = titles or [v.get("title", "") for v in (metrics.get("top_videos") or [])[:3]]
        fallback = lambda: (  # noqa: E731
            P._FALLBACK_NOTE
            + "\n### 本地规则生成的标题优化\n"
            + "\n".join(
                f"- 《{t}》→ 建议压缩到 18 字内并把**结果/数字**前置，"
                "例：把「用了半年的效率神器」改为「3 个用了半年的效率神器，第 2 个几乎没人知道」"
                for t in titles
            )
        )
        return self._generate(
            "title_optimize", P.title_optimize_messages(metrics, titles), fallback, metrics, force_local
        )

    def suggest_publish_time(
        self, metrics: dict[str, Any] | None = None, force_local: bool = False
    ) -> dict[str, Any]:
        metrics = self.current_metrics(metrics)
        return self._generate(
            "publish_time",
            P.publish_time_messages(metrics),
            lambda: P.local_publish_time(metrics),
            metrics,
            force_local,
        )

    # ------------------------------------------------------------------ #
    def ask(
        self,
        question: str,
        metrics: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        session_id: int | None = None,
        force_local: bool = False,
        skills: list[Any] | None = None,
        toolbox: Any | None = None,
        max_tool_rounds: int = 3,
    ) -> dict[str, Any]:
        """自由问答：问题 + 数据上下文 + 已启用技能/工具 → 回答（并写入会话历史）。

        - ``skills``：用户启用的技能（``app.skills.Skill``），其提示词注入 system prompt；
        - ``toolbox``：MCP 工具集合（``app.mcp.McpToolbox``），提供时启用 function calling 循环。
        """
        question = (question or "").strip()
        if not question:
            return {"content": "请输入问题。", "is_fallback": True, "provider": "local", "model": "rule-engine"}
        metrics = self.current_metrics(metrics)

        if session_id is None:
            session_id = create_chat_session(self.db_url, title=question[:30])
        add_chat_message(self.db_url, session_id, "user", question)

        # 技能提示词 + 可用工具说明 → 追加 system 消息
        extra_system: list[str] = []
        skill_text = build_skill_prompt(list(skills or []))
        if skill_text:
            extra_system.append(skill_text)
        tool_specs = list(toolbox.specs()) if toolbox is not None else []
        if tool_specs:
            extra_system.append(
                "【可用外部工具】你可以调用以下工具获取更精确的实时数据："
                f"{toolbox.describe()}。当问题需要具体数据（作品明细、评论样本、最新指标）时，"
                "优先调用工具而不是凭上下文推测；拿到工具结果后再给出结论。"
            )

        content = ""
        provider, model, is_fallback = "local", "rule-engine", True
        error = ""
        tool_trace: list[dict[str, Any]] = []

        client = self.client
        if force_local or not client.is_available:
            content = P.local_answer(metrics, question)
        else:
            try:
                content, provider, model, is_fallback, tool_trace = self._chat_with_tools(
                    metrics, question, history, extra_system, tool_specs, toolbox, max_tool_rounds
                )
            except LLMError as exc:
                error = str(exc)
                logger.error("问答失败，回退本地规则: %s", exc)
                content = (
                    P.local_answer(metrics, question)
                    + f"\n\n> ⚠️ 大模型调用失败，已回退本地规则：{exc}"
                )

        add_chat_message(self.db_url, session_id, "assistant", content, bool(is_fallback))
        return {
            "content": content,
            "provider": provider,
            "model": model,
            "is_fallback": is_fallback,
            "error": error,
            "report_type": "chat",
            "session_id": session_id,
            "tool_trace": tool_trace,
        }

    # ------------------------------------------------------------------ #
    def _chat_with_tools(
        self,
        metrics: dict[str, Any],
        question: str,
        history: list[dict[str, str]] | None,
        extra_system: list[str],
        tool_specs: list[dict[str, Any]],
        toolbox: Any | None,
        max_rounds: int,
    ) -> tuple[str, str, str, bool, list[dict[str, Any]]]:
        """带工具调用的问答循环。

        模型若返回 ``tool_calls``，就本地执行（MCP）并把结果回传，最多循环
        ``max_rounds`` 轮；超出后强制模型基于已有结果收尾。
        """
        messages = P.chat_messages(metrics, question, history, extra_system)
        trace: list[dict[str, Any]] = []
        result = None

        for _round in range(max(1, max_rounds)):
            result = self.client.chat(messages, tools=tool_specs or None)
            if not result.tool_calls:
                return result.content, result.provider, result.model, False, trace

            messages.append(
                {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": result.tool_calls,
                }
            )
            for call in result.tool_calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                raw_arguments = function.get("arguments") or "{}"
                try:
                    arguments = (
                        json.loads(raw_arguments)
                        if isinstance(raw_arguments, str)
                        else dict(raw_arguments)
                    )
                except (ValueError, TypeError):
                    arguments = {}
                output = toolbox.call(name, arguments) if toolbox is not None else "（未配置工具执行器）"
                logger.info("工具调用 %s(%s) 返回 %d 字符", name, arguments, len(output))
                trace.append({"tool": name, "arguments": arguments, "output": output[:600]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": output,
                    }
                )

        # 达到轮数上限：基于已有工具结果收尾，不再提供工具
        final = self.client.chat(
            messages
            + [
                {
                    "role": "user",
                    "content": "请基于以上工具返回的结果直接给出最终回答，不要再调用工具。",
                }
            ]
        )
        return final.content, final.provider, final.model, False, trace
