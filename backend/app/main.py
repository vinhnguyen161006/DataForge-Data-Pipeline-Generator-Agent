from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, batches, exports, health, projects, runs
from app.core.config import get_api_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """TODO: create engine/sessionmaker, open AsyncPostgresSaver and build the graph.

    Then call recover_pending_runs and start a background loop running
    deliver_finished_jobs; close everything on shutdown.
    """
    yield


def create_app() -> FastAPI:
    settings = get_api_settings()
    app = FastAPI(title="DataForge", lifespan=lifespan)
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
