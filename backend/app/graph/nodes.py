import uuid
from typing import Any, Literal

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.schemas import DataDesign
from app.db.models import ApprovalDecision, DesignVersion, JobQueue, JobStatus
from app.graph import design_store
from app.graph.context import GraphContext
from app.graph.design_store import DesignNotApprovedError
from app.graph.interrupts import (
    ClarificationReply,
    ClarificationRequest,
    DesignGateReply,
    DesignGateRequest,
    JobOutcome,
    JobWait,
)
from app.graph.state import PipelineState
from app.jobs import queue
from app.profiler.schemas import DataProfile

PROFILE_JOB_KIND = "profile"


class InvalidDesignError(ValueError):
    """A Modeler output or an edited design failed the cross-field design checks."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _ensure_valid(problems: list[str]) -> None:
    if problems:
        raise InvalidDesignError(problems)


async def profile_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Run the profiler in the sandbox and wait for its DataProfile.

    The node re-runs from the top on resume, so the job is enqueued idempotently and
    committed before interrupting.
    """
    run_id = uuid.UUID(state["run_id"])
    async with runtime.context.sessionmaker.begin() as session:
        payload = await design_store.profile_job_payload(session, uuid.UUID(state["batch_id"]))
        job = await queue.enqueue(
            session,
            queue=JobQueue.SANDBOX,
            kind=PROFILE_JOB_KIND,
            payload=payload,
            run_id=run_id,
            idempotency_key=f"{PROFILE_JOB_KIND}:{run_id}",
        )
        job_id = job.id
    wait = JobWait(job_id=job_id, job_kind=PROFILE_JOB_KIND)
    outcome = JobOutcome.model_validate(interrupt(wait.model_dump(mode="json")))
    if outcome.status is JobStatus.FAILED:
        return {"error": f"Profiling failed: {outcome.error or 'unknown error'}"}
    profile = DataProfile.model_validate(outcome.result)
    return {"profile": profile.model_dump(mode="json")}


async def modeler_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Ask the Modeler for a design or for questions (FR-04, FR-05).

    Only the DataProfile reaches the Modeler. A returned design is passed back together
    with the Engineer's feedback so the next proposal revises it.
    """
    context = runtime.context
    feedback = state.get("design_feedback")
    returned = DataDesign.model_validate(state["design"]) if feedback else None
    output = await context.propose_design(
        request_text=state["request_text"],
        profile=DataProfile.model_validate(state["profile"]),
        answers=state.get("clarification_answers", []),
        returned_design=returned,
        reviewer_feedback=feedback,
    )
    _ensure_valid(context.check_modeler_output(output))
    if output.design is None:
        return {"questions": [question.model_dump(mode="json") for question in output.questions]}

    content = output.design.model_dump(mode="json")
    async with context.sessionmaker.begin() as session:
        version = await design_store.add_design_version(
            session,
            run_id=uuid.UUID(state["run_id"]),
            content=content,
            content_hash=context.hash_design(content),
            edited_by_user=False,
        )
        version_id = version.id
    return {
        "design": content,
        "design_version_id": str(version_id),
        "design_approved": False,
        "design_feedback": None,
        "questions": [],
    }


async def clarify_node(state: PipelineState) -> dict[str, Any]:
    request = ClarificationRequest.model_validate({"questions": state["questions"]})
    reply = ClarificationReply.model_validate(interrupt(request.model_dump(mode="json")))
    answers = [answer.model_dump() for answer in reply.answers]
    return {
        "clarification_answers": [*state.get("clarification_answers", []), *answers],
        "questions": [],
    }


async def _presented_design(runtime: Runtime[GraphContext], version_id: str) -> DesignVersion:
    async with runtime.context.sessionmaker() as session:
        presented = await session.get(DesignVersion, uuid.UUID(version_id))
    if presented is None:
        raise LookupError(f"Design version {version_id} does not exist")
    return presented


async def _decided_version(
    runtime: Runtime[GraphContext], presented: DesignVersion, reply: DesignGateReply
) -> DesignVersion:
    if reply.edited_design is None:
        return presented
    context = runtime.context
    _ensure_valid(context.check_design(reply.edited_design))
    content = reply.edited_design.model_dump(mode="json")
    content_hash = context.hash_design(content)
    async with context.sessionmaker.begin() as session:
        existing = await design_store.find_edit_of(session, presented, content_hash)
        if existing is not None:
            return existing
        return await design_store.add_design_version(
            session,
            run_id=presented.run_id,
            content=content,
            content_hash=content_hash,
            edited_by_user=True,
        )


async def design_gate_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """Gate 1 (FR-06): the Engineer approves, edits then approves, or returns the design.

    The approval binds to the hash of the design actually decided on. A presented
    version gets at most one decision, so a re-run after a crash does not record twice.
    """
    presented = await _presented_design(runtime, state["design_version_id"])
    request = DesignGateRequest(
        design_version_id=presented.id,
        version=presented.version,
        design=DataDesign.model_validate(presented.content),
        edited_by_user=presented.edited_by_user,
    )
    reply = DesignGateReply.model_validate(interrupt(request.model_dump(mode="json")))
    decided = await _decided_version(runtime, presented, reply)
    approved = reply.decision == "approve"

    async with runtime.context.sessionmaker.begin() as session:
        existing = await design_store.find_decision_on(session, presented)
        if existing is not None and (
            existing.approver_id != reply.user_id
            or existing.decision
            != (ApprovalDecision.APPROVED if approved else ApprovalDecision.RETURNED)
            or existing.fingerprint != decided.content_hash
            or existing.fingerprint_parts["design_version_id"] != str(decided.id)
            or existing.comment != reply.comment
        ):
            raise ValueError("A different decision was already recorded for this design")
        if existing is None:
            session.add(
                design_store.design_decision(
                    project_id=uuid.UUID(state["project_id"]),
                    presented=presented,
                    decided=decided,
                    approver_id=reply.user_id,
                    decision=ApprovalDecision.APPROVED if approved else ApprovalDecision.RETURNED,
                    comment=reply.comment,
                )
            )

    if not approved:
        return {"design_approved": False, "design_feedback": reply.comment}
    return {
        "design": decided.content,
        "design_version_id": str(decided.id),
        "design_approved": True,
        "design_feedback": None,
    }


async def codegen_node(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
    """TODO: retrieve examples, generate, assemble a CodeVersion.

    Refuses first, from both the state and the stored approval, unless the current
    design passed gate 1 (FR-06).
    """
    if not state.get("design_approved"):
        raise DesignNotApprovedError("Code generation requires an approved design")
    async with runtime.context.sessionmaker() as session:
        await design_store.assert_design_approved(session, uuid.UUID(state["design_version_id"]))
    raise NotImplementedError


async def execute_node(state: PipelineState) -> dict[str, Any]:
    """TODO: enqueue a sandbox "dbt_build" job and interrupt until its report is delivered."""
    raise NotImplementedError


async def optimize_node(state: PipelineState) -> dict[str, Any]:
    """TODO: rank slow models, gather rule + LLM candidates within budget, benchmark in sandbox.

    Judge each candidate deterministically, log every rejection, keep the best
    valid version (a new CodeVersion with origin "optimizer" when a rewrite is kept).
    """
    raise NotImplementedError


async def code_gate_node(state: PipelineState) -> dict[str, Any]:
    """TODO: gate 2 (FR-13): interrupt with diff, tests, perf table and dashboard config.

    Store the Approval with the VersionParts fingerprint; in team mode the
    reviewer must differ from the engineer, in solo mode flag no independent review.
    """
    raise NotImplementedError


async def publish_node(state: PipelineState) -> dict[str, Any]:
    """TODO: verify the approval still matches, enqueue a publisher "publish" job, wait for it."""
    raise NotImplementedError


async def dashboard_node(state: PipelineState) -> dict[str, Any]:
    """TODO: enqueue a publisher "metabase_sync" job, wait, store the dashboard URL."""
    raise NotImplementedError


def route_after_profile(state: PipelineState) -> Literal["modeler", "__end__"]:
    return "__end__" if state.get("error") else "modeler"


def route_after_modeler(state: PipelineState) -> Literal["clarify", "design_gate"]:
    return "clarify" if state.get("questions") else "design_gate"


def route_after_design_gate(state: PipelineState) -> Literal["codegen", "modeler"]:
    """Codegen only after approval; a returned design goes back to the Modeler (FR-06)."""
    return "codegen" if state.get("design_approved") else "modeler"


def route_after_execute(state: PipelineState) -> Literal["optimize", "codegen", "__end__"]:
    """TODO: on failure retry codegen within max_fix_attempts, else end with an error."""
    raise NotImplementedError


def route_after_code_gate(state: PipelineState) -> Literal["publish", "codegen"]:
    """TODO: publish only when approved; otherwise back to Codegen with feedback."""
    raise NotImplementedError
