import pytest

from app.agents.schemas import GeneratedFile
from app.codegen.guard import check_generated_files


@pytest.mark.skip(reason="TODO")
def test_sandbox_env_has_no_credentials() -> None:
    """TODO: build_env() drops DATAFORGE_* and refuses DSN/password keys."""


@pytest.mark.skip(reason="TODO")
def test_codegen_guard_rejects_file_access() -> None:
    bad_file = GeneratedFile(
        path="models/silver/bad.sql", content="SELECT * FROM read_csv('secret.csv');"
    )
    violations = check_generated_files([bad_file])
    assert len(violations) > 0
    assert any("read_csv" in v for v in violations)


def test_codegen_guard_rejects_bad_paths() -> None:
    bad_path = GeneratedFile(path="../models/mart/hacked.sql", content="SELECT 1")
    violations = check_generated_files([bad_path])
    assert len(violations) > 0
    assert any("relative traversal" in v for v in violations)


def test_codegen_guard_accepts_valid_code() -> None:
    good_file = GeneratedFile(
        path="models/mart/good.sql",
        content="{{ config(materialized='table') }}\nSELECT * FROM {{ ref('silver_users') }}",
    )
    violations = check_generated_files([good_file])
    assert len(violations) == 0


@pytest.mark.skip(reason="TODO")
def test_tests_generated_only_from_approved_constraints() -> None:
    """TODO: assumptions and profiler observations never appear in _schema.yml."""


@pytest.mark.skip(reason="TODO")
def test_bronze_keeps_leading_zeros() -> None:
    """TODO: a 00123 code survives bronze as VARCHAR."""


@pytest.mark.skip(reason="TODO")
def test_codegen_refused_before_design_approval() -> None:
    """TODO: codegen_node raises when design_approved is false."""
