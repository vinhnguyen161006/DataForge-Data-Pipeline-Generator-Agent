import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def schema_fingerprint(session: AsyncSession, batch_id: uuid.UUID) -> str:
    """TODO: hash sorted (filename, column names, sniffed types) of every file in the batch."""
    raise NotImplementedError


async def check_schema_unchanged(
    session: AsyncSession, batch_id: uuid.UUID, approved_fingerprint: str
) -> None:
    """TODO: raise when a new batch changes schema; stop and ask the Engineer (FR-17)."""
    raise NotImplementedError


async def mark_batch_ready(
    session: AsyncSession, batch_id: uuid.UUID, required_files: list[str]
) -> None:
    """TODO: set READY and write _READY only when every required file is present and confirmed."""
    raise NotImplementedError
