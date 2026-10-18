import uuid
from typing import Any

import pytest
from langgraph.runtime import Runtime
from langgraph.types import Interrupt, PregelTask, StateSnapshot
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.schemas import ModelerOutput
from app.db.models import RunStatus
from app.graph import nodes
from app.graph.context import GraphContext
from app.graph.design_store import DesignNotApprovedError
from app.graph.interrupts import JobWait
from app.graph.state import PipelineState
from app.profiler.schemas import DataProfile
from app.services.runs import run_view


async def never_proposes(
    *,
    request_text: str,
    profile: DataProfile,
    answers: list[dict[str, str]],
    returned_design: Any,
    reviewer_feedback: str | None,
) -> ModelerOutput:
    raise AssertionError("the Modeler must not be called")


def unused_runtime() -> Runtime[GraphContext]:
    context = GraphContext(sessionmaker=async_sessionmaker(), propose_design=never_proposes)
    return Runtime(context=context)


def snapshot(
    *, values: dict[str, Any], next_nodes: tuple[str, ...], tasks: tuple[PregelTask, ...]
) -> StateSnapshot:
    return StateSnapshot(
        values=values,
        next=next_nodes,
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=tasks,
        interrupts=tuple(i for task in tasks for i in task.interrupts),
    )


def test_profile_failure_ends_the_run() -> None:
    assert nodes.route_after_profile({"error": "Profiling failed: boom"}) == "__end__"
    assert nodes.route_after_profile({"profile": {}}) == "modeler"


def test_questions_route_to_clarification() -> None:
    assert nodes.route_after_modeler({"questions": [{"question": "Gross or net?"}]}) == "clarify"
    assert nodes.route_after_modeler({"questions": []}) == "design_gate"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"design_approved": True}, "codegen"),
        ({"design_approved": False, "design_feedback": "Wrong grain"}, "modeler"),
        ({}, "modeler"),
    ],
)
def test_only_an_approved_design_reaches_codegen(state: PipelineState, expected: str) -> None:
    assert nodes.route_after_design_gate(state) == expected


@pytest.mark.parametrize("state", [{}, {"design_approved": False, "design_version_id": "x"}])
async def test_codegen_refuses_an_unapproved_design(state: PipelineState) -> None:
    with pytest.raises(DesignNotApprovedError):
        await nodes.codegen_node(state, unused_runtime())


def test_run_view_reports_the_pending_interrupt() -> None:
    wait = JobWait(job_id=uuid.uuid4(), job_kind="profile").model_dump(mode="json")
    task = PregelTask(id="t1", name="profile", path=(), interrupts=(Interrupt(value=wait),))
    status, step, pending = run_view(
        snapshot(values={"run_id": "r"}, next_nodes=("profile",), tasks=(task,))
    )
    assert (status, step, pending) == (RunStatus.WAITING_JOB, "profile", wait)


def test_run_view_between_nodes_is_running() -> None:
    view = run_view(snapshot(values={"run_id": "r"}, next_nodes=("modeler",), tasks=()))
    assert view == (RunStatus.RUNNING, "modeler", None)


def test_run_view_of_a_finished_thread() -> None:
    failed = run_view(snapshot(values={"error": "Profiling failed"}, next_nodes=(), tasks=()))
    done = run_view(snapshot(values={"dashboard_url": "http://mb"}, next_nodes=(), tasks=()))
    assert failed == (RunStatus.FAILED, None, None)
    assert done == (RunStatus.PUBLISHED, None, None)
