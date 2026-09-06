"""Config-to-request integration through Hermes's real plugin context/registry."""

from types import SimpleNamespace

import pytest
import yaml

from hermes_openai_codex_web_search import provider as codex_provider
from hermes_openai_codex_web_search import register


@pytest.fixture
def registered_search(tmp_path, monkeypatch):
    # No live profile reads/writes, OAuth refresh, or network requests.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from agent import web_search_registry
    from hermes_cli.plugins import PluginContext, PluginManager

    try:
        from hermes_cli.plugins_manifest import PluginManifest
    except ImportError:  # Hermes 0.20.5 kept the manifest in plugins.py.
        from hermes_cli.plugins import PluginManifest

    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return iter(
            [
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {"type": "web_search_call", "status": "completed"},
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"results": []}'}],
                    },
                },
                {"type": "response.completed", "response": {"status": "completed"}},
            ]
        )

    monkeypatch.setattr(codex_provider, "_is_interrupted", lambda: False)
    monkeypatch.setattr(
        codex_provider,
        "resolve_codex_runtime_credentials",
        lambda: {"api_key": "test-token", "base_url": "https://example.invalid/codex"},
    )
    monkeypatch.setattr(
        codex_provider,
        "_create_codex_client",
        lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    manager = PluginManager()
    context = PluginContext(PluginManifest(name="web-openai-codex"), manager)
    register(context)
    provider = web_search_registry.get_provider("openai-codex")
    assert isinstance(provider, codex_provider.OpenAICodexWebSearchProvider)

    def search(config):
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        before = (tmp_path / "config.yaml").read_bytes()
        result = provider.search("configuration propagation")
        assert (tmp_path / "config.yaml").read_bytes() == before
        return result, requests

    yield search
    manager.unload()


@pytest.mark.parametrize("subtree", ["settings", "config"])
def test_plugin_settings_reach_registered_provider_request(registered_search, caplog, subtree):
    entry = {
        "config": {
            "model": "gpt-old-plugin",
            "mode": "live",
            "context_size": "low",
            "timeout": 23,
        }
    }
    entry[subtree] = {
        "model": "gpt-plugin",
        "mode": "cached",
        "context_size": "high",
        "timeout": 42,
    }
    result, requests = registered_search(
        {
            "model": {"provider": "openai-codex", "default": "gpt-main"},
            "web": {
                "openai_codex": {
                    "model": "gpt-legacy",
                    "mode": "live",
                    "context_size": "low",
                    "timeout": 12,
                }
            },
            "plugins": {"entries": {"web-openai-codex": entry}},
        }
    )

    assert result == {"success": True, "data": {"web": []}}
    assert len(requests) == 1
    assert requests[0]["model"] == "gpt-plugin"
    assert requests[0]["timeout"] == 42
    assert requests[0]["tools"] == [
        {
            "type": "web_search",
            "external_web_access": False,
            "search_context_size": "high",
        }
    ]
    assert "Rejected config path" not in caplog.text


@pytest.mark.parametrize(
    "entry, legacy, main_model, expected",
    [
        pytest.param(
            {"settings": {"mode": "cached"}, "config": {"context_size": "high"}},
            {"model": "gpt-legacy", "timeout": 31, "context_size": "low"},
            {"provider": "openai-codex", "default": "gpt-main"},
            ("gpt-legacy", False, "high", 31),
            id="per-key-fallbacks",
        ),
        pytest.param(
            {},
            {"model": "gpt-legacy", "mode": "cached", "context_size": "low", "timeout": 27},
            {"provider": "openai-codex", "default": "gpt-main"},
            ("gpt-legacy", False, "low", 27),
            id="legacy-web-settings",
        ),
        pytest.param(
            {},
            {},
            {"provider": "openai-codex", "default": "gpt-main"},
            ("gpt-main", True, "medium", 90),
            id="main-codex-default",
        ),
        pytest.param(
            {},
            {},
            {"provider": "openai-codex", "model": "gpt-main-alias"},
            ("gpt-main-alias", True, "medium", 90),
            id="main-codex-model-alias",
        ),
        pytest.param(
            {"settings": {"model": ""}, "config": {"model": "gpt-old-plugin"}},
            {"model": "gpt-legacy"},
            {"provider": "openai-codex", "default": "gpt-main"},
            ("gpt-main", True, "medium", 90),
            id="blank-owned-model-uses-main",
        ),
        pytest.param(
            {},
            {},
            {"provider": "anthropic", "default": "claude-not-for-codex"},
            None,
            id="non-codex-main-fails-before-request",
        ),
        pytest.param(
            {"settings": [], "config": "malformed"},
            {},
            {"provider": "openai-codex", "default": "gpt-main"},
            ("gpt-main", True, "medium", 90),
            id="malformed-subtrees",
        ),
    ],
)
def test_registered_provider_fallbacks(
    registered_search, caplog, entry, legacy, main_model, expected
):
    result, requests = registered_search(
        {
            "model": main_model,
            "web": {"openai_codex": legacy},
            "plugins": {
                "entries": {
                    "web-openai-codex": entry,
                    "unrelated-plugin": {
                        "settings": {"model": "gpt-must-not-leak", "timeout": 999}
                    },
                }
            },
        }
    )

    assert "Rejected config path" not in caplog.text
    if expected is None:
        assert result["success"] is False
        assert "needs a model" in result["error"]
        assert requests == []
        return
    model, external_access, context_size, timeout = expected
    assert result == {"success": True, "data": {"web": []}}
    assert len(requests) == 1
    request = requests[0]
    assert request["model"] == model
    assert request["timeout"] == timeout
    assert request["tools"] == [
        {
            "type": "web_search",
            "external_web_access": external_access,
            "search_context_size": context_size,
        }
    ]
