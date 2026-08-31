from hermes_openai_codex_web_search import OpenAICodexWebSearchProvider, register


class FakeContext:
    def __init__(self):
        self.providers = []

    def register_web_search_provider(self, provider):
        self.providers.append(provider)


def test_registers_web_search_provider():
    ctx = FakeContext()
    register(ctx)
    assert len(ctx.providers) == 1
    assert isinstance(ctx.providers[0], OpenAICodexWebSearchProvider)
    assert ctx.providers[0].name == "openai-codex"
