# Hermes OpenAI Codex Web Search

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) backend that routes Hermes's built-in `web_search` tool through OpenAI Codex hosted search. It reuses an existing ChatGPT/Codex OAuth sign-in and registers the backend ID `openai-codex`.

No separate search API key is required. Each search does make a bounded Codex model call and therefore uses your ChatGPT/Codex subscription capacity. The plugin is search-only; configure another backend for `web_extract`.

## Requirements

- Hermes Agent 0.20.5 or newer; CI covers 0.20.5, the latest release, and current `main`
- Python 3.11–3.14; current Hermes `main` runs on Python 3.14
- An OpenAI Codex sign-in configured with `hermes auth add openai-codex`
- An active OpenAI Codex model, or an explicit plugin model setting

## Install from GitHub

```bash
hermes plugins install bart6114/hermes-openai-codex-web-search --enable
hermes config set web.search_backend openai-codex
```

Restart long-running Hermes or gateway processes after installation or updates so they rediscover the plugin.

### Multiple profiles on managed-runtime Hermes

Current Hermes can stage profile-local Python packages into one uv workspace. Installing this same packaged plugin in several profiles can produce a duplicate-package-name error and cause Hermes to disable those copies.

For affected installations, keep the plugin as a dependency-free native directory plugin: rename `pyproject.toml` to `pyproject.distribution.toml` inside each installed `plugins/web-openai-codex` directory. Keep `plugin.yaml`, the root `__init__.py`, and the `hermes_openai_codex_web_search` package unchanged. Then re-enable `web-openai-codex` in each affected profile with `hermes --profile <name> plugins enable web-openai-codex`, run Plugin Doctor, and restart the gateway. The plugin uses libraries already supplied by Hermes; no package installation into the managed environment is needed.

This is a workaround for Hermes workspace staging, not a change to the distribution's packaging. Recheck the installed layout after plugin updates, which may restore `pyproject.toml`.

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

Version 1.x still reads the former `web.openai_codex` settings as a lower-priority compatibility fallback. Plugin `settings` take precedence over the older `plugins.entries.web-openai-codex.config` subtree, which in turn takes precedence over `web.openai_codex`. If no non-empty model is selected, only a main model using the `openai-codex` provider is inherited. New configuration should use the plugin-owned path above.

The documented `settings.model` key remains supported. Hermes reserves the relative key `model` in `PluginContext.get_config`, so this plugin reads its own model leaf from the active profile's read-only configuration instead. It does not rewrite configuration or access another plugin's settings.

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

The test suite includes a fresh Git installation into a temporary `HERMES_HOME`, followed by runtime validation. This catches installer compatibility failures that Plugin Doctor alone does not detect. Integration tests also exercise settings through the real Hermes `PluginContext`.

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
