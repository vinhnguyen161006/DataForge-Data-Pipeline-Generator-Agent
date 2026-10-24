import dataclasses
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import func, select, update

from app.agents.schemas import CodegenOutput, DataDesign, GeneratedFile
from app.codegen.project import AssembledProject
from app.db.models import (
    CodeOrigin,
    CodeVersion,
    ExecutionReport,
    Job,
    JobStatus,
    PipelineRun,
    RunStatus,
)
from app.graph.interrupts import DesignGateReply
from app.jobs.reports import ExecutionReportData
from app.profiler.schemas import DataProfile
from app.services.runs import deliver_finished_jobs, thread_config
from tests.integration import test_graph_design_gate as gate

pytestmark = pytest.mark.integration

setup = gate.setup


@pytest.fixture(autouse=True)
async def settle_build_jobs(setup: gate.Fixture) -> AsyncIterator[None]:
    """Finish the builds a test leaves queued, so later queue tests start from an empty queue."""
    yield
    project_runs = select(PipelineRun.id).where(PipelineRun.project_id == setup.project_id)
    async with setup.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.status == JobStatus.QUEUED, Job.run_id.in_(project_runs))
            .values(status=JobStatus.FAILED, delivered=True, finished_at=func.clock_timestamp())
        )


FIRST = {"models/mart/fct_registration.sql": "select 1 as registrations"}
SECOND = {"models/mart/fct_registration.sql": "select 2 as registrations"}
REJECTED = {"models/mart/fct_registration.sql": "select * from read_csv('/etc/passwd')"}
FAILED_BUILD = ExecutionReportData(compiled=False, succeeded=False, error="Parser Error")
PASSED_BUILD = ExecutionReportData(compiled=True, succeeded=True)


def output(files: dict[str, str]) -> CodegenOutput:
    return CodegenOutput(files=[GeneratedFile(path=p, content=c) for p, c in files.items()])


@dataclass
class ScriptedCodegen:
    """Plays back Codegen outputs in order and records the repair context of every call."""

    outputs: list[CodegenOutput]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def __call__(
        self,
        *,
        design: DataDesign,
        profile: DataProfile,
        previous_files: dict[str, str] | None,
        failure_report: str | None,
        reviewer_feedback: str | None,
    ) -> CodegenOutput:
        self.calls.append({"previous_files": previous_files, "failure_report": failure_report})
        return self.outputs.pop(0)


async def fake_assembler(
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    version: int,
    design: DataDesign,
    files: list[GeneratedFile],
) -> AssembledProject:
    return AssembledProject(
        root=f"projects/{project_id}/runs/{run_id}/code/v{version}",
        code_hash=gate.fake_hash({f.path: f.content for f in files}),
        tests_hash=gate.fake_hash([]),
        files=[f.path for f in files],
    )


def reject_file_access(files: list[GeneratedFile]) -> list[str]:
    return [f"{f.path}: reads a file" for f in files if "read_csv" in f.content]


@dataclass
class Loop:
    fx: gate.Fixture
    codegen: ScriptedCodegen


def with_codegen(fx: gate.Fixture, outputs: list[dict[str, str]], budget: int = 2) -> Loop:
    codegen = ScriptedCodegen(outputs=[output(files) for files in outputs])
    fx.context = dataclasses.replace(
        fx.context,
        generate_code=codegen,
        assemble_code=fake_assembler,
        check_generated_files=reject_file_access,
        hash_report=gate.fake_hash,
        max_fix_attempts=budget,
    )
    return Loop(fx=fx, codegen=codegen)


async def approve(loop: Loop) -> uuid.UUID:
    fx = loop.fx
    run_id = await gate.reach_design_gate(fx)
    approval = DesignGateReply(user_id=fx.user_id, decision="approve")
    await gate.reply(fx, run_id, RunStatus.WAITING_DESIGN_APPROVAL, approval)
    return run_id


async def finish_build(
    loop: Loop, run_id: uuid.UUID, report: ExecutionReportData | None
) -> PipelineRun:
    fx = loop.fx
    run = await gate.load_run(fx, run_id)
    assert run.pending is not None
    assert run.pending["job_kind"] == "dbt_build"
    values: dict[str, Any] = (
        {"status": JobStatus.FAILED, "last_error": "duckdb crashed"}
        if report is None
        else {"status": JobStatus.SUCCEEDED, "result": report.model_dump(mode="json")}
    )
    async with fx.factory.begin() as session:
        await session.execute(
            update(Job)
            .where(Job.id == uuid.UUID(run.pending["job_id"]))
            .values(finished_at=func.clock_timestamp(), **values)
        )
    await deliver_finished_jobs(fx.factory, fx.graph, fx.context)
    return await gate.load_run(fx, run_id)


async def code_versions(fx: gate.Fixture, run_id: uuid.UUID) -> list[CodeVersion]:
    async with fx.factory() as session:
        query = select(CodeVersion).where(CodeVersion.run_id == run_id)
        return list((await session.scalars(query.order_by(CodeVersion.version))).all())


async def build_jobs(fx: gate.Fixture, run_id: uuid.UUID) -> list[Job]:
    async with fx.factory() as session:
        query = select(Job).where(Job.run_id == run_id, Job.kind == "dbt_build")
        return list((await session.scalars(query.order_by(Job.created_at))).all())


async def reports(fx: gate.Fixture, run_id: uuid.UUID) -> list[ExecutionReport]:
    async with fx.factory() as session:
        query = select(ExecutionReport).join(CodeVersion).where(CodeVersion.run_id == run_id)
        return list((await session.scalars(query)).all())


async def test_approved_design_is_built_once_in_the_sandbox(setup: gate.Fixture) -> None:
    loop = with_codegen(setup, [FIRST])
    run_id = await approve(loop)

    run = await gate.load_run(setup, run_id)
    assert run.status is RunStatus.WAITING_JOB
    assert run.current_step == "execute"
    versions = await code_versions(setup, run_id)
    assert [(v.version, v.origin) for v in versions] == [(1, CodeOrigin.CODEGEN)]
    jobs = await build_jobs(setup, run_id)
    assert len(jobs) == 1
    assert jobs[0].payload["code_version_id"] == str(versions[0].id)
    assert jobs[0].payload["code_dir"] == versions[0].storage_path
    assert loop.codegen.calls == [{"previous_files": None, "failure_report": None}]

    run = await finish_build(loop, run_id, PASSED_BUILD)

    stored = await reports(setup, run_id)
    assert [r.job_id for r in stored] == [jobs[0].id]
    state = (await setup.graph.aget_state(thread_config(run_id))).values
    assert state["execution_job_id"] == str(jobs[0].id)
    assert state["failure_report"] is None
    assert run.error is not None
    assert run.error.startswith("NotImplementedError")


async def test_failed_build_sends_files_and_failure_back_to_codegen(setup: gate.Fixture) -> None:
    loop = with_codegen(setup, [FIRST, SECOND])
    run_id = await approve(loop)

    run = await finish_build(loop, run_id, FAILED_BUILD)

    assert loop.codegen.calls[1] == {
        "previous_files": FIRST,
        "failure_report": "Parser Error; dbt compile failed",
    }
    assert run.status is RunStatus.WAITING_JOB
    versions = await code_versions(setup, run_id)
    assert [v.version for v in versions] == [1, 2]
    jobs = await build_jobs(setup, run_id)
    assert [j.payload["code_version_id"] for j in jobs] == [str(v.id) for v in versions]
    state = (await setup.graph.aget_state(thread_config(run_id))).values
    assert state["fix_attempts"] == 1


async def test_repairs_stop_when_the_budget_is_spent(setup: gate.Fixture) -> None:
    loop = with_codegen(setup, [FIRST, SECOND], budget=1)
    run_id = await approve(loop)

    await finish_build(loop, run_id, FAILED_BUILD)
    run = await finish_build(loop, run_id, FAILED_BUILD)

    assert run.status is RunStatus.FAILED
    assert run.error == (
        "Code still failing after 1 repair attempts: Parser Error; dbt compile failed"
    )
    assert len(loop.codegen.calls) == 2


async def test_guard_rejection_is_repaired_before_any_sandbox_job(setup: gate.Fixture) -> None:
    loop = with_codegen(setup, [REJECTED, FIRST])
    run_id = await approve(loop)

    failure = loop.codegen.calls[1]["failure_report"]
    assert failure.startswith("Guard rejected the generated files:")
    assert loop.codegen.calls[1]["previous_files"] == REJECTED
    versions = await code_versions(setup, run_id)
    assert [v.version for v in versions] == [1]
    assert len(await build_jobs(setup, run_id)) == 1


async def test_a_crashed_sandbox_job_ends_the_run(setup: gate.Fixture) -> None:
    loop = with_codegen(setup, [FIRST])
    run_id = await approve(loop)

    run = await finish_build(loop, run_id, None)

    assert run.status is RunStatus.FAILED
    assert run.error == "Sandbox build failed: duckdb crashed"
    assert len(loop.codegen.calls) == 1
    assert await reports(setup, run_id) == []
