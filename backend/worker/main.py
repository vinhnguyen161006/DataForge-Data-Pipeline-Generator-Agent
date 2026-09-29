import asyncio

from app.core.config import WorkerSettings


async def run_forever(settings: WorkerSettings) -> None:
    """TODO: sandbox worker loop on queue "sandbox".

    Reclaim expired leases, claim a job, heartbeat while running, dispatch by
    kind to worker/runner.py, then complete or fail the job. This process must
    never hold warehouse credentials.
    """
    raise NotImplementedError


def main() -> None:
    asyncio.run(run_forever(WorkerSettings()))


if __name__ == "__main__":
    main()
