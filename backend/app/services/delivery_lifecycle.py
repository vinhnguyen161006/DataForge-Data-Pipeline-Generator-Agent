"""Bound startup waiting and observe unexpected delivery-loop exits."""

import asyncio
import logging
from functools import partial

from app.core.readiness import JobDeliveryStatus

logger = logging.getLogger(__name__)


async def wait_for_delivery_startup(
    task: asyncio.Task[None],
    ready: asyncio.Event,
    *,
    timeout_seconds: float,
) -> None:
    """Wait for readiness or task failure without leaving an orphaned event waiter."""
    waiter = asyncio.create_task(ready.wait())
    try:
        done, _ = await asyncio.wait(
            {task, waiter}, timeout=timeout_seconds, return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            raise TimeoutError("Job delivery startup did not finish before the deadline")
        if task.done():
            if task.cancelled():
                raise RuntimeError("Job delivery was cancelled during startup")
            await task
            raise RuntimeError("Job delivery stopped during startup")
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def _delivery_exited(task: asyncio.Task[None], *, status: JobDeliveryStatus) -> None:
    if status.stopping or status.failed:
        return
    status.failed = True
    status.ready = False
    error = None if task.cancelled() else task.exception()
    logger.critical(
        "Job delivery stopped unexpectedly",
        extra={"error_type": type(error).__name__ if error is not None else "UnexpectedExit"},
    )


def observe_delivery(task: asyncio.Task[None], status: JobDeliveryStatus) -> None:
    task.add_done_callback(partial(_delivery_exited, status=status))


async def stop_delivery(task: asyncio.Task[None], status: JobDeliveryStatus) -> None:
    """Record exits racing with shutdown, then join before closing database resources."""
    if task.done():
        _delivery_exited(task, status=status)
    status.stopping = True
    status.ready = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    error = None if task.cancelled() else task.exception()
    if error is not None and not status.failed:
        status.failed = True
        logger.error(
            "Job delivery failed during shutdown",
            extra={"error_type": type(error).__name__},
        )
