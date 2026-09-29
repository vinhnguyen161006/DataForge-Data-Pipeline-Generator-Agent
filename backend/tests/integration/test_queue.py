import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="TODO")
async def test_two_workers_never_claim_the_same_job(database_url: str) -> None:
    """TODO: two sessions call claim_next concurrently on one queued job; exactly one wins."""


@pytest.mark.skip(reason="TODO")
async def test_serial_key_blocks_parallel_runs_of_one_pipeline(database_url: str) -> None:
    """TODO: with one running job for a serial_key, a second job with that key stays queued."""


@pytest.mark.skip(reason="TODO")
async def test_expired_lease_is_reclaimed(database_url: str) -> None:
    """TODO: a running job with an expired lease is requeued, or failed when out of attempts."""
