from pathlib import Path

import pytest

from worker.sandbox import build_env


def test_sandbox_env_has_no_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The sandbox environment excludes both prefixed and generic database credentials."""
    for key in ("DATAFORGE_APP_DATABASE_URL", "DATAFORGE_WAREHOUSE_DSN", "PGPASSWORD"):
        monkeypatch.setenv(key, "fixture-parent-only")
    env = build_env(tmp_path)
    assert not any(key.startswith("DATAFORGE_") for key in env)
    assert "PGPASSWORD" not in env
    with pytest.raises(ValueError, match="Unsupported or invalid"):
        build_env(tmp_path, {"UNLISTED_VALUE": "fixture-parent-only"})


@pytest.mark.skip(reason="TODO")
def test_codegen_guard_rejects_file_access() -> None:
    """TODO: read_csv / attach / copy / paths outside models/silver|mart are violations."""


@pytest.mark.skip(reason="TODO")
def test_tests_generated_only_from_approved_constraints() -> None:
    """TODO: assumptions and profiler observations never appear in _schema.yml."""


@pytest.mark.skip(reason="TODO")
def test_bronze_keeps_leading_zeros() -> None:
    """TODO: a 00123 code survives bronze as VARCHAR."""


@pytest.mark.skip(reason="TODO")
def test_codegen_refused_before_design_approval() -> None:
    """TODO: codegen_node raises when design_approved is false."""
