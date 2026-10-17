from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import modeler
from app.agents.llm import StructuredLLM
from app.agents.schemas import DataDesign, ModelerOutput
from app.profiler.schemas import DataProfile
from app.versioning import canonical_json_hash


class DesignProposer(Protocol):
    async def __call__(
        self,
        *,
        request_text: str,
        profile: DataProfile,
        answers: list[dict[str, str]],
        returned_design: DataDesign | None,
        reviewer_feedback: str | None,
    ) -> ModelerOutput: ...


DesignHasher = Callable[[Any], str]


@dataclass(frozen=True)
class GraphContext:
    """Run-scoped dependencies handed to nodes through LangGraph's Runtime.

    Never checkpointed, so it is passed again on every invoke and resume.
    """

    sessionmaker: async_sessionmaker[AsyncSession]
    propose_design: DesignProposer
    hash_design: DesignHasher = canonical_json_hash


def make_graph_context(
    sessionmaker: async_sessionmaker[AsyncSession], llm: StructuredLLM
) -> GraphContext:
    async def propose_design(
        *,
        request_text: str,
        profile: DataProfile,
        answers: list[dict[str, str]],
        returned_design: DataDesign | None,
        reviewer_feedback: str | None,
    ) -> ModelerOutput:
        return await modeler.propose_design(
            llm,
            request_text=request_text,
            profile=profile,
            answers=answers,
            returned_design=returned_design,
            reviewer_feedback=reviewer_feedback,
        )

    return GraphContext(sessionmaker=sessionmaker, propose_design=propose_design)
