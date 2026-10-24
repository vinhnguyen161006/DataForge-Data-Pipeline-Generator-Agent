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
from app.jobs.reports import DbtTestResult, ExecutionReportData, ModelMetrics
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


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"code_version_id": "c1", "failure_report": None}, "execute"),
        ({"failure_report": "Guard rejected the generated files: x"}, "codegen"),
        ({"failure_report": "x", "error": "Code still failing"}, "__end__"),
    ],
)
def test_route_after_codegen(state: PipelineState, expected: str) -> None:
    assert nodes.route_after_codegen(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"execution_report": {}, "failure_report": None}, "optimize"),
        ({"failure_report": "dbt compile failed"}, "codegen"),
        ({"error": "Sandbox build failed: timeout"}, "__end__"),
        ({"failure_report": "x", "error": "Code still failing"}, "__end__"),
    ],
)
def test_route_after_execute(state: PipelineState, expected: str) -> None:
    assert nodes.route_after_execute(state) == expected


def test_failures_are_repaired_until_the_budget_is_spent() -> None:
    first = nodes.code_failure(attempts=0, budget=2, report="dbt compile failed")
    last = nodes.code_failure(attempts=2, budget=2, report="dbt compile failed")
    assert first == {"failure_report": "dbt compile failed", "fix_attempts": 0}
    assert last["error"] == "Code still failing after 2 repair attempts: dbt compile failed"


def test_no_budget_ends_on_the_first_failure() -> None:
    assert "error" in nodes.code_failure(attempts=0, budget=0, report="boom")


def passing_report() -> ExecutionReportData:
    return ExecutionReportData(
        compiled=True,
        succeeded=True,
        models=[ModelMetrics(model_name="fct_orders", status="success", seconds=0.4)],
        tests=[
            DbtTestResult(
                test_name="unique_order_id", model_name="fct_orders", status="pass", failures=0
            )
        ],
    )


def test_a_clean_build_has_no_failure() -> None:
    assert nodes.build_failure(passing_report()) is None


def test_a_failing_test_fails_the_build_even_when_dbt_succeeded() -> None:
    report = passing_report()
    report.tests[0].status = "fail"
    report.tests[0].failures = 3
    assert nodes.build_failure(report) == (
        "test unique_order_id on fct_orders: fail, 3 failing rows"
    )


def test_compile_errors_are_reported_first() -> None:
    report = ExecutionReportData(compiled=False, succeeded=False, error="Parser Error near FROM")
    assert nodes.build_failure(report) == "Parser Error near FROM; dbt compile failed"


def test_unsuccessful_build_without_details_still_fails() -> None:
    report = passing_report()
    report.succeeded = False
    assert nodes.build_failure(report) == "dbt build did not succeed"


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
