from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, batches, exports, health, projects, runs
from app.core.config import get_api_settings
from app.db.session import make_engine, make_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database resources for the application lifetime."""
    settings = get_api_settings()
    engine = make_engine(settings.app_database_url)

    try:
        app.state.sessionmaker = make_sessionmaker(engine)
        yield
    finally:
        await engine.dispose()


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
