# Hermes OpenAI Codex Web Search

A standalone [Hermes Agent](https://github.com/NousResearch/hermes-agent) backend that routes Hermes's built-in `web_search` tool through OpenAI Codex hosted search. It reuses an existing ChatGPT/Codex OAuth sign-in and registers the backend ID `openai-codex`.

No separate search API key is required. Each search does make a bounded Codex model call and therefore uses your ChatGPT/Codex subscription capacity. The plugin is search-only; configure another backend for `web_extract`.

## Requirements

- Hermes Agent 0.20.5 or newer; CI covers the minimum, legacy releases, the pinned current installed baseline (0.23.0), and current `main`
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

For affected installations, keep the plugin as a dependency-free native directory plugin. For a **clean Git checkout**, sparse checkout can omit only the root packaging metadata without recording a tracked deletion:

```bash
# Set this to the affected profile's actual plugin directory.
plugin_dir="${HERMES_HOME:-$HOME/.hermes}/plugins/web-openai-codex"
git -C "$plugin_dir" status --short   # back up/reconcile local changes first
# Run only once the tracked working tree is clean:
git -C "$plugin_dir" sparse-checkout set --no-cone '/*' '!/pyproject.toml'
git -C "$plugin_dir" status --short   # should remain clean
```

The `plugin.yaml`, root `__init__.py`, and provider package remain present. Git retains the exclusion across ordinary pulls, including changes to `pyproject.toml`; a reinstall/reclone or a tool that disables sparse checkout may restore it. To undo the exclusion, run `git -C "$plugin_dir" sparse-checkout disable`.

The previous rename workaround (`pyproject.toml` → `pyproject.distribution.toml`) still works at runtime, but leaves a tracked deletion and can interfere with updates. If migrating, back up the renamed file and any other changes, reconcile with upstream, and restore the tracked metadata before applying sparse checkout. Do not discard local changes blindly.

After changing the layout, re-enable `web-openai-codex` in each affected profile with `hermes --profile <name> plugins enable web-openai-codex`, run Plugin Doctor, and restart the gateway. The plugin uses libraries already supplied by Hermes; do not pip-install into the managed runtime. Recheck the layout after plugin updates. This is a workaround for Hermes workspace staging, not a change to the published distribution's packaging.

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

## Python entry-point packaging

The distribution exposes `web-openai-codex` in the `hermes_agent.plugins` entry-point group for independently managed Python environments. For normal Hermes installations, use `hermes plugins install` above instead of raw pip/uv commands or a hard-coded `venv/bin/python` path. Current Hermes owns its Python runtime through PM; the old source-install venv may no longer be the interpreter Hermes actually runs.

See the official [installation guide](https://hermes-agent.nousresearch.com/docs/getting-started/installation) and [package-management reference](https://hermes-agent.nousresearch.com/docs/reference/package-management). The supported source/developer workflow is activation/PM; an independent full-core test environment can be built with `python -m pm.build_env --source . --out .venv --group dev --group test` from a prepared Hermes checkout (the output must not already exist). Never add this plugin's test tools to a production managed generation.

## Verify

```bash
hermes plugins list
hermes tools --summary
hermes chat -q 'Use web_search to find the latest Hermes Agent release.'
```

For installed-plugin validation, run `hermes plugins doctor . --ci` from the plugin checkout.

### Compatibility CI and local tests

CI tests Python 3.11/minimum 0.20.5, Python 3.12–3.13/legacy 0.21.0, and Python 3.14 against both the current installed 0.23.0 baseline (`109fd8161a509db5a00942152ba48882e446e8b0`) and moving `main`. Update the pinned current baseline deliberately when upgrading; the weekly scheduled main job detects upstream contract drift. Every matrix job is required: no tests are skipped and failures are not allowed.

These are **plugin contract environments, not full Hermes application installs**. CI resolves the explicit SDK/config/CLI/test dependencies in `requirements-ci.txt`, then installs the real Hermes and plugin source projects with `--no-deps`. This keeps unrelated browser/image/desktop dependencies out of this plugin's checks; for example, upstream's `browser-harness==0.1.13` requires `Pillow==12.3.0` while core pins `Pillow==13.0.0`. It does not override those pins or claim that a complete upstream installation is healthy. If an exercised Hermes import gains a dependency, add it explicitly rather than stubbing the module or skipping its test.

To reproduce against a separately checked-out Hermes revision, from this plugin checkout:

```bash
# Keep the test home outside the plugin checkout (Doctor stages a copy).
export HERMES_HOME=/path/outside/plugin/checkout/hermes-test-home
export TZ=UTC LANG=C.UTF-8
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements-ci.txt
uv pip install --python .venv/bin/python --no-deps -e /path/to/hermes-agent -e .
.venv/bin/python -m pytest tests -q
.venv/bin/python -m hermes_cli.main plugins doctor . --ci
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m build --installer uv
```

Run these only in a disposable caller-owned venv, never the runtime printed by `hermes --print-runtime-command`. The suite includes a fresh Git installation into a temporary `HERMES_HOME`, followed by Plugin Doctor. It also exercises settings through the real `PluginContext`, the real Codex stream consumer, and actual SDK client construction/auth imports without network calls or live credentials. Thus the `--no-deps` boundary does not replace Hermes implementations with mocks; hosted search itself is not a credential-free CI test.

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
