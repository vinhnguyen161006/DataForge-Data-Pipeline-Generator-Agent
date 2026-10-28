"""Isolation guards and fixed business contracts for the Compose recovery application."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.agents.schemas import validate_modeler_output
from app.core.config import get_api_settings
from scripts import recovery_app
from tests.designs import minimal_profile

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def drill_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key, value in {
        "DATAFORGE_RECOVERY_DRILL": "true",
        "DATAFORGE_APP_DATABASE_URL": "postgresql+asyncpg://dataforge:dataforge@localhost/dataforge_recovery",
        "DATAFORGE_CHECKPOINT_DATABASE_URL": "postgresql://dataforge:dataforge@localhost/dataforge_recovery",
        "DATAFORGE_STORAGE_ROOT": str(tmp_path / "recovery-drill"),
        "DATAFORGE_JOB_DELIVERY_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    get_api_settings.cache_clear()
    yield
    get_api_settings.cache_clear()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("DATAFORGE_RECOVERY_DRILL", "false", "explicit drill"),
        (
            "DATAFORGE_APP_DATABASE_URL",
            "postgresql+asyncpg://dataforge:dataforge@localhost/dataforge_app",
            "dedicated recovery database",
        ),
        (
            "DATAFORGE_CHECKPOINT_DATABASE_URL",
            "postgresql://dataforge:dataforge@localhost/dataforge_app",
            "dedicated recovery database",
        ),
        ("DATAFORGE_STORAGE_ROOT", "/data", "dedicated drill storage"),
        ("DATAFORGE_JOB_DELIVERY_ENABLED", "false", "startup recovery"),
    ],
)
def test_recovery_application_refuses_non_drill_resources(
    drill_settings: None,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(variable, value)
    get_api_settings.cache_clear()
    with pytest.raises(RuntimeError, match=message):
        recovery_app.create_app()


async def test_fixed_modeler_accepts_fixture_profile_and_revises_after_feedback() -> None:
    source = minimal_profile().tables[0]
    profile = minimal_profile().model_copy(
        update={
            "tables": [
                source.model_copy(update={"name": "customers", "source_file": "customers.csv"}),
                source.model_copy(update={"name": "orders", "source_file": "orders.csv"}),
            ]
        }
    )
    output = await recovery_app.propose_design(
        request_text="Count orders",
        profile=profile,
        answers=[],
        returned_design=None,
        reviewer_feedback=None,
    )
    assert validate_modeler_output(output) == []
    revised = await recovery_app.propose_design(
        request_text="Count orders",
        profile=profile,
        answers=[],
        returned_design=output.design,
        reviewer_feedback="Explain the declared order grain",
    )
    assert validate_modeler_output(revised) == []
    assert revised != output


async def test_fixed_modeler_rejects_unrelated_profile() -> None:
    with pytest.raises(ValueError, match="synthetic fixture"):
        await recovery_app.propose_design(
            request_text="Count registrations",
            profile=minimal_profile(),
            answers=[],
            returned_design=None,
            reviewer_feedback=None,
        )
