import profile

from pydantic import BaseModel

from app.agents.llm import StructuredLLM
from app.agents.schemas import OptimizerOutput
from backend.app.profiler.schemas import DataProfile


class ModelPerf(BaseModel):
    model_name: str
    compiled_sql: str
    median_seconds: float
    rows_scanned: int | None = None
    plan: str | None = None


async def propose_rewrites(
    llm: StructuredLLM, *, slowest: list[ModelPerf], max_candidates: int
) -> OptimizerOutput:
    """TODO: ask the LLM for at most max_candidates rewrites; judging happens in
    optimizer/judge.py.
    """
    if not isinstance(profile, DataProfile):
        raise TypeError("profile must be a DataProfile instance.")

    raise NotImplementedError
