"""Directory-plugin entry point for `hermes plugins install`."""
from __future__ import annotations

try:
    from .hermes_openai_codex_web_search import register
except ImportError:  # Pytest may import this root file as top-level ``__init__``.
    from hermes_openai_codex_web_search import register

__all__ = ["register"]
