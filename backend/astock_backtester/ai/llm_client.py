"""Thin wrapper around the official ``openai`` SDK (OpenAI-compatible providers).

The SDK owns SSE framing, tool-call delta accumulation, transport retries and
timeouts; this wrapper only maps provider failures onto the module's stable
error codes, normalizes the streaming output into a simple event protocol, and
keeps a rough token estimate for budget accounting.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Protocol

from astock_backtester.ai.config import AiConfig
from astock_backtester.ai.errors import AiNotConfigured, AiUpstreamError

ChatEvent = tuple[str, Any]
"""("text", delta) while streaming content, then ("final", turn dict)."""


class ChatModel(Protocol):
    """The Agent loop only depends on this protocol; tests swap in a fake."""

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> Iterator[ChatEvent]:
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _default_client_factory(config: AiConfig) -> Any:
    from openai import OpenAI

    return OpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=60.0,
        max_retries=2,
    )


def _map_provider_error(exc: Exception) -> AiUpstreamError:
    name = type(exc).__name__
    detail = str(exc)
    if len(detail) > 400:
        detail = detail[:400] + "..."
    return AiUpstreamError(f"模型服务调用失败（{name}）：{detail}")


class OpenAiCompatibleClient:
    """ChatModel implementation backed by the openai SDK."""

    def __init__(
        self,
        config_provider: Callable[[], AiConfig],
        client_factory: Callable[[AiConfig], Any] | None = None,
    ) -> None:
        self._config_provider = config_provider
        self._client_factory = client_factory or _default_client_factory

    def _require_config(self) -> AiConfig:
        config = self._config_provider()
        if not config.is_configured():
            raise AiNotConfigured("AI 服务尚未配置，请先在设置中填写 base_url、API Key 和模型名。")
        return config

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatEvent]:
        config = self._require_config()
        client = self._client_factory(config)
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            stream = client.chat.completions.create(**kwargs)
        except Exception as exc:  # openai SDK raises SDK-specific exceptions
            raise _map_provider_error(exc) from exc

        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        try:
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) if delta is not None else None
                if text:
                    content_parts.append(text)
                    yield ("text", text)
                raw_calls = getattr(delta, "tool_calls", None) if delta is not None else None
                for raw in raw_calls or []:
                    slot = tool_calls.setdefault(
                        raw.index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if raw.id:
                        slot["id"] = raw.id
                    function = getattr(raw, "function", None)
                    if function is not None:
                        if function.name and not slot["function"]["name"]:
                            slot["function"]["name"] = function.name
                        if function.arguments:
                            slot["function"]["arguments"] += function.arguments
        except Exception as exc:
            raise _map_provider_error(exc) from exc

        ordered = [tool_calls[index] for index in sorted(tool_calls)]
        for call in ordered:
            if not call["id"]:
                call["id"] = f"call_{index_ok(ordered, call)}"
        yield (
            "final",
            {
                "content": "".join(content_parts) or None,
                "tool_calls": ordered or None,
            },
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        config = self._require_config()
        if not config.embedding_model.strip():
            raise AiNotConfigured("未配置 embedding_model，知识检索不可用。")
        client = self._client_factory(config)
        try:
            response = client.embeddings.create(model=config.embedding_model, input=texts)
        except Exception as exc:
            raise _map_provider_error(exc) from exc
        return [item.embedding for item in response.data]


def index_ok(ordered: list[dict[str, Any]], call: dict[str, Any]) -> int:
    """Fallback synthetic index for providers that omit tool-call ids."""
    try:
        return ordered.index(call)
    except ValueError:
        return 0


def estimate_tokens(text: str) -> int:
    """Rough budget proxy: CJK ≈ 1 token/char, ASCII ≈ 4 chars/token."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    return cjk + max(0, (len(text) - cjk) // 4)
