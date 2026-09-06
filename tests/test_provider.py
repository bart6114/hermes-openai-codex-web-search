"""Tests for the OpenAI Codex hosted web-search provider."""

from __future__ import annotations

import json
from types import SimpleNamespace


class TestOpenAICodexProviderIdentity:
    def test_provider_identity_and_capabilities(self):
        from hermes_openai_codex_web_search.provider import OpenAICodexWebSearchProvider

        provider = OpenAICodexWebSearchProvider()
        assert provider.name == "openai-codex"
        assert provider.display_name == "OpenAI Codex Hosted Search"
        assert provider.supports_search() is True
        assert provider.supports_extract() is False


class TestOpenAICodexAvailability:
    def test_available_from_provider_singleton_without_refresh(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps(
                {"providers": {"openai-codex": {"tokens": {"access_token": "oauth-token"}}}}
            ),
            encoding="utf-8",
        )

        from hermes_openai_codex_web_search.provider import OpenAICodexWebSearchProvider

        assert OpenAICodexWebSearchProvider().is_available() is True

    def test_available_from_credential_pool_without_refresh(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "auth.json").write_text(
            json.dumps({"credential_pool": {"openai-codex": [{"access_token": "pool-token"}]}}),
            encoding="utf-8",
        )

        from hermes_openai_codex_web_search.provider import OpenAICodexWebSearchProvider

        assert OpenAICodexWebSearchProvider().is_available() is True

    def test_unavailable_when_auth_store_is_missing_or_invalid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))

        from hermes_openai_codex_web_search.provider import OpenAICodexWebSearchProvider

        provider = OpenAICodexWebSearchProvider()
        assert provider.is_available() is False

        (tmp_path / "auth.json").write_text("not-json", encoding="utf-8")
        assert provider.is_available() is False


class TestOpenAICodexConfig:
    def test_non_codex_main_model_is_not_sent_to_codex_endpoint(self, monkeypatch):
        from hermes_cli import config as config_module

        from hermes_openai_codex_web_search import provider as codex_provider

        monkeypatch.setattr(
            config_module,
            "load_config_readonly",
            lambda *args: {
                "model": {"provider": "anthropic", "default": "claude-opus-4-1"},
                "web": {"search_backend": "openai-codex"},
            },
        )

        config = codex_provider._load_openai_codex_web_config()

        assert not config.get("model")

    def test_plugin_owned_settings_override_legacy_settings(self, monkeypatch):
        from hermes_cli import config as config_module

        from hermes_openai_codex_web_search import provider as codex_provider

        monkeypatch.setattr(
            config_module,
            "load_config_readonly",
            lambda: {
                "model": {"provider": "openai-codex", "default": "gpt-main"},
                "web": {
                    "openai_codex": {
                        "model": "gpt-legacy",
                        "mode": "cached",
                    }
                },
                "plugins": {
                    "entries": {
                        "web-openai-codex": {
                            "settings": {"model": "gpt-plugin"},
                        }
                    }
                },
            },
        )
        settings = {"context_size": "high"}

        config = codex_provider._load_openai_codex_web_config(
            lambda key, default=None: settings.get(key, default)
        )

        assert config == {
            "model": "gpt-plugin",
            "mode": "cached",
            "context_size": "high",
        }


class TestCodexStreamAdapter:
    def test_records_real_terminal_event_contract(self):
        from hermes_openai_codex_web_search import provider as codex_provider

        final = codex_provider._consume_codex_event_stream(
            iter(
                [
                    {
                        "type": "response.completed",
                        "response": {"status": "completed", "output": []},
                    }
                ]
            ),
            model="gpt-5.6-sol",
        )

        assert final.status == "completed"
        assert final.terminal_event_seen is True

    def test_marks_truncated_partial_stream_as_non_terminal(self, monkeypatch):
        from agent import codex_runtime

        from hermes_openai_codex_web_search import provider as codex_provider

        def consume(events, *, model, on_event, **kwargs):
            for event in events:
                on_event(event)
            return SimpleNamespace(output=[{"type": "message"}], status="completed")

        monkeypatch.setattr(codex_runtime, "_consume_codex_event_stream", consume)

        final = codex_provider._consume_codex_event_stream(
            iter([{"type": "response.output_text.delta", "delta": "partial"}]),
            model="gpt-5.6-sol",
        )

        assert final.terminal_event_seen is False


class _FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return iter([{"type": "response.completed", "response": {"status": "completed"}}])


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponses()


def _final_response(
    text: str,
    *,
    searched: bool = True,
    search_status: str = "completed",
    annotations=None,
):
    output = []
    if searched:
        output.append(SimpleNamespace(type="web_search_call", status=search_status))
    output.append(
        SimpleNamespace(
            type="message",
            content=[
                SimpleNamespace(
                    type="output_text",
                    text=text,
                    annotations=annotations or [],
                )
            ],
        )
    )
    return SimpleNamespace(
        output=output,
        status="completed",
        terminal_event_seen=True,
    )


class TestOpenAICodexSearch:
    def test_search_stops_before_auth_when_interrupted(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        monkeypatch.setattr(codex_provider, "_is_interrupted", lambda: True, raising=False)
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: (_ for _ in ()).throw(AssertionError("auth must not run")),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result == {"success": False, "error": "Interrupted"}

    def test_search_discards_partial_output_when_interrupted_during_stream(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        checks = 0

        def interrupted():
            nonlocal checks
            checks += 1
            return checks >= 2

        monkeypatch.setattr(codex_provider, "_is_interrupted", interrupted)
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(
                '{"results":[{"title":"Partial","url":"https://example.com",'
                '"description":"partial"}]}'
            ),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result == {"success": False, "error": "Interrupted"}

    def test_search_uses_native_hosted_tool_and_normalizes_results(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        payload = json.dumps(
            {
                "results": [
                    {
                        "title": "Current result",
                        "url": "https://example.com/current",
                        "description": "Verified current information.",
                    }
                ]
            }
        )
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda *args: {
                "api_key": "oauth-token",
                "base_url": "https://chatgpt.com/backend-api/codex",
            },
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {
                "model": "gpt-5.6-sol-900k",
                "timeout": 42,
                "mode": "live",
                "context_size": "high",
            },
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_create_codex_client",
            lambda **kwargs: client,
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(payload),
            raising=False,
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search(
            "latest technology news", limit=3
        )

        assert result == {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Current result",
                        "url": "https://example.com/current",
                        "description": "Verified current information.",
                        "position": 1,
                    }
                ]
            },
        }
        assert client.responses.kwargs["model"] == "gpt-5.6-sol"
        assert client.responses.kwargs["store"] is False
        assert client.responses.kwargs["stream"] is True
        assert client.responses.kwargs["timeout"] == 42
        assert client.responses.kwargs["tools"] == [
            {
                "type": "web_search",
                "external_web_access": True,
                "search_context_size": "high",
            }
        ]
        assert "latest technology news" in str(client.responses.kwargs["input"])

    def test_search_fails_closed_when_provider_did_not_search(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_create_codex_client",
            lambda **kwargs: client,
            raising=False,
        )
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response('{"results": []}', searched=False),
            raising=False,
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["success"] is False
        assert "without invoking hosted web search" in result["error"]

    def test_search_rejects_failed_hosted_search_call(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        payload = '{"results":[{"title":"Ungrounded","url":"https://example.com",'
        payload += '"description":"model-only"}]}'
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(payload, search_status="failed"),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["success"] is False
        assert "hosted web search did not complete" in result["error"]

    def test_search_rejects_failed_terminal_response(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        final = _final_response(
            '{"results":[{"title":"Partial","url":"https://example.com","description":"partial"}]}'
        )
        final.status = "failed"
        final.error = {"message": "provider failed after partial output"}
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: final,
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["success"] is False
        assert "provider failed after partial output" in result["error"]

    def test_search_rejects_output_without_terminal_event(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        final = _final_response('{"results": []}')
        final.terminal_event_seen = False
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: final,
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["success"] is False
        assert "without a terminal event" in result["error"]

    def test_search_uses_url_citations_when_model_does_not_return_json(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        annotations = [
            {
                "type": "url_citation",
                "url": "https://example.com/source",
                "title": "Canonical source",
            }
        ]
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_create_codex_client",
            lambda **kwargs: client,
        )
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(
                "Grounded answer without the requested JSON.",
                annotations=annotations,
            ),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["success"] is True
        assert result["data"]["web"] == [
            {
                "title": "Canonical source",
                "url": "https://example.com/source",
                "description": "Grounded answer without the requested JSON.",
                "position": 1,
            }
        ]

    def test_search_uses_citations_when_json_rows_are_all_invalid(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        annotations = [
            {
                "type": "url_citation",
                "url": "https://example.com/grounded",
                "title": "Grounded citation",
            }
        ]
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(
                '{"results":[{"title":"Unsafe","url":"javascript:alert(1)"}]}',
                annotations=annotations,
            ),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert [row["url"] for row in result["data"]["web"]] == ["https://example.com/grounded"]

    def test_search_drops_non_http_urls_from_model_json(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        payload = json.dumps(
            {
                "results": [
                    {"title": "Unsafe", "url": "javascript:alert(1)", "description": ""},
                    {"title": "Safe", "url": "https://example.com/safe", "description": "ok"},
                ]
            }
        )
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(payload),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query", limit=1)

        assert [row["url"] for row in result["data"]["web"]] == ["https://example.com/safe"]

    def test_search_parses_embedded_json_and_removes_duplicate_urls(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        payload = (
            'Preface {"meta": true} then '
            '{"results":['
            '{"title":"First","url":"https://example.com","description":"one"},'
            '{"title":"Duplicate","url":"https://example.com","description":"two"}'
            "]} trailing prose"
        )
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response(payload),
        )

        result = codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert result["data"]["web"] == [
            {
                "title": "First",
                "url": "https://example.com",
                "description": "one",
                "position": 1,
            }
        ]

    def test_search_normalizes_non_finite_timeout(self, monkeypatch):
        from hermes_openai_codex_web_search import provider as codex_provider

        client = _FakeClient()
        monkeypatch.setattr(
            codex_provider,
            "resolve_codex_runtime_credentials",
            lambda: {"api_key": "token", "base_url": "https://chatgpt.com/backend-api/codex"},
        )
        monkeypatch.setattr(
            codex_provider,
            "_load_openai_codex_web_config",
            lambda *args: {"model": "gpt-5.6-luna", "timeout": "nan"},
        )
        monkeypatch.setattr(codex_provider, "_create_codex_client", lambda **kwargs: client)
        monkeypatch.setattr(
            codex_provider,
            "_consume_codex_event_stream",
            lambda stream, **kwargs: _final_response('{"results": []}'),
        )

        codex_provider.OpenAICodexWebSearchProvider().search("query")

        assert client.responses.kwargs["timeout"] == codex_provider.DEFAULT_TIMEOUT
