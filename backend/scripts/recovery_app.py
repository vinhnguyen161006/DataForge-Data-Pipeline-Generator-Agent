"""Deterministic gate recovery application, enabled only by the dedicated Compose override."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.agents.schemas import DataDesign, ModelerOutput
from app.core.config import get_api_settings
from app.db.checkpointer import open_postgres_checkpointer
from app.db.models import Approval, Batch, DesignVersion, Job, PipelineRun, RunResumeIntent
from app.db.session import make_engine, make_sessionmaker
from app.graph import design_store, nodes
from app.graph.context import GraphContext
from app.graph.state import PipelineState
from app.ingest.storage import Storage
from app.main import create_app as create_api
from app.services.runs import thread_config

if TYPE_CHECKING:
    from fastapi import FastAPI
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.runtime import Runtime
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.agents.llm import StructuredLLM
    from app.graph.builder import PipelineGraph
    from app.profiler.schemas import DataProfile

BOOT_ID = str(uuid4())
DATABASE = "dataforge_recovery"


def require_drill_settings() -> None:
    settings = get_api_settings()
    if os.environ.get("DATAFORGE_RECOVERY_DRILL") != "true":
        raise RuntimeError("The recovery application requires explicit drill configuration")
    if (
        make_url(settings.app_database_url).database != DATABASE
        or make_url(settings.checkpoint_database_url).database != DATABASE
    ):
        raise RuntimeError("The recovery application requires the dedicated recovery database")
    if Path(settings.storage_root).name != "recovery-drill":
        raise RuntimeError("The recovery application requires dedicated drill storage")
    if not settings.job_delivery_enabled:
        raise RuntimeError("The recovery application requires startup recovery and delivery")


def record_event(kind: str, run_id: str | None = None) -> None:
    root = Path(get_api_settings().storage_root)
    root.mkdir(parents=True, exist_ok=True)
    event = {
        "kind": kind,
        "run_id": run_id,
        "boot_id": BOOT_ID,
        "time": datetime.now(UTC).isoformat(),
    }
    with (root / "observations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")


def orders_design() -> DataDesign:
    return DataDesign.model_validate(
        {
            "facts": [
                {
                    "name": "fct_orders",
                    "grain": "One order identified by order_id",
                    "source_tables": ["orders"],
                    "measures": ["order_count"],
                    "dimension_keys": ["customer_id"],
                    "rationale": "A fixed design for the synthetic recovery fixture",
                }
            ],
            "dimensions": [
                {
                    "name": "dim_customers",
                    "business_key": ["customer_id"],
                    "source_table": "customers",
                    "attributes": ["customer_name", "city"],
                    "rationale": "Preserve the fixture customer identifiers as text",
                }
            ],
            "keys": [
                {
                    "table": "orders",
                    "columns": ["order_id"],
                    "kind": "business",
                    "rationale": "The synthetic fixture declares one order per identifier",
                },
                {
                    "table": "customers",
                    "columns": ["customer_id"],
                    "kind": "business",
                    "rationale": "The synthetic fixture declares one customer per identifier",
                },
            ],
            "relationships": [
                {
                    "child_table": "orders",
                    "child_columns": ["customer_id"],
                    "parent_table": "customers",
                    "parent_columns": ["customer_id"],
                    "cardinality": "many_to_one",
                    "rationale": "The fixture orders reference the declared customers",
                }
            ],
            "metrics": [
                {
                    "name": "order_count",
                    "definition": "Number of fixture orders",
                    "expression": "count(*)",
                    "fact_table": "fct_orders",
                    "rationale": "A deterministic metric for exercising gate approval",
                }
            ],
            "cleaning_rules": [
                {
                    "table": "orders",
                    "columns": ["order_id", "customer_id"],
                    "condition": "order_id IS NULL OR customer_id IS NULL",
                    "action": "quarantine",
                    "rationale": "Incomplete fixture identifiers must remain visible",
                }
            ],
            "update_policy": {
                "mode": "snapshot_replace",
                "required_files": ["customers.csv", "orders.csv"],
                "rationale": "Both files form one complete synthetic snapshot",
            },
            "dashboard": {
                "metrics": ["order_count"],
                "dimensions": [],
                "filters": [],
                "cards": [
                    {
                        "key": "orders",
                        "title": "Fixture orders",
                        "type": "kpi",
                        "metric": "order_count",
                    }
                ],
                "rationale": "A KPI requirement is enough for the recovery fixture",
            },
            "constraints": [],
        }
    )


async def propose_design(
    *,
    request_text: str,
    profile: DataProfile,
    answers: list[dict[str, str]],
    returned_design: DataDesign | None,
    reviewer_feedback: str | None,
) -> ModelerOutput:
    sources = {table.source_file for table in profile.tables}
    if sources != {"customers.csv", "orders.csv"}:
        raise ValueError("The recovery Modeler accepts only the two synthetic fixture files")
    design = orders_design()
    if reviewer_feedback:
        design.assumptions.append("Revised after fixture feedback: " + reviewer_feedback)
    return ModelerOutput(design=design)


def make_context(factory: async_sessionmaker[AsyncSession], llm: StructuredLLM) -> GraphContext:
    return GraphContext(sessionmaker=factory, propose_design=propose_design)


def build_graph(saver: BaseCheckpointSaver[str]) -> PipelineGraph:
    graph: StateGraph[PipelineState, GraphContext, PipelineState, PipelineState] = StateGraph(
        PipelineState, context_schema=GraphContext
    )

    async def modeler(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
        record_event("modeler_called", state["run_id"])
        return await nodes.modeler_node(state, runtime)

    async def codegen_probe(state: PipelineState, runtime: Runtime[GraphContext]) -> dict[str, Any]:
        if not state.get("design_approved"):
            raise RuntimeError("The recovery probe requires an approved design")
        async with runtime.context.sessionmaker() as session:
            await design_store.assert_design_approved(session, UUID(state["design_version_id"]))
        record_event("codegen_probe", state["run_id"])
        return {}

    graph.add_node("profile", nodes.profile_node)
    graph.add_node("modeler", modeler)
    graph.add_node("clarify", nodes.clarify_node)
    graph.add_node("design_gate", nodes.design_gate_node)
    graph.add_node("codegen", codegen_probe)
    graph.add_edge(START, "profile")
    graph.add_conditional_edges("profile", nodes.route_after_profile)
    graph.add_conditional_edges("modeler", nodes.route_after_modeler)
    graph.add_edge("clarify", "modeler")
    graph.add_conditional_edges("design_gate", nodes.route_after_design_gate)
    graph.add_edge("codegen", END)
    return graph.compile(checkpointer=saver)


def create_app() -> FastAPI:
    require_drill_settings()
    record_event("app_created")
    return create_api(graph_builder=build_graph, context_builder=make_context)


async def snapshot(run_id: str) -> dict[str, Any]:
    """Read committed records and the actual PostgreSQL interrupt through fresh connections."""
    require_drill_settings()
    identity = UUID(run_id)
    settings = get_api_settings()
    engine = make_engine(settings.app_database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            run = await session.get(PipelineRun, identity)
            if run is None:
                raise ValueError("Recovery run does not exist")
            batch = await session.get(Batch, run.batch_id)
            if batch is None:
                raise ValueError("Recovery batch does not exist")
            jobs = list(
                await session.scalars(select(Job).where(Job.run_id == identity).order_by(Job.id))
            )
            designs = list(
                await session.scalars(
                    select(DesignVersion)
                    .where(DesignVersion.run_id == identity)
                    .order_by(DesignVersion.version)
                )
            )
            approvals = list(
                await session.scalars(
                    select(Approval)
                    .where(Approval.run_id == identity)
                    .order_by(Approval.created_at, Approval.id)
                )
            )
            intents = list(
                await session.scalars(
                    select(RunResumeIntent)
                    .where(RunResumeIntent.run_id == identity)
                    .order_by(RunResumeIntent.created_at, RunResumeIntent.id)
                )
            )
        storage = Storage(settings.storage_root)
        async with open_postgres_checkpointer(settings.checkpoint_database_url) as saver:
            checkpoint = await build_graph(saver).aget_state(thread_config(identity))
        observations = storage.root / "observations.jsonl"
        events = [
            event
            for line in observations.read_text().splitlines()
            if (event := json.loads(line))["run_id"] == run_id
        ]
        return {
            "run": {
                "id": str(run.id),
                "project_id": str(run.project_id),
                "batch_id": str(run.batch_id),
                "status": run.status.value,
                "current_step": run.current_step,
                "pending": run.pending,
                "interrupt_id": run.interrupt_id,
                "error": run.error,
            },
            "batch": {
                "status": batch.status.value,
                "manifest_sha256": batch.manifest_sha256,
                "marker_exists": storage.marker_path(run.project_id, run.batch_id).is_file(),
            },
            "checkpoint": {
                "thread_id": checkpoint.config["configurable"]["thread_id"],
                "checkpoint_id": checkpoint.config["configurable"].get("checkpoint_id"),
                "values": checkpoint.values,
                "next": list(checkpoint.next),
                "interrupts": [
                    {"id": interrupt.id, "value": interrupt.value}
                    for task in checkpoint.tasks
                    for interrupt in task.interrupts
                ],
            },
            "jobs": [
                {
                    "id": str(job.id),
                    "kind": job.kind,
                    "status": job.status.value,
                    "attempts": job.attempts,
                    "delivered": job.delivered,
                    "result": job.result,
                }
                for job in jobs
            ],
            "designs": [
                {
                    "id": str(design.id),
                    "version": design.version,
                    "hash": design.content_hash,
                    "content": design.content,
                }
                for design in designs
            ],
            "approvals": [
                {
                    "id": str(approval.id),
                    "decision": approval.decision.value,
                    "actor_id": str(approval.approver_id),
                    "fingerprint": approval.fingerprint,
                    "parts": approval.fingerprint_parts,
                }
                for approval in approvals
            ],
            "intents": [
                {
                    "id": str(intent.id),
                    "interrupt_id": intent.interrupt_id,
                    "delivered": intent.delivered,
                }
                for intent in intents
            ],
            "events": events,
        }
    finally:
        await engine.dispose()
