from pathlib import Path

from pydantic import BaseModel

from app.agents.schemas import DataDesign, GeneratedFile
from app.ingest.sniff import CsvReadConfig

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "dbt_project"


class DagConfig(BaseModel):
    pipeline_id: str
    project_id: str
    code_version_id: str
    schedule: str | None = None
    required_files: list[str]
    schema_fingerprint: str
    dbt_threads: int = 2


class AssembledProject(BaseModel):
    root: str
    code_hash: str
    tests_hash: str
    files: list[str]


def assemble_project(
    dest: Path,
    *,
    project_name: str,
    code_version: str,
    design: DataDesign,
    read_configs: dict[str, CsvReadConfig],
    llm_files: list[GeneratedFile],
    dag_config: DagConfig,
    threads: int = 2,
) -> AssembledProject:
    """TODO: write one complete dbt project version to dest and hash it.

    Sources: TEMPLATE_DIR (dbt_project.yml, profiles.yml, macros), bronze models,
    schema tests from approved constraints, guarded LLM files, dag_config.json,
    design.json, read_configs.json. Compute code_hash and tests_hash separately.
    """
    raise NotImplementedError
