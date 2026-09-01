"""Hermes OpenAI Codex hosted web-search plugin."""

from __future__ import annotations

from .provider import OpenAICodexWebSearchProvider

__all__ = ["OpenAICodexWebSearchProvider", "register"]


def register(ctx) -> None:
    """Register the OpenAI Codex hosted-search backend with Hermes."""
    config_getter = getattr(ctx, "get_config", None)
    ctx.register_web_search_provider(
        OpenAICodexWebSearchProvider(
            config_getter=config_getter if callable(config_getter) else None,
        )
    )
