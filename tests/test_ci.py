"""Keep compatibility CI independent of unrelated Hermes application extras."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ci_installs_explicit_contract_dependencies_before_no_deps_projects():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["compatibility"]["steps"]
    setup = next(step["run"] for step in steps if step.get("name") == "Create test environment")

    assert "-r plugin/requirements-ci.txt" in setup
    assert "--no-deps -e ./hermes-agent -e ./plugin" in setup
    requirements = (ROOT / "requirements-ci.txt").read_text().lower()
    assert "pyyaml==" in requirements
    assert "openai==" in requirements
    assert "browser-harness==" not in requirements
    assert "pillow==" not in requirements


def test_ci_covers_minimum_current_and_main_without_optional_failures():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["compatibility"]
    matrix = job["strategy"]["matrix"]["include"]

    assert any(row["python"] == "3.11" and row["hermes_ref"] == "v2026.8.19" for row in matrix)
    assert any(
        row["python"] == "3.14" and row["hermes_ref"] == "109fd8161a509db5a00942152ba48882e446e8b0"
        for row in matrix
    )
    assert any(row["python"] == "3.14" and row["hermes_ref"] == "main" for row in matrix)
    assert not job.get("continue-on-error", False)
    assert all(not step.get("continue-on-error", False) for step in job["steps"])


def test_ci_build_uses_uv_without_requiring_system_ensurepip():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["compatibility"]["steps"]
    build = next(step["run"] for step in steps if step.get("name") == "Build distributions")

    assert "--installer uv" in build
