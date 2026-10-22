"""Business validation required before accepting a gate-1 decision."""

import hashlib
import math

import pytest

from app.agents.schemas import (
    ClarificationQuestion,
    ModelerOutput,
    validate_design,
    validate_modeler_output,
)
from app.versioning import canonical_json_hash
from tests.designs import minimal_design


def test_complete_design_and_modeler_output_are_valid() -> None:
    design = minimal_design()
    assert validate_design(design) == []
    assert validate_modeler_output(ModelerOutput(design=design)) == []


def test_modeler_must_choose_questions_or_a_design() -> None:
    question = ClarificationQuestion(topic="grain", question="What is a row?", why="Ambiguous")
    assert validate_modeler_output(ModelerOutput()) != []
    assert (
        validate_modeler_output(ModelerOutput(design=minimal_design(), questions=[question])) != []
    )
    assert validate_modeler_output(ModelerOutput(questions=[question])) == []


@pytest.mark.parametrize("issue", ["blank-question", "blank-reason", "duplicate"])
def test_clarification_questions_must_be_answerable_and_distinct(issue: str) -> None:
    question = ClarificationQuestion(topic="grain", question="What is a row?", why="Ambiguous")
    questions = [question]
    if issue == "blank-question":
        question.question = " "
    elif issue == "blank-reason":
        question.why = " "
    else:
        questions.append(question.model_copy())
    assert validate_modeler_output(ModelerOutput(questions=questions)) != []


def test_approval_rejects_unresolved_business_questions() -> None:
    design = minimal_design()
    design.metrics[0].open_questions = ["Should refunds be deducted?"]
    assert validate_design(design) != []


def test_hash_is_stable_across_key_order_and_model_or_json_input() -> None:
    assert canonical_json_hash({"b": 2, "a": 1}) == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    design = minimal_design()
    assert canonical_json_hash(design) == canonical_json_hash(design.model_dump(mode="json"))


def test_hash_changes_when_business_meaning_changes() -> None:
    original = minimal_design()
    edited = original.model_copy(deep=True)
    edited.metrics[0].definition = "Registrations excluding withdrawals"
    assert canonical_json_hash(original) != canonical_json_hash(edited)


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_hash_rejects_non_json_numbers(number: float) -> None:
    with pytest.raises(ValueError, match="Out of range"):
        canonical_json_hash({"number": number})
