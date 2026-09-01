# Hermes OpenAI Codex Web Search

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) backend that routes Hermes's built-in `web_search` tool through OpenAI Codex hosted search. It reuses an existing ChatGPT/Codex OAuth sign-in and registers the backend ID `openai-codex`.

No separate search API key is required. Each search does make a bounded Codex model call and therefore uses your ChatGPT/Codex subscription capacity. The plugin is search-only; configure another backend for `web_extract`.

## Requirements

- Hermes Agent 0.20.5 or newer; CI covers 0.20.5, the latest release, and current `main`
- Python 3.11–3.13, matching Hermes
- An OpenAI Codex sign-in configured with `hermes auth add openai-codex`
- An active OpenAI Codex model, or an explicit plugin model setting

## Install from GitHub

```bash
hermes plugins install bart6114/hermes-openai-codex-web-search --enable
hermes config set web.search_backend openai-codex
```

Restart long-running Hermes or gateway processes after installation or updates so they rediscover the plugin.

## Configure

If the active Hermes model already uses the `openai-codex` provider, the plugin reuses that model. Otherwise configure one in the plugin-owned settings namespace:

```bash
hermes config set plugins.entries.web-openai-codex.settings.model gpt-5.6-sol
```

Optional settings:

```bash
hermes config set plugins.entries.web-openai-codex.settings.mode live
hermes config set plugins.entries.web-openai-codex.settings.context_size medium
hermes config set plugins.entries.web-openai-codex.settings.timeout 90
```

- `mode`: `live` permits external web access; `cached` restricts the hosted tool to cached content.
- `context_size`: `low`, `medium`, or `high`.
- `timeout`: a positive number of seconds; invalid values fall back to 90.

Version 1.x still reads the former `web.openai_codex` settings as a lower-priority compatibility fallback. New configuration should use the plugin-owned path above.

For a split setup, keep extraction on a provider that supports it:

```bash
hermes config set web.search_backend openai-codex
hermes config set web.extract_backend firecrawl
```

## Install as a Python entry-point plugin

Install into the same Python environment as Hermes:

```bash
~/.hermes/bin/uv pip install \
  --python ~/.hermes/hermes-agent/venv/bin/python \
  "git+https://github.com/bart6114/hermes-openai-codex-web-search.git"
hermes plugins enable web-openai-codex
hermes config set web.search_backend openai-codex
```

The package exposes `web-openai-codex` in the `hermes_agent.plugins` entry-point group.

## Verify

```bash
hermes plugins list
hermes tools --summary
hermes chat -q 'Use web_search to find the latest Hermes Agent release.'
```

For source validation:

```bash
hermes plugins doctor . --ci
python -m pytest -q
ruff check .
```

## Security and behavior

- Reads OAuth state from the active profile's `auth.json`; it never copies or logs tokens.
- Refreshes credentials only when an actual search runs; availability checks remain local and side-effect-free.
- Uses the hosted Responses API `web_search` tool with `store: false`.
- Requires a completed hosted-search call and a terminal response event before accepting results.
- Accepts only HTTP(S) result URLs and removes duplicates.
- Returns the standard Hermes web-search envelope.
- Relies on Hermes's Codex OAuth and streaming internals, which are compatibility-tested in CI but may change upstream.

## Origin

This is the standalone distribution requested by Hermes's third-party integration policy. It derives from the OpenAI Codex hosted-search implementation originally developed for `NousResearch/hermes-agent`; both are MIT licensed.
