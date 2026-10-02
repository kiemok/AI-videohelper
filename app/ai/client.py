"""大模型调用客户端（OpenAI 兼容协议）。

同一份代码支持 DeepSeek、通义千问(DashScope 兼容模式) 及任意 OpenAI 兼容服务：
只需在设置页选择服务商（或填自定义 base_url）并填入用户自己的 API Key。
API Key 仅保存在本地配置文件，不进入版本库。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from app.config import PROVIDER_PRESETS, LLMSettings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)


class LLMError(RuntimeError):
    """大模型调用异常（网络/鉴权/返回格式）。"""


@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    is_fallback: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    #: 模型请求调用的工具（OpenAI function calling 格式）
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    #: 原始 assistant 消息（含 tool_calls），用于回传给模型继续对话
    raw_message: dict[str, Any] = field(default_factory=dict)

    def describe_source(self) -> str:
        if self.is_fallback:
            return "本地规则生成（未配置 API Key）"
        label = PROVIDER_PRESETS.get(self.provider, {}).get("label", self.provider)
        return f"{label} / {self.model}"


class LLMClient:
    """轻量 HTTP 客户端，仅依赖 requests。"""

    def __init__(self, settings: LLMSettings, proxy: str = "") -> None:
        self.settings = settings
        self.proxy = proxy or ""

    # ------------------------------------------------------------------ #
    @property
    def is_available(self) -> bool:
        return self.settings.is_configured

    def _endpoint(self) -> str:
        return f"{self.settings.resolved_base_url()}/chat/completions"

    def _proxies(self) -> dict[str, str] | None:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        """同步调用 Chat Completions，网络类错误自动重试一次。

        传入 ``tools``（OpenAI function calling 格式）时，模型可能返回 ``tool_calls``
        而不是直接给答案，由调用方执行工具后把结果回传（见 ``InsightService.ask``）。
        """
        if not self.is_available:
            raise LLMError("未配置 API Key / 模型，无法调用大模型")

        payload: dict[str, Any] = {
            "model": self.settings.resolved_model(),
            "messages": messages,
            "temperature": self.settings.temperature if temperature is None else temperature,
            "max_tokens": self.settings.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key.strip()}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(2):
            started = time.time()
            try:
                response = requests.post(
                    self._endpoint(),
                    json=payload,
                    headers=headers,
                    timeout=self.settings.timeout,
                    proxies=self._proxies(),
                )
                if response.status_code >= 400:
                    detail = response.text[:300]
                    raise LLMError(f"接口返回 {response.status_code}: {detail}")
                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                content = (message.get("content") or "").strip()
                tool_calls = message.get("tool_calls") or []
                if not content and not tool_calls:
                    raise LLMError("接口返回内容为空")
                logger.info(
                    "大模型调用成功: provider=%s model=%s 耗时=%.2fs",
                    self.settings.provider,
                    self.settings.resolved_model(),
                    time.time() - started,
                )
                return LLMResult(
                    content=content,
                    provider=self.settings.provider,
                    model=self.settings.resolved_model(),
                    usage=data.get("usage") or {},
                    tool_calls=list(tool_calls),
                    raw_message=dict(message),
                )
            except LLMError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                logger.warning("大模型调用失败(第 %d 次): %s", attempt + 1, exc)
                time.sleep(1.0)
        raise LLMError(f"大模型调用失败: {last_error}")

    def test_connection(self) -> tuple[bool, str]:
        """设置页「测试连接」使用。"""
        if not self.is_available:
            return False, "请先填写 API Key（以及必要的 base_url / 模型名）"
        try:
            result = self.chat(
                [{"role": "user", "content": "回复两个字：正常"}], temperature=0.0, max_tokens=16
            )
            return True, f"连接成功，模型回复：{result.content.strip()[:50]}"
        except LLMError as exc:
            return False, str(exc)
