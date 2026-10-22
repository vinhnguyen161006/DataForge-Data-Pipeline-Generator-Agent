"""Gate-1 HTTP decisions with real PostgreSQL receipts, locks and checkpoints."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.agents.schemas import ClarificationQuestion, ModelerOutput
from app.api.routes import runs
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import (
    Approval,
    ApprovalDecision,
    CodeVersion,
    DesignVersion,
    Job,
    JobStatus,
    PipelineRun,
    Project,
    RunResumeIntent,
    RunStatus,
)
from app.db.session import make_engine, make_sessionmaker
from app.graph import design_store, nodes
from app.graph.context import GraphContext
from app.graph.state import PipelineState
from app.services import runs as service
from app.services.run_lock import RunBusyError, run_lock
from tests.designs import minimal_design, minimal_profile
from tests.integration.test_graph_design_gate import ScriptedModeler
from tests.integration.test_run_creation import (
    creation as creation,
)
from tests.integration.test_run_creation import (
    creation_password_hash as creation_password_hash,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from httpx import Response
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.runtime import Runtime

    from app.graph.builder import PipelineGraph
    from tests.integration.test_run_creation import RunCreationScenario

pytestmark = pytest.mark.integration
QUESTION = ClarificationQuestion(
    topic="metric", question="Include withdrawn registrations?", why="The profile cannot decide"
)


@dataclass
class DecisionScenario:
    base: RunCreationScenario
    seen: list[str] = field(default_factory=list)
    modeler: ScriptedModeler = field(default_factory=lambda: ScriptedModeler([]))
    context: GraphContext | None = None

    async def poll(self, run_id: UUID, *, client: AsyncClient | None = None) -> dict[str, Any]:
        response = await (client or self.base.client).get(
            f"/api/projects/{self.base.project_id}/runs/{run_id}",
            headers=self.base.headers["engineer"],
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def reach(self, *, questions: bool = False) -> tuple[UUID, dict[str, Any]]:
        self.modeler.outputs = ([ModelerOutput(questions=[QUESTION])] if questions else []) + [
            ModelerOutput(design=minimal_design()) for _ in range(8)
        ]
        created = await self.base.create()
        assert created.status_code == 200, created.text
        run_id = UUID(created.json()["id"])
        job = (await self.base.jobs(run_id))[0]
        async with self.base.factory.begin() as session:
            stored = await session.get(Job, job.id)
            assert stored is not None
            stored.status = JobStatus.SUCCEEDED
            stored.result = minimal_profile().model_dump(mode="json")
            stored.finished_at = func.now()
        await service.deliver_finished_jobs(
            self.base.factory, self.base.app.state.graph, self.base.app.state.graph_context
        )
        return run_id, await self.poll(run_id)

    async def post(
        self,
        run_id: UUID,
        body: dict[str, Any],
        *,
        clarification: bool = False,
        actor: str = "engineer",
        project_id: UUID | None = None,
        client: AsyncClient | None = None,
    ) -> Response:
        endpoint = "clarifications" if clarification else "design-decision"
        return await (client or self.base.client).post(
            f"/api/projects/{project_id or self.base.project_id}/runs/{run_id}/{endpoint}",
            headers=self.base.headers[actor],
            json=body,
        )

    async def records(self) -> dict[str, int]:
        async with self.base.factory() as session:
            return {
                model.__tablename__: int(
                    await session.scalar(select(func.count()).select_from(model)) or 0
                )
                for model in (Approval, DesignVersion, CodeVersion, RunResumeIntent, Job)
            }

    async def approvals(self) -> list[Approval]:
        async with self.base.factory() as session:
            return list(await session.scalars(select(Approval).order_by(Approval.created_at)))

    async def receipts(self) -> list[RunResumeIntent]:
        async with self.base.factory() as session:
            return list(await session.scalars(select(RunResumeIntent)))


def small_graph(saver: BaseCheckpointSaver[str], seen: list[str]) -> PipelineGraph:
    """Keep real nodes through gate 1, replacing only the later code-generation work."""
    graph: StateGraph[PipelineState, GraphContext, PipelineState, PipelineState] = StateGraph(
        PipelineState, context_schema=GraphContext
    )

    async def codegen_probe(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
        assert state["design_approved"] is True
        async with runtime.context.sessionmaker() as session:
            await design_store.assert_design_approved(session, UUID(state["design_version_id"]))
        seen.append(state["run_id"])
        return {}

    for name, node in (
        ("profile", nodes.profile_node),
        ("modeler", nodes.modeler_node),
        ("clarify", nodes.clarify_node),
        ("design_gate", nodes.design_gate_node),
    ):
        graph.add_node(name, node)
    graph.add_node("codegen", codegen_probe)
    graph.add_edge(START, "profile")
    graph.add_conditional_edges("profile", nodes.route_after_profile)
    graph.add_conditional_edges("modeler", nodes.route_after_modeler)
    graph.add_edge("clarify", "modeler")
    graph.add_conditional_edges("design_gate", nodes.route_after_design_gate)
    graph.add_edge("codegen", END)
    return graph.compile(checkpointer=saver)


@pytest.fixture
async def decisions(creation: RunCreationScenario) -> DecisionScenario:
    scenario = DecisionScenario(creation)
    context = GraphContext(sessionmaker=creation.factory, propose_design=scenario.modeler)
    scenario.context = context
    creation.app.state.graph = small_graph(creation.checkpointer, scenario.seen)
    creation.app.state.graph_context = context
    return scenario


def decision_body(view: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "interrupt_id": view["interrupt_id"],
        "design_version_id": view["pending"]["design_version_id"],
        "decision": "approve",
        **changes,
    }


def answer_body(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "interrupt_id": view["interrupt_id"],
        "answers": [{"question": QUESTION.question, "answer": "  Exclude withdrawals  "}],
    }


@asynccontextmanager
async def fresh_backend(
    scenario: DecisionScenario, database_url: str
) -> AsyncIterator[tuple[AsyncClient, GraphContext, PipelineGraph]]:
    """Open an independent engine, saver, graph and HTTP app on the committed data."""
    engine = make_engine(database_url).execution_options(
        schema_translate_map={None: scenario.base.schema}
    )
    try:
        factory = make_sessionmaker(engine)
        conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
        async with open_postgres_checkpointer(conn_string) as saver:
            modeler = ScriptedModeler([ModelerOutput(design=minimal_design()) for _ in range(8)])
            context = GraphContext(sessionmaker=factory, propose_design=modeler)
            graph = small_graph(saver, scenario.seen)
            app = FastAPI()
            app.state.sessionmaker = factory
            app.state.graph = graph
            app.state.graph_context = context
            app.include_router(runs.router, prefix="/api")
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://restarted-decisions.test",
            ) as client:
                yield client, context, graph
    finally:
        await engine.dispose()


async def test_approve_records_authenticated_actor_and_reaches_codegen(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach()
    assert view["interrupt_id"]
    assert decisions.seen == []
    before = await decisions.records()
    assert before["code_versions"] == before["approvals"] == 0
    response = await decisions.post(run_id, decision_body(view))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert response.json()["pending"] is None
    assert response.json()["interrupt_id"] is None
    final = await decisions.poll(run_id)
    assert final["status"] == "published"
    assert decisions.seen == [str(run_id)]
    approval = (await decisions.approvals())[0]
    receipt = (await decisions.receipts())[0]
    assert approval.approver_id == receipt.actor_id
    async with decisions.base.factory() as session:
        engineer_id = await session.scalar(
            select(Project.created_by).where(Project.id == decisions.base.project_id)
        )
    assert approval.approver_id == engineer_id
    assert approval.decision == ApprovalDecision.APPROVED
    assert approval.fingerprint_parts["design_version_id"] == view["pending"]["design_version_id"]
    assert (
        approval.fingerprint_parts["presented_design_version_id"]
        == view["pending"]["design_version_id"]
    )
    assert approval.independent_review is False
    assert receipt.payload["user_id"] == str(receipt.actor_id)
    assert receipt.delivered is True


async def test_edited_approval_binds_new_version_and_preserves_presented_design(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach()
    edited = minimal_design()
    edited.facts[0].grain = "One registration per student, module and presentation"
    response = await decisions.post(
        run_id, decision_body(view, edited_design=edited.model_dump(mode="json"))
    )
    assert response.status_code == 200, response.text
    async with decisions.base.factory() as session:
        versions = list(
            await session.scalars(select(DesignVersion).order_by(DesignVersion.version))
        )
    assert len(versions) == 2
    assert versions[0].content == view["pending"]["design"]
    assert versions[1].edited_by_user is True
    assert versions[1].content == edited.model_dump(mode="json")
    approval = (await decisions.approvals())[0]
    assert approval.fingerprint == versions[1].content_hash
    assert approval.fingerprint_parts["design_version_id"] == str(versions[1].id)
    assert approval.fingerprint_parts["presented_design_version_id"] == str(versions[0].id)
    assert decisions.seen == [str(run_id)]


async def test_return_revisits_modeler_with_feedback_without_codegen(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach()
    response = await decisions.post(
        run_id, decision_body(view, decision="return", comment="  Exclude withdrawals  ")
    )
    assert response.status_code == 200, response.text
    current = await decisions.poll(run_id)
    assert current["status"] == "waiting_design_approval"
    assert current["interrupt_id"] != view["interrupt_id"]
    assert current["pending"]["version"] == 2
    assert decisions.modeler.calls[-1]["reviewer_feedback"] == "Exclude withdrawals"
    assert decisions.modeler.calls[-1]["returned_design"] == minimal_design()
    assert decisions.seen == []
    assert (await decisions.records())["code_versions"] == 0
    assert (await decisions.approvals())[0].decision == ApprovalDecision.RETURNED
    stale = await decisions.post(run_id, decision_body(view))
    assert stale.status_code == 409
    assert len(await decisions.approvals()) == 1


async def test_clarification_answers_return_to_modeler_without_an_approval(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach(questions=True)
    response = await decisions.post(run_id, answer_body(view), clarification=True)
    assert response.status_code == 200, response.text
    assert decisions.modeler.calls[-1]["answers"] == [
        {"question": QUESTION.question, "answer": "Exclude withdrawals"}
    ]
    current = await decisions.poll(run_id)
    assert current["status"] == "waiting_design_approval"
    assert current["interrupt_id"] != view["interrupt_id"]
    assert decisions.seen == []
    assert await decisions.approvals() == []
    assert (await decisions.records())["code_versions"] == 0


@pytest.mark.parametrize(
    ("actor", "expected"),
    [
        ("reviewer", 403),
        ("outsider", 403),
        ("anonymous", 401),
    ],
)
@pytest.mark.parametrize("clarification", [False, True])
async def test_only_project_engineers_can_submit_human_replies(
    decisions: DecisionScenario,
    actor: str,
    expected: int,
    clarification: bool,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    before = await decisions.records()
    body = answer_body(view) if clarification else decision_body(view)
    response = await decisions.post(run_id, body, actor=actor, clarification=clarification)
    assert response.status_code == expected
    assert await decisions.records() == before
    assert await decisions.poll(run_id) == view
    assert decisions.seen == []


@pytest.mark.parametrize("clarification", [False, True])
async def test_unknown_or_cross_project_run_is_not_exposed(
    decisions: DecisionScenario,
    clarification: bool,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    body = answer_body(view) if clarification else decision_body(view)
    unknown = await decisions.post(uuid4(), body, clarification=clarification)
    assert unknown.status_code == 404
    foreign = await decisions.post(run_id, body, clarification=clarification, project_id=uuid4())
    assert foreign.status_code == 403
    assert await decisions.receipts() == []


@pytest.mark.parametrize("clarification", [False, True])
@pytest.mark.parametrize("field", ["user_id", "approver_id", "actor_id"])
async def test_client_cannot_choose_the_decision_actor(
    decisions: DecisionScenario,
    clarification: bool,
    field: str,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    body = answer_body(view) if clarification else decision_body(view)
    body[field] = str(uuid4())
    response = await decisions.post(run_id, body, clarification=clarification)
    assert response.status_code == 422
    assert await decisions.receipts() == []
    assert await decisions.approvals() == []


@pytest.mark.parametrize(
    "change",
    [
        {"interrupt_id": "stale-interrupt"},
        {"design_version_id": str(uuid4())},
    ],
)
async def test_stale_interrupt_or_design_is_rejected_without_mutation(
    decisions: DecisionScenario,
    change: dict[str, Any],
) -> None:
    run_id, view = await decisions.reach()
    before = await decisions.records()
    response = await decisions.post(run_id, decision_body(view, **change))
    assert response.status_code == 409
    assert await decisions.records() == before
    assert await decisions.poll(run_id) == view


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"interrupt_id": "", "decision": "approve"},
        {"decision": "unknown"},
        {"decision": "return"},
        {"decision": "return", "comment": "   "},
        {
            "decision": "return",
            "comment": "Revise",
            "edited_design": minimal_design().model_dump(mode="json"),
        },
        {"edited_design": {}},
    ],
)
async def test_invalid_decision_bodies_are_rejected_before_acceptance(
    decisions: DecisionScenario,
    body: dict[str, Any],
) -> None:
    run_id, view = await decisions.reach()
    submitted = decision_body(view, **body) if body else {}
    response = await decisions.post(run_id, submitted)
    assert response.status_code == 422
    assert await decisions.receipts() == []


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"question": QUESTION.question, "answer": " "}],
        [{"question": "Old question", "answer": "No"}],
        [
            {"question": QUESTION.question, "answer": "Yes"},
            {"question": QUESTION.question, "answer": "No"},
        ],
        [
            {"question": QUESTION.question, "answer": "No"},
            {"question": "Unknown", "answer": "Yes"},
        ],
    ],
)
async def test_answers_must_match_each_current_question_once(
    decisions: DecisionScenario,
    answers: list[dict[str, str]],
) -> None:
    run_id, view = await decisions.reach(questions=True)
    before = await decisions.records()
    body = answer_body(view)
    body["answers"] = answers
    response = await decisions.post(run_id, body, clarification=True)
    assert response.status_code == 422, response.text
    assert await decisions.records() == before
    assert await decisions.poll(run_id) == view


@pytest.mark.parametrize(
    "invalid", ["card-metric", "key-table", "relationship", "blank-grain", "open-question"]
)
async def test_edited_design_must_pass_real_cross_field_validation(
    decisions: DecisionScenario,
    invalid: str,
) -> None:
    run_id, view = await decisions.reach()
    edited = minimal_design()
    if invalid == "card-metric":
        edited.dashboard.cards[0].metric = "undefined"
    elif invalid == "key-table":
        edited.keys[0].table = "undefined"
    elif invalid == "relationship":
        from app.agents.schemas import RelationshipDefinition

        edited.relationships.append(
            RelationshipDefinition(
                child_table="missing",
                child_columns=["a"],
                parent_table="missing",
                parent_columns=["a", "b"],
                cardinality="many_to_one",
                rationale="Mismatch",
            )
        )
    elif invalid == "blank-grain":
        edited.facts[0].grain = " "
    else:
        edited.facts[0].open_questions = ["Resolve this first"]
    response = await decisions.post(
        run_id, decision_body(view, edited_design=edited.model_dump(mode="json"))
    )
    assert response.status_code == 422, response.text
    assert await decisions.receipts() == []
    assert await decisions.approvals() == []
    assert await decisions.poll(run_id) == view


@pytest.mark.parametrize("clarification", [False, True])
async def test_human_endpoints_cannot_resume_a_worker_interrupt(
    decisions: DecisionScenario,
    clarification: bool,
) -> None:
    created = await decisions.base.create()
    run_id = UUID(created.json()["id"])
    view = await decisions.poll(run_id)
    before = await decisions.records()
    body = (
        {"interrupt_id": view["interrupt_id"], "answers": [{"question": "Fake", "answer": "No"}]}
        if clarification
        else {
            "interrupt_id": view["interrupt_id"],
            "design_version_id": str(uuid4()),
            "decision": "approve",
        }
    )
    response = await decisions.post(run_id, body, clarification=clarification)
    assert response.status_code == 409
    assert await decisions.records() == before
    assert await decisions.poll(run_id) == view
    assert decisions.seen == []


async def test_human_endpoints_cannot_cross_each_others_gate(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach(questions=True)
    wrong = await decisions.post(
        run_id,
        {
            "interrupt_id": view["interrupt_id"],
            "design_version_id": str(uuid4()),
            "decision": "approve",
        },
    )
    assert wrong.status_code == 409
    correct = await decisions.post(run_id, answer_body(view), clarification=True)
    assert correct.status_code == 200
    after = await decisions.poll(run_id)
    wrong = await decisions.post(
        run_id,
        {
            "interrupt_id": after["interrupt_id"],
            "answers": [{"question": QUESTION.question, "answer": "No"}],
        },
        clarification=True,
    )
    assert wrong.status_code == 409
    assert await decisions.approvals() == []
    assert decisions.seen == []


@pytest.mark.parametrize("field", ["interrupt_id", "design_version_id"])
async def test_decision_requires_stale_request_identifiers(
    decisions: DecisionScenario,
    field: str,
) -> None:
    run_id, view = await decisions.reach()
    body = decision_body(view)
    del body[field]
    response = await decisions.post(run_id, body)
    assert response.status_code == 422
    assert await decisions.receipts() == []


async def test_checkpoint_mismatch_is_rejected_even_if_db_projection_matches(
    decisions: DecisionScenario,
) -> None:
    run_id, view = await decisions.reach()
    async with decisions.base.factory.begin() as session:
        row = await session.get(PipelineRun, run_id)
        assert row is not None
        row.interrupt_id = "outdated-projection"
    body = decision_body(view, interrupt_id="outdated-projection")
    response = await decisions.post(run_id, body)
    assert response.status_code == 409
    assert await decisions.receipts() == []
    assert await decisions.approvals() == []


@pytest.mark.parametrize("clarification", [False, True])
async def test_duplicate_decision_from_independent_backends_is_accepted_once(
    decisions: DecisionScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    clarification: bool,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    body = answer_body(view) if clarification else decision_body(view)
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        with monkeypatch.context() as patch:
            delivery = AsyncMock(return_value=0)
            patch.setattr(service, "deliver_resume_intents", delivery)
            responses = await asyncio.gather(
                decisions.post(run_id, body, clarification=clarification),
                decisions.post(run_id, body, clarification=clarification, client=client),
            )
            assert sorted(response.status_code for response in responses) == [200, 409]
            receipts = await decisions.receipts()
            assert len(receipts) == 1
            assert receipts[0].delivered is False
            assert await decisions.approvals() == []
        assert decisions.context is not None
        await asyncio.gather(
            service.deliver_resume_intents(
                decisions.base.factory, decisions.base.app.state.graph, decisions.context
            ),
            service.deliver_resume_intents(context.sessionmaker, graph, context),
        )
    assert len(await decisions.receipts()) == 1
    if clarification:
        assert await decisions.approvals() == []
        assert decisions.seen == []
    else:
        assert len(await decisions.approvals()) == 1
        assert decisions.seen == [str(run_id)]


@pytest.mark.parametrize("clarification", [False, True])
async def test_reply_survives_closing_backend_after_acceptance_before_delivery(
    decisions: DecisionScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    clarification: bool,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    body = answer_body(view) if clarification else decision_body(view)
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        with monkeypatch.context() as patch:
            patch.setattr(service, "deliver_resume_intents", AsyncMock(return_value=0))
            response = await decisions.post(
                run_id, body, clarification=clarification, client=client
            )
        assert response.status_code == 200
        assert (await decisions.receipts())[0].delivered is False
        assert (await decisions.base.row(run_id)).status == RunStatus.RUNNING
        old_state = await graph.aget_state(service.thread_config(run_id))
        assert old_state.tasks[0].interrupts[0].id == view["interrupt_id"]
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        await service.recover_pending_runs(context.sessionmaker, graph, context)
        current = await decisions.poll(run_id, client=client)
        receipt = (await decisions.receipts())[0]
        assert receipt.delivered is True
        assert receipt.interrupt_id == view["interrupt_id"]
        if clarification:
            assert current["status"] == "waiting_design_approval"
            assert await decisions.approvals() == []
            assert decisions.seen == []
        else:
            assert current["status"] == "published"
            assert len(await decisions.approvals()) == 1
            assert decisions.seen == [str(run_id)]


@pytest.mark.parametrize("clarification", [False, True])
async def test_restart_preserves_unanswered_human_interrupt(
    decisions: DecisionScenario,
    database_url: str,
    clarification: bool,
) -> None:
    run_id, view = await decisions.reach(questions=clarification)
    before = await decisions.records()
    calls = len(decisions.modeler.calls)
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        await service.recover_pending_runs(context.sessionmaker, graph, context)
        current = await decisions.poll(run_id, client=client)
        assert current["status"] == view["status"]
        assert current["pending"] == view["pending"]
        assert current["interrupt_id"] == view["interrupt_id"]
    assert await decisions.records() == before
    assert len(decisions.modeler.calls) == calls
    assert decisions.seen == []


@pytest.mark.parametrize("decision", ["approve", "return"])
async def test_crash_after_graph_progress_does_not_reapply_old_decision(
    decisions: DecisionScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    run_id, view = await decisions.reach()
    body = decision_body(view, decision=decision, comment="Revise the metric")
    with monkeypatch.context() as patch:
        patch.setattr(service, "deliver_resume_intents", AsyncMock(return_value=0))
        response = await decisions.post(run_id, body)
    assert response.status_code == 200
    assert decisions.context is not None
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "_mark_resume_delivered",
            AsyncMock(side_effect=RuntimeError("Injected crash before receipt acknowledgement")),
        )
        with pytest.raises(RuntimeError, match="Injected crash"):
            await service.deliver_resume_intents(
                decisions.base.factory, decisions.base.app.state.graph, decisions.context
            )
    before = await decisions.records()
    advanced = await decisions.poll(run_id)
    assert len(await decisions.approvals()) == 1
    assert (await decisions.receipts())[0].delivered is False
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        await service.recover_pending_runs(context.sessionmaker, graph, context)
        current = await decisions.poll(run_id, client=client)
        assert current["status"] == advanced["status"]
        assert current["pending"] == advanced["pending"]
        assert current["interrupt_id"] == advanced["interrupt_id"]
    assert await decisions.records() == before
    assert (await decisions.receipts())[0].delivered is True
    assert decisions.seen == ([str(run_id)] if decision == "approve" else [])


async def test_lock_is_shared_across_independent_backend_connections_and_released(
    decisions: DecisionScenario,
    database_url: str,
) -> None:
    run_id, view = await decisions.reach()
    async with fresh_backend(decisions, database_url) as (_client, context, _graph):
        async with run_lock(context.sessionmaker, run_id):
            blocked = await decisions.post(run_id, decision_body(view))
            assert blocked.status_code == 409
            assert await decisions.receipts() == []
        allowed = await decisions.post(run_id, decision_body(view))
        assert allowed.status_code == 200
    assert decisions.seen == [str(run_id)]


async def test_failed_receipt_commit_preserves_waiting_run(
    decisions: DecisionScenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    run_id, view = await decisions.reach()
    with monkeypatch.context() as patch:
        patch.setattr(
            AsyncSession, "commit", AsyncMock(side_effect=RuntimeError("Injected commit failure"))
        )
        response = await decisions.post(run_id, decision_body(view))
    assert response.status_code == 500
    assert await decisions.poll(run_id) == view
    assert await decisions.receipts() == []
    assert decisions.seen == []


class InterruptedDecision(BaseException):
    """Emulate a process disappearing after a gate writes its database records."""


@pytest.mark.parametrize("edited", [False, True])
async def test_restart_replays_gate_after_approval_commit_without_duplicate_records(
    decisions: DecisionScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    edited: bool,
) -> None:
    run_id, view = await decisions.reach()
    changes: dict[str, Any] = {}
    if edited:
        design = minimal_design()
        design.facts[0].grain = "One registration in a module presentation"
        changes["edited_design"] = design.model_dump(mode="json")
    with monkeypatch.context() as patch:
        patch.setattr(service, "deliver_resume_intents", AsyncMock(return_value=0))
        response = await decisions.post(run_id, decision_body(view, **changes))
    assert response.status_code == 200
    original = nodes.design_gate_node

    async def interrupted_gate(
        state: PipelineState, runtime: Runtime[GraphContext]
    ) -> dict[str, Any]:
        await original(state, runtime)
        raise InterruptedDecision

    with monkeypatch.context() as patch:
        patch.setattr(nodes, "design_gate_node", interrupted_gate)
        graph = small_graph(decisions.base.checkpointer, decisions.seen)
        assert decisions.context is not None
        with pytest.raises(InterruptedDecision):
            await service.deliver_resume_intents(decisions.base.factory, graph, decisions.context)
    before = await decisions.records()
    assert before["approvals"] == 1
    assert before["design_versions"] == (2 if edited else 1)
    assert decisions.seen == []
    assert (await decisions.receipts())[0].delivered is False
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        await service.recover_pending_runs(context.sessionmaker, graph, context)
        assert (await decisions.poll(run_id, client=client))["status"] == "published"
    assert await decisions.records() == before
    assert decisions.seen == [str(run_id)]
    assert (await decisions.receipts())[0].delivered is True


async def test_cancelled_lock_holder_releases_its_pooled_connection(
    decisions: DecisionScenario,
) -> None:
    entered = asyncio.Event()
    run_id = uuid4()

    async def hold() -> None:
        async with run_lock(decisions.base.factory, run_id):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold())
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with pytest.raises(RunBusyError):
            async with run_lock(decisions.base.factory, run_id, wait=False):
                pytest.fail("An independent owner must not acquire the held run")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with run_lock(decisions.base.factory, run_id, wait=False):
        pass


async def test_cancelled_lock_waiter_never_acquires_a_later_owner_lock(
    decisions: DecisionScenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrying = asyncio.Event()
    original_sleep = asyncio.sleep

    async def observed_sleep(seconds: float) -> None:
        retrying.set()
        await original_sleep(seconds)

    async def wait_for_lock(run_id: UUID) -> None:
        async with run_lock(decisions.base.factory, run_id):
            pytest.fail("The cancelled waiter must not become an owner")

    run_id = uuid4()
    async with run_lock(decisions.base.factory, run_id):
        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "sleep", observed_sleep)
            task = asyncio.create_task(wait_for_lock(run_id))
            try:
                await asyncio.wait_for(retrying.wait(), timeout=5)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
    async with run_lock(decisions.base.factory, run_id, wait=False):
        pass


@pytest.mark.parametrize("decision", ["return", "edit"])
async def test_accepted_return_or_edit_survives_a_backend_restart(
    decisions: DecisionScenario,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    run_id, view = await decisions.reach()
    changes: dict[str, Any]
    if decision == "return":
        changes = {"decision": "return", "comment": "Exclude withdrawn registrations"}
    else:
        edited = minimal_design()
        edited.metrics[0].definition = "Registration count after withdrawals"
        changes = {"edited_design": edited.model_dump(mode="json")}
    async with fresh_backend(decisions, database_url) as (client, _context, _graph):
        with monkeypatch.context() as patch:
            patch.setattr(service, "deliver_resume_intents", AsyncMock(return_value=0))
            accepted = await decisions.post(run_id, decision_body(view, **changes), client=client)
        assert accepted.status_code == 200
        assert await decisions.approvals() == []
    async with fresh_backend(decisions, database_url) as (client, context, graph):
        await service.recover_pending_runs(context.sessionmaker, graph, context)
        current = await decisions.poll(run_id, client=client)
    approval = (await decisions.approvals())[0]
    assert (await decisions.receipts())[0].delivered is True
    if decision == "return":
        assert approval.decision == ApprovalDecision.RETURNED
        assert current["status"] == "waiting_design_approval"
        assert current["interrupt_id"] != view["interrupt_id"]
        assert decisions.seen == []
    else:
        assert approval.decision == ApprovalDecision.APPROVED
        assert (
            approval.fingerprint_parts["design_version_id"] != view["pending"]["design_version_id"]
        )
        assert current["status"] == "published"
        assert decisions.seen == [str(run_id)]
