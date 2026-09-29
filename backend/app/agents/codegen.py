from app.agents.llm import StructuredLLM
from app.agents.schemas import CodegenOutput, DataDesign
from app.profiler.schemas import DataProfile


async def generate_models(
    llm: StructuredLLM,
    *,
    design: DataDesign,
    profile: DataProfile,
    examples: list[str],
    previous_files: dict[str, str] | None = None,
    failure_report: str | None = None,
    reviewer_feedback: str | None = None,
) -> CodegenOutput:
    """TODO: generate or repair silver/mart models from an approved design (FR-07).

    Include retrieved examples, current files, sandbox failures and gate-2 feedback.
    """
    raise NotImplementedError
