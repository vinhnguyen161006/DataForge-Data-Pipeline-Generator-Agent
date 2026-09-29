from enum import StrEnum

from pydantic import BaseModel

from app.compare.benchmark import SpeedVerdict
from app.compare.multiset import ComparisonResult


class RewriteDecision(StrEnum):
    KEPT = "kept"
    WRONG_RESULT = "wrong_result"
    RUN_ERROR = "run_error"
    NOT_FASTER = "not_faster"
    TIMEOUT = "timeout"


class CandidateOutcome(BaseModel):
    model_name: str
    candidate_sql: str
    run_error: str | None = None
    timed_out: bool = False
    equivalence: ComparisonResult | None = None
    speed: SpeedVerdict | None = None


class Judgement(BaseModel):
    decision: RewriteDecision
    outcome: CandidateOutcome


def judge(outcome: CandidateOutcome) -> Judgement:
    """TODO: deterministic verdict, checked in order: run error, timeout, wrong result, not faster.

    Never call an LLM here (FR-12).
    """
    raise NotImplementedError


def select_best(original_sql: str, judgements: list[Judgement]) -> str:
    """TODO: fastest kept rewrite, or the original SQL when every candidate was rejected."""
    raise NotImplementedError
