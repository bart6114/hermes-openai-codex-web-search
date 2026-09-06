"""OpenAI Codex hosted web-search provider."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from agent.web_search_provider import WebSearchProvider
from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 90.0
_VALID_CONTEXT_SIZES = {"low", "medium", "high"}
_SEARCH_OUTPUT_TYPES = {"web_search_call", "webSearch", "web_search"}
_TERMINAL_EVENT_TYPES = {
    "response.completed",
    "response.failed",
    "response.incomplete",
}
_PLUGIN_SETTING_KEYS = ("model", "mode", "context_size", "timeout")
_MISSING = object()
PluginConfigGetter = Callable[[str, Any], Any]


def _has_codex_credentials() -> bool:
    """Cheap auth-store probe that never refreshes OAuth tokens."""
    try:
        auth_path = get_hermes_home() / "auth.json"
        if not auth_path.exists():
            return False
        store = json.loads(auth_path.read_text(encoding="utf-8-sig"))
        if not isinstance(store, dict):
            return False

        providers = store.get("providers")
        state = providers.get("openai-codex") if isinstance(providers, dict) else None
        tokens = state.get("tokens") if isinstance(state, dict) else None
        if isinstance(tokens, dict) and str(tokens.get("access_token") or "").strip():
            return True

        pool = store.get("credential_pool")
        entries = pool.get("openai-codex") if isinstance(pool, dict) else None
        if isinstance(entries, list):
            return any(
                isinstance(entry, dict) and str(entry.get("access_token") or "").strip()
                for entry in entries
            )
    except Exception:
        return False
    return False


def _load_openai_codex_web_config(
    get_plugin_config: PluginConfigGetter | None = None,
) -> dict[str, Any]:
    """Return plugin-owned settings plus legacy and main-model fallbacks."""
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
    except Exception as exc:
        logger.debug("Could not load Hermes config: %s", exc)
        config = {}
    if not isinstance(config, dict):
        config = {}

    web = config.get("web")
    section = web.get("openai_codex") if isinstance(web, dict) else None
    result = dict(section) if isinstance(section, dict) else {}

    # Hermes rejects the plugin-relative key "model" as a reserved core root,
    # even inside this plugin's settings. Read only our own model leaf from the
    # already-loaded, profile-scoped config; never ask ctx.get_config("model").
    plugins = config.get("plugins")
    entries = plugins.get("entries") if isinstance(plugins, dict) else None
    entry = entries.get("web-openai-codex") if isinstance(entries, dict) else None
    if isinstance(entry, dict):
        for subtree in ("config", "settings"):
            settings = entry.get(subtree)
            if isinstance(settings, dict) and "model" in settings:
                result["model"] = settings["model"]

    # Other keys use the public plugin-relative API (settings, then config).
    # web.openai_codex remains a read-only fallback for existing installations.
    if get_plugin_config is not None:
        for key in _PLUGIN_SETTING_KEYS:
            if key == "model":
                continue
            try:
                value = get_plugin_config(key, _MISSING)
            except Exception as exc:
                logger.debug("Could not read plugin setting %s: %s", key, exc)
                continue
            if value is not _MISSING:
                result[key] = value

    if not str(result.get("model") or "").strip():
        model = config.get("model")
        if (
            isinstance(model, dict)
            and str(model.get("provider") or "").strip().lower() == "openai-codex"
        ):
            result["model"] = model.get("default") or model.get("model") or ""
    return result


def resolve_codex_runtime_credentials() -> dict[str, Any]:
    """Resolve and refresh Codex OAuth credentials only for a real search."""
    from hermes_cli.auth import resolve_codex_runtime_credentials as resolve

    return resolve()


def _create_codex_client(*, api_key: str, base_url: str):
    from agent.auxiliary_client import _create_openai_client

    try:
        from agent.codex_headers import codex_cloudflare_headers

        headers = codex_cloudflare_headers(api_key, base_url=base_url)
    except ImportError:
        # Hermes 0.20.x kept this helper in auxiliary_client and accepted
        # only the token argument. Keep the advertised minimum compatible.
        from agent.auxiliary_client import _codex_cloudflare_headers

        headers = _codex_cloudflare_headers(api_key)

    return _create_openai_client(
        api_key=api_key,
        base_url=base_url,
        default_headers=headers,
    )


def _is_interrupted() -> bool:
    try:
        from tools.interrupt import is_interrupted

        return bool(is_interrupted())
    except Exception:
        return False


def _consume_codex_event_stream(
    stream: Any,
    *,
    model: str,
    interrupt_check: Any = None,
) -> Any:
    from agent.codex_runtime import _consume_codex_event_stream as consume

    terminal_event_seen = False

    def observe_event(event: Any) -> None:
        nonlocal terminal_event_seen
        if _item_get(event, "type") in _TERMINAL_EVENT_TYPES:
            terminal_event_seen = True

    final = consume(
        stream,
        model=model,
        interrupt_check=interrupt_check,
        on_event=observe_event,
    )
    # Hermes's stream consumer deliberately does not expose whether it saw a
    # terminal frame when partial output exists. Record the observation here
    # so the provider can reject truncated-but-plausible output.
    final.terminal_event_seen = terminal_event_seen
    return final


def _wire_model_name(model: str) -> str:
    try:
        from agent.model_metadata import strip_codex_context_variant_suffix

        return strip_codex_context_variant_suffix(model)
    except ImportError:
        # Hermes 0.20.5 predates the helper but understands the base model.
        # Only strip aliases known to be valid; invalid aliases must still
        # fail honestly at the provider instead of silently changing models.
        raw = model.strip()
        bare = raw.rsplit("/", 1)[-1].lower()
        if bare in {"gpt-5.6-luna-900k", "gpt-5.6-sol-900k"}:
            return raw[: -len("-900k")]
        return raw


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _collect_response_text(final: Any) -> tuple[list[str], list[dict[str, Any]]]:
    texts: list[str] = []
    annotations: list[dict[str, Any]] = []
    for item in _item_get(final, "output", []) or []:
        if _item_get(item, "type") != "message":
            continue
        for part in _item_get(item, "content", []) or []:
            if _item_get(part, "type") not in {"output_text", "text"}:
                continue
            text = _item_get(part, "text", "")
            if isinstance(text, str) and text.strip():
                texts.append(text)
            for annotation in _item_get(part, "annotations", []) or []:
                if isinstance(annotation, dict):
                    annotations.append(annotation)
                elif annotation is not None:
                    annotations.append(
                        {
                            key: getattr(annotation, key, None)
                            for key in ("type", "url", "title", "start_index", "end_index")
                        }
                    )
    return texts, annotations


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _json_objects(text: str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects embedded in a model response, in source order."""
    decoder = json.JSONDecoder()
    stripped = text.strip()
    starts = [index for index, char in enumerate(stripped) if char == "{"]
    for start in starts:
        try:
            payload, _ = decoder.raw_decode(stripped[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(payload, dict):
            yield payload


def _parse_json_results(
    texts: list[str],
    limit: int,
) -> list[dict[str, Any]] | None:
    for text in texts:
        for payload in _json_objects(text):
            rows = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            if not rows:
                return []
            normalized: list[dict[str, Any]] = []
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not _is_http_url(url) or url in seen:
                    continue
                seen.add(url)
                normalized.append(
                    {
                        "title": str(row.get("title") or "").strip(),
                        "url": url,
                        "description": str(row.get("description") or "").strip(),
                        "position": len(normalized) + 1,
                    }
                )
                if len(normalized) >= limit:
                    break
            if normalized:
                return normalized
    return None


def _results_from_annotations(
    annotations: list[dict[str, Any]],
    texts: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    description = "\n".join(texts).strip()[:500]
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for annotation in annotations:
        if annotation.get("type") != "url_citation":
            continue
        url = str(annotation.get("url") or "").strip()
        if not _is_http_url(url) or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": str(annotation.get("title") or "").strip(),
                "url": url,
                "description": description,
                "position": len(results) + 1,
            }
        )
        if len(results) >= limit:
            break
    return results


class OpenAICodexWebSearchProvider(WebSearchProvider):
    """Search-only provider backed by OpenAI Codex hosted search."""

    def __init__(
        self,
        *,
        config_getter: PluginConfigGetter | None = None,
    ) -> None:
        self._config_getter = config_getter

    @property
    def name(self) -> str:
        return "openai-codex"

    @property
    def display_name(self) -> str:
        return "OpenAI Codex Hosted Search"

    def is_available(self) -> bool:
        return _has_codex_credentials()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        if _is_interrupted():
            return {"success": False, "error": "Interrupted"}

        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 5

        try:
            credentials = resolve_codex_runtime_credentials()
        except Exception as exc:
            return {"success": False, "error": f"No usable OpenAI Codex credentials: {exc}"}

        api_key = str(credentials.get("api_key") or "").strip()
        base_url = str(credentials.get("base_url") or "").strip().rstrip("/")
        if not api_key or not base_url:
            return {
                "success": False,
                "error": "No OpenAI Codex credentials found. Run `hermes auth`.",
            }

        config = _load_openai_codex_web_config(self._config_getter)
        model = _wire_model_name(str(config.get("model") or "").strip())
        if not model:
            return {
                "success": False,
                "error": (
                    "OpenAI Codex hosted search needs a model. Set "
                    "plugins.entries.web-openai-codex.settings.model or choose "
                    "an OpenAI Codex model."
                ),
            }
        try:
            timeout = float(config.get("timeout", DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        if timeout <= 0 or not math.isfinite(timeout):
            timeout = DEFAULT_TIMEOUT

        context_size = str(config.get("context_size") or "medium").strip().lower()
        if context_size not in _VALID_CONTEXT_SIZES:
            context_size = "medium"
        mode = str(config.get("mode") or "live").strip().lower()
        if mode not in {"cached", "live"}:
            mode = "live"

        web_search_tool: dict[str, Any] = {
            "type": "web_search",
            "external_web_access": mode == "live",
            "search_context_size": context_size,
        }
        prompt = (
            "Use hosted web search for the query below. Return ONLY one JSON object "
            "matching this schema: "
            '{"results":[{"title":"string","url":"https://...",'
            '"description":"1-2 sentence summary"}]}. '
            f"Return at most {limit} results in relevance order. Query: {query}"
        )
        request = {
            "model": model,
            "instructions": (
                "You are a bounded web-search worker. You must invoke the hosted "
                "web_search tool before answering and return grounded source URLs."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "tools": [web_search_tool],
            "store": False,
            "stream": True,
            "timeout": timeout,
        }

        stream = None
        try:
            client = _create_codex_client(api_key=api_key, base_url=base_url)
            stream = client.responses.create(**request)
            final = _consume_codex_event_stream(
                stream,
                model=model,
                interrupt_check=_is_interrupted,
            )
        except Exception as exc:
            logger.warning("OpenAI Codex hosted search failed: %s", exc)
            return {"success": False, "error": f"OpenAI Codex hosted search failed: {exc}"}
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()

        if _is_interrupted():
            return {"success": False, "error": "Interrupted"}

        if _item_get(final, "terminal_event_seen", False) is not True:
            return {
                "success": False,
                "error": "OpenAI Codex hosted search ended without a terminal event.",
            }

        status = str(_item_get(final, "status", "completed") or "completed").lower()
        if status != "completed":
            detail = _item_get(final, "error") or _item_get(final, "incomplete_details")
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("reason") or detail
            suffix = f": {detail}" if detail else ""
            return {
                "success": False,
                "error": f"OpenAI Codex hosted search ended {status}{suffix}",
            }

        output = _item_get(final, "output", []) or []
        search_items = [item for item in output if _item_get(item, "type") in _SEARCH_OUTPUT_TYPES]
        if not search_items:
            return {
                "success": False,
                "error": "OpenAI Codex answered without invoking hosted web search.",
            }
        search_completed = any(
            str(_item_get(item, "status", "") or "").lower() in {"completed", "succeeded"}
            for item in search_items
        )
        if not search_completed:
            return {
                "success": False,
                "error": "OpenAI Codex hosted web search did not complete.",
            }

        texts, annotations = _collect_response_text(final)
        results = _parse_json_results(texts, limit)
        if results is None:
            results = _results_from_annotations(annotations, texts, limit)
        return {"success": True, "data": {"web": results}}

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            "name": self.display_name,
            "badge": "subscription",
            "tag": "Uses your existing OpenAI Codex / ChatGPT sign-in.",
            "env_vars": [],
        }
