"""Exercise fresh installation, not just the runtime's permissive parser."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_git_install_enables_plugin_in_isolated_home(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    # Commit the working tree, including uncommitted fixes, into a local fixture.
    for args in (
        ["init"],
        ["add", "."],
        [
            "-c",
            "user.name=Plugin Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "Plugin installation fixture",
        ],
    ):
        subprocess.run(["git", *args], cwd=source, check=True, capture_output=True, text=True)

    home = tmp_path / "hermes-home"
    home.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "PYTHONPATH", "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    env.update(HOME=str(tmp_path), HERMES_HOME=str(home), TZ="UTC", LANG="C.UTF-8")
    command = [sys.executable, "-m", "hermes_cli.main"]
    install = subprocess.run(
        [*command, "plugins", "install", source.as_uri(), "--enable"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    installed = home / "plugins" / "web-openai-codex"
    assert yaml.safe_load((installed / "plugin.yaml").read_text()) == yaml.safe_load(
        (ROOT / "plugin.yaml").read_text()
    )
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert "web-openai-codex" in config["plugins"]["enabled"]
    doctor = subprocess.run(
        [*command, "plugins", "doctor", str(installed), "--ci"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
