from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import LogLevel


class BaseProcessSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DATAFORGE_", extra="ignore")

    app_database_url: str = "postgresql+asyncpg://dataforge:dataforge@localhost:5432/dataforge_app"
    storage_root: Path = Path("./data")
    log_level: LogLevel = "INFO"


class OptimizerBudget(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATAFORGE_OPT_", extra="ignore")

    max_candidates: int = 5
    max_fix_attempts: int = 2
    max_seconds: int = 600
    benchmark_repeats: int = 5
    min_relative_improvement: float = 0.10


class ApiSettings(BaseProcessSettings):
    checkpoint_database_url: str = "postgresql://dataforge:dataforge@localhost:5432/dataforge_app"

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_ttl_minutes: int = 720
    cors_origins: list[str] = ["http://localhost:5173"]

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-001"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "pipeline_examples"
    retrieval_top_k: int = 3

    github_token: SecretStr = SecretStr("")

    optimizer: OptimizerBudget = Field(default_factory=OptimizerBudget)


class WorkerSettings(BaseProcessSettings):
    worker_id: str = "sandbox-1"
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 300
    run_timeout_seconds: int = 900
    run_memory_mb: int = 2048
    run_cpu_seconds: int = 900
    run_max_file_mb: int = 2048
    duckdb_threads: int = 2


class PublisherSettings(BaseProcessSettings):
    worker_id: str = "publisher-1"
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 600

    warehouse_dsn: SecretStr = SecretStr(
        "postgresql://publisher:publisher@localhost:5432/dataforge_warehouse"
    )

    metabase_url: str = "http://localhost:3000"
    metabase_user: str = "admin@dataforge.local"
    metabase_password: SecretStr = SecretStr("")
    metabase_database_id: int | None = None


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()
