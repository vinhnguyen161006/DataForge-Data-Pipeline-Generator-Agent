from app.agents.llm import StructuredLLM
from app.agents.schemas import DataDesign, ModelerOutput
from app.profiler.schemas import DataProfile


async def propose_design(
    llm: StructuredLLM,
    *,
    request_text: str,
    profile: DataProfile,
    answers: list[dict[str, str]],
    returned_design: DataDesign | None = None,
    reviewer_feedback: str | None = None,
) -> ModelerOutput:
    """TODO: build the prompt from prompts/modeler.md and return a design or questions (FR-04,
    FR-05).

    Accepts only a DataProfile, so raw rows can never reach the LLM.
    """
    raise NotImplementedError
