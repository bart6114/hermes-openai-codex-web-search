"""Contracts against Hermes's real Responses stream consumer, no live auth."""

from types import SimpleNamespace

import pytest

from hermes_openai_codex_web_search import provider as codex_provider


@pytest.fixture
def streamed_search(monkeypatch):
    monkeypatch.setattr(codex_provider, "_is_interrupted", lambda: False)
    monkeypatch.setattr(
        codex_provider,
        "resolve_codex_runtime_credentials",
        lambda: {"api_key": "test-token", "base_url": "https://example.invalid/codex"},
    )
    monkeypatch.setattr(
        codex_provider,
        "_load_openai_codex_web_config",
        lambda *args: {"model": "gpt-test"},
    )
    items = [
        {"type": "web_search_call", "status": "completed"},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": '{"results":[{"url":"https://example.com/source","title":"Source"}]}',
                }
            ],
        },
    ]

    def search(terminal):
        events = [
            {"type": "response.output_item.done", "output_index": index, "item": item}
            for index, item in enumerate(items)
        ]
        if terminal is not None:
            events.append(terminal)
        monkeypatch.setattr(
            codex_provider,
            "_create_codex_client",
            lambda **kwargs: SimpleNamespace(
                responses=SimpleNamespace(create=lambda **kwargs: iter(events))
            ),
        )
        return codex_provider.OpenAICodexWebSearchProvider().search("query")

    return search


@pytest.mark.parametrize("status", ["failed", "incomplete"])
@pytest.mark.parametrize("response", [{}, {"status": "completed"}])
def test_terminal_failure_type_rejects_grounded_partial_output(streamed_search, status, response):
    result = streamed_search({"type": f"response.{status}", "response": response})

    assert result["success"] is False
    assert f"ended {status}" in result["error"]


@pytest.mark.parametrize(
    "terminal, succeeds",
    [
        (None, False),
        ({"type": "response.completed", "response": {"status": "completed"}}, True),
    ],
)
def test_grounded_stream_requires_actual_completion_frame(streamed_search, terminal, succeeds):
    result = streamed_search(terminal)

    assert result["success"] is succeeds
    if succeeds:
        assert result["data"]["web"][0]["url"] == "https://example.com/source"
    else:
        assert "without a terminal event" in result["error"]
