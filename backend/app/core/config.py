from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
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
    max_upload_bytes: int = Field(default=1024 * 1024 * 1024, gt=0, le=2147483647)
    job_delivery_enabled: bool = True
    job_delivery_interval_seconds: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    job_delivery_startup_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "pipeline_examples"
    retrieval_top_k: int = 3

    github_token: SecretStr = SecretStr("")

    optimizer: OptimizerBudget = Field(default_factory=OptimizerBudget)


class WorkerSettings(BaseProcessSettings):
    worker_id: str = Field(default="sandbox-1", min_length=1, max_length=128)
    poll_interval_seconds: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    lease_seconds: int = Field(default=300, gt=0)
    heartbeat_interval_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    database_timeout_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    run_timeout_seconds: int = Field(default=900, gt=0)
    run_memory_mb: int = Field(default=2048, gt=0)
    run_cpu_seconds: int = Field(default=900, gt=0)
    run_max_file_mb: int = Field(default=2048, gt=0)
    run_max_processes: int = Field(default=4096, gt=0)
    duckdb_threads: int = Field(default=2, gt=0, le=64)
    duckdb_memory_mb: int = Field(default=256, gt=0)
    duckdb_max_temp_mb: int = Field(default=512, gt=0)

    @model_validator(mode="after")
    def validate_lease_budget(self) -> "WorkerSettings":
        if not self.worker_id.strip():
            raise ValueError("worker_id cannot be blank")
        if self.heartbeat_interval_seconds + self.database_timeout_seconds >= self.lease_seconds:
            raise ValueError(
                "The heartbeat interval and database timeout must fit inside the lease"
            )
        if self.duckdb_memory_mb >= self.run_memory_mb:
            raise ValueError("DuckDB memory must leave room inside the process memory limit")
        return self


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
