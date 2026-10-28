import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import codegen, modeler
from app.agents.llm import StructuredLLM
from app.agents.schemas import (
    CodegenOutput,
    DataDesign,
    GeneratedFile,
    ModelerOutput,
    validate_design,
    validate_modeler_output,
)
from app.codegen.guard import check_generated_files
from app.codegen.project import AssembledProject
from app.core.config import OptimizerBudget
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


class CodeGenerator(Protocol):
    async def __call__(
        self,
        *,
        design: DataDesign,
        profile: DataProfile,
        previous_files: dict[str, str] | None,
        failure_report: str | None,
        reviewer_feedback: str | None,
    ) -> CodegenOutput: ...


class CodeAssembler(Protocol):
    async def __call__(
        self,
        *,
        project_id: uuid.UUID,
        run_id: uuid.UUID,
        version: int,
        design: DataDesign,
        files: list[GeneratedFile],
    ) -> AssembledProject: ...


JsonHasher = Callable[[Any], str]
DesignChecker = Callable[[DataDesign], list[str]]
ModelerOutputChecker = Callable[[ModelerOutput], list[str]]
GeneratedFilesChecker = Callable[[list[GeneratedFile]], list[str]]


async def no_code_generator(**_: Any) -> CodegenOutput:
    raise RuntimeError("No code generator is configured for this graph context")


async def no_code_assembler(**_: Any) -> AssembledProject:
    raise RuntimeError("No code assembler is configured for this graph context")


def default_max_fix_attempts() -> int:
    return OptimizerBudget().max_fix_attempts


@dataclass(frozen=True)
class GraphContext:
    """Run-scoped dependencies handed to nodes through LangGraph's Runtime.

    Never checkpointed, so it is passed again on every invoke and resume.
    """

    sessionmaker: async_sessionmaker[AsyncSession]
    propose_design: DesignProposer
    hash_design: JsonHasher = canonical_json_hash
    check_design: DesignChecker = validate_design
    check_modeler_output: ModelerOutputChecker = validate_modeler_output
    generate_code: CodeGenerator = no_code_generator
    assemble_code: CodeAssembler = no_code_assembler
    check_generated_files: GeneratedFilesChecker = check_generated_files
    hash_report: JsonHasher = canonical_json_hash
    max_fix_attempts: int = field(default_factory=default_max_fix_attempts)


def make_graph_context(
    sessionmaker: async_sessionmaker[AsyncSession], llm: StructuredLLM, budget: OptimizerBudget
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

    async def generate_code(
        *,
        design: DataDesign,
        profile: DataProfile,
        previous_files: dict[str, str] | None,
        failure_report: str | None,
        reviewer_feedback: str | None,
    ) -> CodegenOutput:
        return await codegen.generate_models(
            llm,
            design=design,
            profile=profile,
            examples=[],
            previous_files=previous_files,
            failure_report=failure_report,
            reviewer_feedback=reviewer_feedback,
        )

    return GraphContext(
        sessionmaker=sessionmaker,
        propose_design=propose_design,
        generate_code=generate_code,
        max_fix_attempts=budget.max_fix_attempts,
    )
