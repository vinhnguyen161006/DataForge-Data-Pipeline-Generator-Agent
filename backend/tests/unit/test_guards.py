import pytest


@pytest.mark.skip(reason="TODO")
def test_sandbox_env_has_no_credentials() -> None:
    """TODO: build_env() drops DATAFORGE_* and refuses DSN/password keys."""


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
