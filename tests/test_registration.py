from hermes_openai_codex_web_search import OpenAICodexWebSearchProvider, register


class FakeContext:
    def __init__(self, settings=None):
        self.providers = []
        self.settings = settings or {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_web_search_provider(self, provider):
        self.providers.append(provider)


def test_registers_web_search_provider():
    ctx = FakeContext({"model": "gpt-5.6-sol"})
    register(ctx)
    assert len(ctx.providers) == 1
    assert isinstance(ctx.providers[0], OpenAICodexWebSearchProvider)
    assert ctx.providers[0].name == "openai-codex"
    assert ctx.providers[0]._config_getter("model", None) == "gpt-5.6-sol"
