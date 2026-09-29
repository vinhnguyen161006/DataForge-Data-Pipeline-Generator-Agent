import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import CardSpec, DataDesign
from app.metabase.client import MetabaseClient


def card_spec(
    card: CardSpec, design: DataDesign, database_id: int, serving_schema: str
) -> dict[str, Any]:
    """TODO: native-SQL card payload; display is scalar (kpi), line or bar."""
    raise NotImplementedError


async def upsert_card(
    session: AsyncSession,
    client: MetabaseClient,
    *,
    project_id: uuid.UUID,
    card: CardSpec,
    spec: dict[str, Any],
) -> int:
    """TODO: look up MetabaseObject by (project, "card", card.key); update if present, else create.

    Store the id before returning so a retry never creates a duplicate card.
    """
    raise NotImplementedError


async def build_dashboard(
    session: AsyncSession,
    client: MetabaseClient,
    *,
    project_id: uuid.UUID,
    project_name: str,
    design: DataDesign,
    database_id: int,
    serving_schema: str,
) -> str:
    """TODO: sync schema -> upsert cards -> verify each card query -> upsert dashboard -> link
    (FR-15).

    Re-runnable on its own without reloading data.
    """
    raise NotImplementedError
