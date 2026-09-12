"""AI runtime configuration persisted under 运行产物/AI配置.

The file lives inside the user-data directory (never committed); ``api_key``
is never returned to the frontend — only a masked hint is.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR_NAME = "AI配置"
CONFIG_FILE_NAME = "ai-config.json"


SUPPORTED_API_STYLES = ("chat-completions", "responses", "anthropic")
SUPPORTED_RESEARCH_STYLES = ("conservative", "balanced", "aggressive")


@dataclass
class AiConfig:
    """OpenAI-compatible provider settings. Empty by default until the user
    fills them in the desktop settings dialog.

    ``api_style`` selects the wire protocol:
    - ``chat-completions``: POST {base}/chat/completions（OpenAI 兼容，默认）;
    - ``responses``: OpenAI Responses API（GPT-5 系等新接口）;
    - ``anthropic``: Anthropic Messages API（{base}/v1/messages）。

    ``research_style`` selects the analyst persona: conservative / balanced /
    aggressive（对应保守/均衡/激进三种研究风格，注入 system prompt）。
    """

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    embedding_model: str = ""
    api_style: str = "chat-completions"
    research_style: str = "balanced"
    temperature: float = 0.3
    max_steps: int = 8
    insights_enabled: bool = True
    insight_max_per_hour: int = 6

    def is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())

    def sanitized(self) -> AiConfig:
        cfg = AiConfig(**asdict(self))
        cfg.base_url = cfg.base_url.strip().rstrip("/")
        cfg.api_key = cfg.api_key.strip()
        cfg.model = cfg.model.strip()
        cfg.embedding_model = cfg.embedding_model.strip()
        if cfg.api_style not in SUPPORTED_API_STYLES:
            cfg.api_style = "chat-completions"
        if cfg.research_style not in SUPPORTED_RESEARCH_STYLES:
            cfg.research_style = "balanced"
        cfg.temperature = min(max(cfg.temperature, 0.0), 2.0)
        cfg.max_steps = max(1, min(int(cfg.max_steps), 16))
        cfg.insight_max_per_hour = max(0, min(int(cfg.insight_max_per_hour), 60))
        return cfg


def masked_key(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}****{key[-4:]}"


class AiConfigStore:
    """Load/save ``ai-config.json`` with atomic writes and key preservation.

    ``save`` treats an empty ``api_key`` as "keep the existing key" so the
    settings dialog never needs to round-trip the secret back to the user.
    """

    def __init__(self, ai_base_dir: str | Path) -> None:
        self._dir = Path(ai_base_dir) / CONFIG_DIR_NAME
        self._path = self._dir / CONFIG_FILE_NAME

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AiConfig:
        if not self._path.exists():
            return AiConfig()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AiConfig()
        if not isinstance(payload, dict):
            return AiConfig()
        known = {key: payload[key] for key in asdict(AiConfig()) if key in payload}
        try:
            return AiConfig(**known).sanitized()
        except (TypeError, ValueError):
            return AiConfig()

    def save(self, config: AiConfig) -> AiConfig:
        current = self.load()
        merged = AiConfig(**asdict(config))
        if not merged.api_key.strip():
            merged.api_key = current.api_key
        merged = merged.sanitized()
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(asdict(merged), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)
        return merged

    def masked_view(self) -> dict[str, object]:
        config = self.load().sanitized()
        return {
            "base_url": config.base_url,
            "model": config.model,
            "embedding_model": config.embedding_model,
            "api_style": config.api_style,
            "research_style": config.research_style,
            "api_key_masked": masked_key(config.api_key),
            "temperature": config.temperature,
            "max_steps": config.max_steps,
            "insights_enabled": config.insights_enabled,
            "insight_max_per_hour": config.insight_max_per_hour,
            "configured": config.is_configured(),
        }


def ai_base_dir_from_cache_dir(cache_dir: str | Path) -> Path:
    """Resolve 运行产物 root from the data-warehouse directory.

    The warehouse lives at ``运行产物/本地数据仓`` in the desktop layout, so the
    AI user data (config / chats / embedding cache) sits next to it as sibling
    directories.  Falls back to the cache dir itself when the parent is not
    writable (portable/odd layouts).
    """
    root = Path(cache_dir).resolve()
    candidate = root.parent
    probe = candidate / ".ai-write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return candidate
    except OSError:
        return root
