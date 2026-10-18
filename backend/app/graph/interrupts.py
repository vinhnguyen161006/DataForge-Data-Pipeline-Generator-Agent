import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from app.agents.schemas import ClarificationQuestion, DataDesign
from app.db.models import JobStatus, RunStatus


class JobWait(BaseModel):
    """Pending payload while the run waits for a worker job to finish."""

    kind: Literal["job"] = "job"
    job_id: uuid.UUID
    job_kind: str


class ClarificationRequest(BaseModel):
    """Pending payload while the Modeler waits for the Engineer's answers (FR-05)."""

    kind: Literal["clarification"] = "clarification"
    questions: list[ClarificationQuestion] = Field(min_length=1)


class DesignGateRequest(BaseModel):
    """Pending payload at gate 1 (FR-06): the exact design version under review."""

    kind: Literal["design_gate"] = "design_gate"
    design_version_id: uuid.UUID
    version: int
    design: DataDesign
    edited_by_user: bool


Pending = Annotated[JobWait | ClarificationRequest | DesignGateRequest, Field(discriminator="kind")]
pending_adapter: TypeAdapter[JobWait | ClarificationRequest | DesignGateRequest] = TypeAdapter(
    Pending
)

WAITING_STATUS: dict[str, RunStatus] = {
    "job": RunStatus.WAITING_JOB,
    "clarification": RunStatus.WAITING_CLARIFICATION,
    "design_gate": RunStatus.WAITING_DESIGN_APPROVAL,
}


class JobOutcome(BaseModel):
    """Resume value for JobWait, delivered once the job reaches a terminal status."""

    job_id: uuid.UUID
    status: Literal[JobStatus.SUCCEEDED, JobStatus.FAILED]
    result: dict[str, Any] | None = None
    error: str | None = None


class ClarificationAnswer(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ClarificationReply(BaseModel):
    """Resume value for ClarificationRequest."""

    user_id: uuid.UUID
    answers: list[ClarificationAnswer] = Field(min_length=1)


class DesignGateReply(BaseModel):
    """Resume value for DesignGateRequest.

    Approve may carry an edited design, which becomes a new design version and is
    the one the approval binds to. Return must explain why, so the Modeler can revise.
    """

    user_id: uuid.UUID
    decision: Literal["approve", "return"]
    edited_design: DataDesign | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def check_decision(self) -> "DesignGateReply":
        if self.decision == "return":
            if self.edited_design is not None:
                raise ValueError("a returned design cannot carry edits")
            if not (self.comment and self.comment.strip()):
                raise ValueError("returning a design requires a comment")
        return self
