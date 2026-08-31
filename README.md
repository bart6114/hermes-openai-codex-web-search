# Hermes OpenAI Codex Web Search

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) web-search backend that uses OpenAI Codex hosted search through your existing ChatGPT/Codex OAuth sign-in. It adds the backend id `openai-codex` to Hermes' built-in `web_search` tool.

No separate search API key is required. The plugin is search-only; configure another backend for `web_extract`.

## Requirements

- Hermes Agent 0.20.5 or newer
- An OpenAI Codex / ChatGPT sign-in configured through `hermes auth`
- An OpenAI Codex model selected in Hermes, or an explicit model under `web.openai_codex.model`

## Install from GitHub (recommended)

```bash
hermes plugins install bart6114/hermes-openai-codex-web-search
hermes plugins enable web-openai-codex
hermes config set web.search_backend openai-codex
```

If the installer already enabled the plugin, the explicit `enable` command is harmless. Restart long-running Hermes processes after installation so they discover the new plugin.

## Install as a Python entry-point plugin

Install the package into the same Python environment as Hermes:

```bash
~/.hermes/bin/uv pip install \
  --python ~/.hermes/hermes-agent/venv/bin/python \
  "git+https://github.com/bart6114/hermes-openai-codex-web-search.git"
hermes plugins enable web-openai-codex
hermes config set web.search_backend openai-codex
```

The wheel exposes the `web-openai-codex` entry point in the `hermes_agent.plugins` group.

## Configure

When your main Hermes model already uses the `openai-codex` provider, the plugin reuses that model automatically. Otherwise set one explicitly:

```bash
hermes config set web.openai_codex.model gpt-5.6-sol
```

Optional settings:

```bash
hermes config set web.openai_codex.mode live
hermes config set web.openai_codex.context_size medium
hermes config set web.openai_codex.timeout 90
```

- `mode`: `live` (external web access) or `cached`
- `context_size`: `low`, `medium`, or `high`
- `timeout`: positive seconds

For a split setup, keep extraction on a provider that supports it:

```bash
hermes config set web.search_backend openai-codex
hermes config set web.extract_backend firecrawl
```

## Verify

```bash
hermes plugins list
hermes tools --summary
hermes chat -q 'Use web_search to find the latest Hermes Agent release.'
```

Plugin source validation for contributors:

```bash
hermes plugins doctor . --ci
```

## Security and behavior

- Reads OAuth state from the active profile's `auth.json`; it does not copy or log tokens.
- Refreshes Codex credentials only when a real search runs.
- Uses the hosted Responses API `web_search` tool with `store: false`.
- Rejects responses that did not actually invoke and complete hosted search.
- Accepts only HTTP(S) result URLs.
- Returns the standard Hermes web-search envelope.

## Origin

Extracted from the OpenAI Codex hosted-search implementation originally developed for NousResearch/hermes-agent. The original source and this standalone distribution are MIT licensed.
