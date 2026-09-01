"""Directory-plugin entry point for `hermes plugins install`."""

from __future__ import annotations

if __package__:
    from .hermes_openai_codex_web_search import register
else:  # Pytest may import this root file as top-level ``__init__``.
    from hermes_openai_codex_web_search import register

__all__ = ["register"]
