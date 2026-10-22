import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.schemas import ClarificationQuestion, DataDesign, ModelerOutput
from app.db.models import (
    Approval,
    ApprovalDecision,
    Batch,
    DesignVersion,
    Gate,
    Job,
    JobStatus,
    PipelineRun,
    Project,
    RunStatus,
    SourceFile,
    User,
)
from app.graph import nodes
from app.graph.builder import PipelineGraph, build_graph
from app.graph.context import GraphContext
from app.graph.interrupts import ClarificationReply, DesignGateReply
from app.graph.state import PipelineState
from app.profiler.schemas import DataProfile
from app.services.runs import (
    RunStateConflictError,
    deliver_finished_jobs,
    deliver_resume_intents,
    drive_run,
    recover_pending_runs,
    resume_run,
    start_run,
)
from tests.designs import minimal_design, minimal_profile

pytestmark = pytest.mark.integration

AMOUNT_QUESTION = ClarificationQuestion(
    topic="metric", question="Is registrations net of withdrawals?", why="Profile cannot tell"
)


def fake_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass
class ScriptedModeler:
    """Plays back Modeler outputs in order and records every call it receives."""

    outputs: list[ModelerOutput]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(
        self,
        *,
        request_text: str,
        profile: DataProfile,
        answers: list[dict[str, str]],
        returned_design: DataDesign | None,
        reviewer_feedback: str | None,
    ) -> ModelerOutput:
        self.calls.append(
            {
                "answers": answers,
                "returned_design": returned_design,
                "reviewer_feedback": reviewer_feedback,
            }
        )
        return self.outputs.pop(0)


@dataclass
class Fixture:
    factory: async_sessionmaker[AsyncSession]
    checkpointer: InMemorySaver
    graph: PipelineGraph
    context: GraphContext
    modeler: ScriptedModeler
    project_id: uuid.UUID
    batch_id: uuid.UUID
    user_id: uuid.UUID


def revised_design() -> DataDesign:
    design = minimal_design()
    design.metrics[0].definition = "Registrations excluding withdrawals"
    return design


@pytest.fixture
async def setup(session_factory: async_sessionmaker[AsyncSession]) -> Fixture:
    async with session_factory.begin() as session:
        user = User(email=f"gate-{uuid.uuid4().hex}@example.com", password_hash=uuid.uuid4().hex)
        session.add(user)
        await session.flush()
        project = Project(slug=f"gate-{uuid.uuid4().hex[:20]}", name="Gate", created_by=user.id)
        session.add(project)
        await session.flush()
        batch = Batch(project_id=project.id)
        session.add(batch)
        await session.flush()
        session.add(
            SourceFile(
                batch_id=batch.id,
                filename="studentRegistration.csv",
                storage_path=f"raw/{batch.id}/studentRegistration.csv",
                sha256="0" * 64,
                size_bytes=10,
                read_config={"delimiter": ","},
            )
        )
    modeler = ScriptedModeler(
        outputs=[
            ModelerOutput(questions=[AMOUNT_QUESTION]),
            ModelerOutput(design=minimal_design()),
            ModelerOutput(design=revised_design()),
        ]
    )
    context = GraphContext(
        sessionmaker=session_factory,
        propose_design=modeler,
        hash_design=fake_hash,
        check_design=lambda design: [],
        check_modeler_output=lambda output: [],
    )
    checkpointer = InMemorySaver()
    return Fixture(
        factory=session_factory,
        checkpointer=checkpointer,
        graph=build_graph(checkpointer),
        context=context,
        modeler=modeler,
        project_id=project.id,
        batch_id=batch.id,
        user_id=user.id,
    )


async def begin(fx: Fixture) -> uuid.UUID:
    async with fx.factory() as session:
        run_id = await start_run(
            session,
            project_id=fx.project_id,
            batch_id=fx.batch_id,
            request_text="Registrations per module",
        )
    await drive_run(fx.factory, fx.graph, fx.context, run_id)
    return run_id


async def load_run(fx: Fixture, run_id: uuid.UUID) -> PipelineRun:
    async with fx.factory() as session:
        run = await session.get(PipelineRun, run_id)
    assert run is not None
    return run


async def finish_job(fx: Fixture, run: PipelineRun, *, failed: bool = False) -> None:
    assert run.pending is not None
    values: dict[str, Any] = (
        {"status": JobStatus.FAILED, "last_error": "duckdb crashed"}
        if failed
        else {"status": JobStatus.SUCCEEDED, "result": minimal_profile().model_dump(mode="json")}
    )
    async with fx.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == uuid.UUID(run.pending["job_id"]))
            .values(finished_at=func.clock_timestamp(), **values)
        )


async def accept_reply(
    fx: Fixture, run_id: uuid.UUID, value: ClarificationReply | DesignGateReply
) -> None:
    run = await load_run(fx, run_id)
    assert run.interrupt_id is not None
    await resume_run(
        fx.factory,
        fx.graph,
        fx.context,
        run_id,
        project_id=fx.project_id,
        interrupt_id=run.interrupt_id,
        reply=value,
        design_version_id=(
            uuid.UUID(run.pending["design_version_id"])
            if isinstance(value, DesignGateReply) and run.pending
            else None
        ),
    )


async def reply(
    fx: Fixture, run_id: uuid.UUID, expected: RunStatus, value: ClarificationReply | DesignGateReply
) -> PipelineRun:
    assert (await load_run(fx, run_id)).status is expected
    await accept_reply(fx, run_id, value)
    await deliver_resume_intents(fx.factory, fx.graph, fx.context)
    return await load_run(fx, run_id)


async def reach_design_gate(fx: Fixture) -> uuid.UUID:
    run_id = await begin(fx)
    await finish_job(fx, await load_run(fx, run_id))
    await deliver_finished_jobs(fx.factory, fx.graph, fx.context)
    answers = ClarificationReply(
        user_id=fx.user_id, answers=[{"question": AMOUNT_QUESTION.question, "answer": "Net"}]
    )
    run = await reply(fx, run_id, RunStatus.WAITING_CLARIFICATION, answers)
    assert run.status is RunStatus.WAITING_DESIGN_APPROVAL
    return run_id


async def design_approvals(fx: Fixture, run_id: uuid.UUID) -> list[Approval]:
    async with fx.factory() as session:
        rows = await session.scalars(
            select(Approval)
            .where(Approval.run_id == run_id, Approval.gate == Gate.DESIGN)
            .order_by(Approval.created_at)
        )
        return list(rows.all())


async def design_versions(fx: Fixture, run_id: uuid.UUID) -> list[DesignVersion]:
    async with fx.factory() as session:
        rows = await session.scalars(
            select(DesignVersion)
            .where(DesignVersion.run_id == run_id)
            .order_by(DesignVersion.version)
        )
        return list(rows.all())


async def test_profile_job_is_enqueued_once_and_delivered_once(setup: Fixture) -> None:
    run_id = await begin(setup)
    run = await load_run(setup, run_id)
    assert run.status is RunStatus.WAITING_JOB
    assert run.current_step == "profile"
    assert run.pending is not None
    assert run.pending["kind"] == "job"

    await finish_job(setup, run)
    assert await deliver_finished_jobs(setup.factory, setup.graph, setup.context) >= 1
    assert await deliver_finished_jobs(setup.factory, setup.graph, setup.context) == 0

    async with setup.factory() as session:
        jobs = (await session.scalars(select(Job).where(Job.run_id == run_id))).all()
    assert len(jobs) == 1
    assert jobs[0].delivered is True
    assert jobs[0].payload["files"][0]["filename"] == "studentRegistration.csv"

    run = await load_run(setup, run_id)
    assert run.status is RunStatus.WAITING_CLARIFICATION
    assert run.pending is not None
    assert run.pending["questions"][0]["question"] == AMOUNT_QUESTION.question


async def test_failed_profile_job_fails_the_run(setup: Fixture) -> None:
    run_id = await begin(setup)
    await finish_job(setup, await load_run(setup, run_id), failed=True)
    await deliver_finished_jobs(setup.factory, setup.graph, setup.context)

    run = await load_run(setup, run_id)
    assert run.status is RunStatus.FAILED
    assert run.error == "Profiling failed: duckdb crashed"
    assert setup.modeler.calls == []


async def test_clarification_answers_reach_the_modeler(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)

    assert setup.modeler.calls[1]["answers"] == [
        {"question": AMOUNT_QUESTION.question, "answer": "Net"}
    ]
    run = await load_run(setup, run_id)
    assert run.pending is not None
    assert run.pending["kind"] == "design_gate"
    assert run.pending["version"] == 1
    assert DataDesign.model_validate(run.pending["design"]) == minimal_design()


async def test_returned_design_goes_back_to_the_modeler(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)
    returned = DesignGateReply(
        user_id=setup.user_id, decision="return", comment="Exclude withdrawals"
    )
    run = await reply(setup, run_id, RunStatus.WAITING_DESIGN_APPROVAL, returned)

    last_call = setup.modeler.calls[-1]
    assert last_call["reviewer_feedback"] == "Exclude withdrawals"
    assert last_call["returned_design"] == minimal_design()
    assert run.status is RunStatus.WAITING_DESIGN_APPROVAL
    assert run.pending is not None
    assert run.pending["version"] == 2

    approvals = await design_approvals(setup, run_id)
    assert [a.decision for a in approvals] == [ApprovalDecision.RETURNED]
    assert approvals[0].comment == "Exclude withdrawals"


async def test_codegen_runs_only_after_approval(
    setup: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[PipelineState] = []

    async def spy_codegen(state: PipelineState) -> dict[str, Any]:
        seen.append(state)
        raise NotImplementedError

    monkeypatch.setattr(nodes, "codegen_node", spy_codegen)
    setup.graph = build_graph(setup.checkpointer)
    run_id = await reach_design_gate(setup)
    returned = DesignGateReply(
        user_id=setup.user_id, decision="return", comment="Exclude withdrawals"
    )
    await reply(setup, run_id, RunStatus.WAITING_DESIGN_APPROVAL, returned)
    assert seen == []

    approve = DesignGateReply(user_id=setup.user_id, decision="approve")
    run = await reply(setup, run_id, RunStatus.WAITING_DESIGN_APPROVAL, approve)

    assert len(seen) == 1
    assert seen[0]["design_approved"] is True
    approvals = await design_approvals(setup, run_id)
    assert [a.decision for a in approvals] == [ApprovalDecision.RETURNED, ApprovalDecision.APPROVED]
    assert run.status is RunStatus.FAILED


async def test_approval_binds_to_the_edited_design(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)
    edited = minimal_design()
    edited.facts[0].grain = "one registration per student, module and presentation"
    approve = DesignGateReply(user_id=setup.user_id, decision="approve", edited_design=edited)
    await reply(setup, run_id, RunStatus.WAITING_DESIGN_APPROVAL, approve)

    versions = await design_versions(setup, run_id)
    assert [(v.version, v.edited_by_user) for v in versions] == [(1, False), (2, True)]
    approval = (await design_approvals(setup, run_id))[-1]
    edited_hash = fake_hash(edited.model_dump(mode="json"))
    assert approval.decision is ApprovalDecision.APPROVED
    assert approval.fingerprint == edited_hash == versions[1].content_hash
    assert approval.fingerprint_parts["design_version_id"] == str(versions[1].id)
    assert approval.approver_id == setup.user_id
    assert approval.independent_review is False


async def test_real_codegen_guard_lets_an_approved_design_through(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)
    approve = DesignGateReply(user_id=setup.user_id, decision="approve")
    run = await reply(setup, run_id, RunStatus.WAITING_DESIGN_APPROVAL, approve)

    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert run.error.startswith("NotImplementedError")


async def accept_reply_with_old_interrupt(
    fx: Fixture, run_id: uuid.UUID, value: DesignGateReply
) -> None:
    await resume_run(
        fx.factory,
        fx.graph,
        fx.context,
        run_id,
        project_id=fx.project_id,
        interrupt_id="already-accepted",
        reply=value,
    )


async def test_a_second_decision_is_rejected(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)
    returned = DesignGateReply(
        user_id=setup.user_id, decision="return", comment="Exclude withdrawals"
    )
    await accept_reply(setup, run_id, returned)
    with pytest.raises(RunStateConflictError):
        await accept_reply_with_old_interrupt(setup, run_id, returned)
    await deliver_resume_intents(setup.factory, setup.graph, setup.context)
    assert len(await design_approvals(setup, run_id)) == 1


async def test_restart_restores_a_run_waiting_at_gate_one(setup: Fixture) -> None:
    run_id = await reach_design_gate(setup)
    before = await load_run(setup, run_id)
    restarted = build_graph(setup.checkpointer)
    await recover_pending_runs(setup.factory, restarted, setup.context)

    after = await load_run(setup, run_id)
    assert after.status is RunStatus.WAITING_DESIGN_APPROVAL
    assert after.pending == before.pending
    assert after.current_step == "design_gate"
