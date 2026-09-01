from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_manifest_metadata_stay_in_sync():
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))

    assert package["project"]["version"] == manifest["version"]
    assert manifest["name"] == "web-openai-codex"
    assert manifest["kind"] == "backend"
    assert manifest["manifest_version"] == 2
    assert manifest["api_version"] == 1
    assert manifest["provides_web_providers"] == ["openai-codex"]
    assert set(manifest["config_schema"]) == {
        "context_size",
        "mode",
        "model",
        "timeout",
    }


def test_python_entry_point_targets_register_function():
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert package["project"]["entry-points"]["hermes_agent.plugins"] == {
        "web-openai-codex": "hermes_openai_codex_web_search"
    }
