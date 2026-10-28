import hashlib
import json
import shutil
from pathlib import Path

import jinja2
from pydantic import BaseModel

from app.agents.schemas import DataDesign, GeneratedFile
from app.codegen.bronze import bronze_models
from app.codegen.tests import schema_yml
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


def compute_hash(paths: list[Path], base_dir: Path) -> str:
    hasher = hashlib.sha256()
    for p in sorted(paths):
        hasher.update(p.relative_to(base_dir).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(p.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


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
    """Write one complete dbt project version to dest and hash it."""
    dest.mkdir(parents=True, exist_ok=True)

    code_files: list[Path] = []
    test_files: list[Path] = []
    all_written_files: list[str] = []

    def write_file(rel_path: str, content: str, is_test: bool = False) -> None:
        p = dest / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        all_written_files.append(rel_path)
        if is_test:
            test_files.append(p)
        else:
            code_files.append(p)

    write_file("design.json", design.model_dump_json(indent=2))
    write_file("dag_config.json", dag_config.model_dump_json(indent=2))

    configs_dict = {k: v.model_dump() for k, v in read_configs.items()}
    write_file("read_configs.json", json.dumps(configs_dict, indent=2))

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

    dbt_project_content = env.get_template("dbt_project.yml.j2").render(
        project_name=project_name, code_version=code_version
    )
    write_file("dbt_project.yml", dbt_project_content)

    profiles_content = env.get_template("profiles.yml.j2").render(
        project_name=project_name, threads=threads
    )
    write_file("profiles.yml", profiles_content)

    macros_src = TEMPLATE_DIR / "macros"
    if macros_src.exists():
        shutil.copytree(macros_src, dest / "macros", dirs_exist_ok=True)
        for p in (dest / "macros").rglob("*"):
            if p.is_file():
                rel_path = p.relative_to(dest).as_posix()
                all_written_files.append(rel_path)
                code_files.append(p)

    bronze_dict = bronze_models(read_configs)
    for rel_path, content in bronze_dict.items():
        write_file(rel_path, content)

    for gf in llm_files:
        write_file(gf.path, gf.content)

    schemas = schema_yml(design)
    for rel_path, content in schemas.items():
        write_file(rel_path, content, is_test=True)

    code_hash = compute_hash(code_files, dest)
    tests_hash = compute_hash(test_files, dest)

    return AssembledProject(
        root=str(dest),
        code_hash=code_hash,
        tests_hash=tests_hash,
        files=sorted(all_written_files),
    )
