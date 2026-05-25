"""
llm/router.py

按 config 选择并实例化正确的 LLMBackend。

支持的 provider：
    anthropic  → AnthropicBackend
    openai     → OpenAICompatBackend (base_url=None)
    deepseek   → OpenAICompatBackend (base_url=https://api.deepseek.com)
    groq       → OpenAICompatBackend (base_url=https://api.groq.com/openai/v1)
    ollama     → OpenAICompatBackend (base_url=http://localhost:11434/v1)

新增 provider 只需在 _PROVIDER_BASE_URLS 加一行。
"""

from __future__ import annotations

import os

from llm.base import LLMBackend

# provider → base_url 映射（None 表示使用 SDK 默认）
_PROVIDER_BASE_URLS: dict[str, str | None] = {
    "anthropic": None,      # 走 AnthropicBackend，不用这张表
    "openai":    None,
    "deepseek":  "https://api.deepseek.com",
    "groq":      "https://api.groq.com/openai/v1",
    "ollama":    "http://localhost:11434/v1",
}

# provider → 环境变量名（api_key 未配置时的 fallback）
_ENV_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "deepseek":  "DEEPSEEK_API_KEY",
    "groq":      "GROQ_API_KEY",
    "ollama":    "OLLAMA_API_KEY",   # Ollama 本地通常不需要，留空即可
}


def create_backend(
    provider: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 4096,
) -> LLMBackend:
    """
    工厂函数，根据 provider 创建对应的 LLMBackend。

    Args:
        provider:   "anthropic" | "openai" | "deepseek" | "groq" | "ollama"
        model:      模型名，如 "claude-sonnet-4-5", "gpt-4o", "deepseek-chat"
        api_key:    API key，None 时从环境变量读取
        base_url:   覆盖默认 base_url（通常不需要手动传）
        max_tokens: 最大输出 token 数

    Returns:
        对应的 LLMBackend 实例

    Raises:
        ValueError: provider 不支持，或 api_key 缺失
    """
    provider = provider.lower().strip()

    if provider not in _PROVIDER_BASE_URLS:
        supported = ", ".join(sorted(_PROVIDER_BASE_URLS))
        raise ValueError(
            f"Unsupported provider '{provider}'. Supported: {supported}"
        )

    # 解析 api_key
    resolved_key = api_key or os.environ.get(_ENV_KEY_MAP.get(provider, ""), "")
    if not resolved_key and provider != "ollama":
        env_var = _ENV_KEY_MAP.get(provider, "")
        raise ValueError(
            f"API key for '{provider}' not provided. "
            f"Set it via config or environment variable {env_var!r}."
        )
    # Ollama 本地不需要真实 key，给个占位符
    if not resolved_key:
        resolved_key = "ollama"

    if provider == "anthropic":
        from llm.anthropic_backend import AnthropicBackend
        return AnthropicBackend(
            model=model,
            api_key=resolved_key,
            max_tokens=max_tokens,
        )

    # 所有 OpenAI-compatible providers
    from llm.openai_compat import OpenAICompatBackend

    # base_url 优先级：调用方显式传入 > provider 默认值
    resolved_base_url = base_url or _PROVIDER_BASE_URLS[provider]

    return OpenAICompatBackend(
        model=model,
        api_key=resolved_key,
        base_url=resolved_base_url,
        max_tokens=max_tokens,
    )


def create_backend_from_config(config: dict) -> LLMBackend:
    """
    从配置字典创建 backend，对应 config/default.yaml 的 llm 节。

    config 格式：
        provider: anthropic
        model: claude-sonnet-4-5
        api_key: sk-...        # 可选，缺省读环境变量
        base_url:              # 可选
        max_tokens: 4096       # 可选
    """
    return create_backend(
        provider=config.get("provider", "anthropic"),
        model=config.get("model", "claude-sonnet-4-5"),
        api_key=config.get("api_key") or None,
        base_url=config.get("base_url") or None,
        max_tokens=int(config.get("max_tokens", 4096)),
    )