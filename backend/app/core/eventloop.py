import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def run(main: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion on a selector event loop.

    Psycopg async cannot use the Proactor loop that asyncio picks by default on Windows; the
    selector loop is already the default on Linux, so behaviour there is unchanged.
    """
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(main)
