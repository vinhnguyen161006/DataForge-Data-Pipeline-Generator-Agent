from enum import StrEnum
from typing import cast

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
    if outcome.run_error is not None:
        return Judgement(decision=RewriteDecision.RUN_ERROR, outcome=outcome)

    if outcome.timed_out:
        return Judgement(decision=RewriteDecision.TIMEOUT, outcome=outcome)

    if outcome.equivalence is None or not outcome.equivalence.equivalent:
        return Judgement(decision=RewriteDecision.WRONG_RESULT, outcome=outcome)

    if outcome.speed is None or not outcome.speed.faster:
        return Judgement(decision=RewriteDecision.NOT_FASTER, outcome=outcome)

    return Judgement(decision=RewriteDecision.KEPT, outcome=outcome)


def select_best(original_sql: str, judgements: list[Judgement]) -> str:
    valid_judgements = [
        j for j in judgements if j.decision == RewriteDecision.KEPT and j.outcome.speed is not None
    ]

    if not valid_judgements:
        return original_sql

    best_judgement = min(
        valid_judgements,
        key=lambda j: cast("SpeedVerdict", j.outcome.speed).candidate_median,
    )
    return best_judgement.outcome.candidate_sql
