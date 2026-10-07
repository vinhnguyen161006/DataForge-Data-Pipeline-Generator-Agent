import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.api.routes import auth, batches, exports, health, projects, runs
from app.core.config import ApiSettings, get_api_settings
from app.core.logging import configure_logging
from app.db.checkpointer import open_postgres_checkpointer
from app.db.session import make_engine, make_sessionmaker
from app.graph.builder import build_graph

CheckpointerFactory = Callable[[str], AbstractAsyncContextManager[BaseCheckpointSaver[str]]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

logger = logging.getLogger(__name__)


def make_lifespan(settings: ApiSettings, open_checkpointer: CheckpointerFactory) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Own the process-wide resources and release them on shutdown.

        Exposes app.state.sessionmaker and app.state.graph to request dependencies.

        TODO: call recover_pending_runs on startup and run deliver_finished_jobs in a background
        loop once app.services.runs implements them (FR-21).
        """
        engine = make_engine(settings.app_database_url)
        try:
            async with open_checkpointer(settings.checkpoint_database_url) as checkpointer:
                app.state.sessionmaker = make_sessionmaker(engine)
                app.state.graph = build_graph(checkpointer)
                logger.info("api resources ready")
                yield
        finally:
            await engine.dispose()
            logger.info("api resources released")

    return lifespan


def create_app(open_checkpointer: CheckpointerFactory = open_postgres_checkpointer) -> FastAPI:
    settings = get_api_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="DataForge", lifespan=make_lifespan(settings, open_checkpointer))
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
