import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.llm import StructuredLLM
from app.api.routes import auth, batches, exports, health, projects, runs
from app.core.config import ApiSettings, get_api_settings
from app.core.logging import configure_logging
from app.core.readiness import JobDeliveryStatus
from app.db.checkpointer import open_postgres_checkpointer
from app.db.session import make_engine, make_sessionmaker
from app.graph.builder import PipelineGraph, build_graph
from app.graph.context import GraphContext, make_graph_context
from app.services.delivery_lifecycle import (
    observe_delivery,
    stop_delivery,
    wait_for_delivery_startup,
)
from app.services.runs import job_delivery_loop

CheckpointerFactory = Callable[[str], AbstractAsyncContextManager[BaseCheckpointSaver[str]]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
GraphBuilder = Callable[[BaseCheckpointSaver[str]], PipelineGraph]
ContextBuilder = Callable[[async_sessionmaker[AsyncSession], StructuredLLM], GraphContext]

logger = logging.getLogger(__name__)


def make_llm(settings: ApiSettings) -> StructuredLLM:
    return StructuredLLM(
        api_key=settings.gemini_api_key.get_secret_value(), model=settings.gemini_model
    )


@asynccontextmanager
async def job_delivery(
    settings: ApiSettings,
    sessionmaker: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    *,
    status: JobDeliveryStatus | None = None,
) -> AsyncIterator[None]:
    """Wait for recovery before serving and join delivery before closing its resources."""
    delivery_status = status or JobDeliveryStatus(enabled=settings.job_delivery_enabled)
    if not settings.job_delivery_enabled:
        yield
        return
    startup_ready = asyncio.Event()
    task = asyncio.create_task(
        job_delivery_loop(
            sessionmaker,
            graph,
            context,
            interval_seconds=settings.job_delivery_interval_seconds,
            startup_ready=startup_ready,
        )
    )
    observe_delivery(task, delivery_status)
    try:
        await wait_for_delivery_startup(
            task,
            startup_ready,
            timeout_seconds=settings.job_delivery_startup_timeout_seconds,
        )
        delivery_status.ready = True
        yield
    finally:
        await stop_delivery(task, delivery_status)


def make_lifespan(
    settings: ApiSettings,
    open_checkpointer: CheckpointerFactory,
    *,
    graph_builder: GraphBuilder | None = None,
    context_builder: ContextBuilder | None = None,
) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the process-wide resources and release them on shutdown.

        Exposes app.state.sessionmaker, app.state.graph and app.state.graph_context to
        request dependencies, and runs the job delivery loop that also recovers runs left
        unfinished by a restart (FR-21).
        """
        delivery_status = JobDeliveryStatus(enabled=settings.job_delivery_enabled)
        app.state.job_delivery_status = delivery_status
        engine = make_engine(settings.app_database_url)
        try:
            async with open_checkpointer(settings.checkpoint_database_url) as checkpointer:
                sessionmaker = make_sessionmaker(engine)
                graph = (graph_builder or build_graph)(checkpointer)
                context = (context_builder or make_graph_context)(sessionmaker, make_llm(settings))
                app.state.sessionmaker = sessionmaker
                app.state.graph = graph
                app.state.graph_context = context
                async with job_delivery(
                    settings, sessionmaker, graph, context, status=delivery_status
                ):
                    logger.info("api resources ready")
                    yield
        finally:
            await engine.dispose()
            logger.info("api resources released")

    return lifespan


def create_app(
    open_checkpointer: CheckpointerFactory = open_postgres_checkpointer,
    *,
    graph_builder: GraphBuilder | None = None,
    context_builder: ContextBuilder | None = None,
) -> FastAPI:
    settings = get_api_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="DataForge",
        lifespan=make_lifespan(
            settings,
            open_checkpointer,
            graph_builder=graph_builder,
            context_builder=context_builder,
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        health.router,
        auth.router,
        projects.router,
        batches.router,
        runs.router,
        exports.router,
    ):
        app.include_router(router, prefix="/api")
    return app
