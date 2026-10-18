import typing
import uuid

import pytest
from pydantic import ValidationError

from app.db.models import JobStatus, RunStatus
from app.graph.interrupts import (
    WAITING_STATUS,
    ClarificationRequest,
    DesignGateReply,
    DesignGateRequest,
    JobOutcome,
    JobWait,
    Pending,
    pending_adapter,
)
from tests.designs import minimal_design


def test_pending_payloads_round_trip_by_kind() -> None:
    payloads = [
        JobWait(job_id=uuid.uuid4(), job_kind="profile"),
        ClarificationRequest(
            questions=[{"topic": "metric", "question": "Is amount gross?", "why": "Ambiguous"}]
        ),
        DesignGateRequest(
            design_version_id=uuid.uuid4(), version=1, design=minimal_design(), edited_by_user=False
        ),
    ]
    for payload in payloads:
        dumped = payload.model_dump(mode="json")
        assert pending_adapter.validate_python(dumped) == payload


def test_every_pending_kind_maps_to_a_waiting_status() -> None:
    union = typing.get_args(typing.get_args(Pending)[0])
    kinds = {model.model_fields["kind"].default for model in union}
    assert kinds == set(WAITING_STATUS)
    assert all(status.value.startswith("waiting_") for status in WAITING_STATUS.values())
    assert RunStatus.WAITING_DESIGN_APPROVAL in WAITING_STATUS.values()


def test_clarification_request_needs_a_question() -> None:
    with pytest.raises(ValidationError):
        ClarificationRequest(questions=[])


def test_job_outcome_only_accepts_terminal_status() -> None:
    with pytest.raises(ValidationError):
        JobOutcome(job_id=uuid.uuid4(), status=JobStatus.RUNNING)
    assert JobOutcome(job_id=uuid.uuid4(), status=JobStatus.FAILED, error="boom").error == "boom"


def test_return_requires_a_comment() -> None:
    with pytest.raises(ValidationError, match="requires a comment"):
        DesignGateReply(user_id=uuid.uuid4(), decision="return", comment="  ")


def test_return_cannot_carry_edits() -> None:
    with pytest.raises(ValidationError, match="cannot carry edits"):
        DesignGateReply(
            user_id=uuid.uuid4(),
            decision="return",
            edited_design=minimal_design(),
            comment="Wrong grain",
        )


def test_approve_may_carry_edits_without_comment() -> None:
    reply = DesignGateReply(
        user_id=uuid.uuid4(), decision="approve", edited_design=minimal_design()
    )
    assert reply.edited_design is not None
