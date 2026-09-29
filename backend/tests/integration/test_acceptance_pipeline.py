import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="TODO")
def test_same_batch_twice_does_not_duplicate_rows(database_url: str) -> None:
    """TODO: running the pipeline twice on one batch yields identical mart row counts."""


@pytest.mark.skip(reason="TODO")
def test_exported_zip_rebuilds_on_clean_machine(database_url: str) -> None:
    """TODO: unzip into an empty dir, provide CSVs, rebuild mart without platform API calls."""


@pytest.mark.skip(reason="TODO")
async def test_migrations_round_trip(database_url: str) -> None:
    """TODO: alembic upgrade head, downgrade base, upgrade head on an empty database."""
