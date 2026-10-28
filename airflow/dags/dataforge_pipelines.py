import datetime
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from airflow.sdk import DAG, task

DATA_ROOT = Path(os.environ.get("DATAFORGE_DATA_ROOT", "/data"))
CONFIG_GLOB = "projects/*/approved/*/dag_config.json"
DBT_BIN = os.environ.get("DATAFORGE_DBT_BIN", "/opt/dbt-venv/bin/dbt")


def load_pipeline_config(path: Path) -> dict[str, Any] | None:
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        required_keys = [
            "pipeline_id",
            "project_id",
            "code_version_id",
            "required_files",
            "schema_fingerprint",
        ]
        for key in required_keys:
            if key not in data:
                return None
        return data
    except Exception:
        return None


@task(retries=1440, retry_delay=datetime.timedelta(minutes=1))
def wait_for_ready_batch(config: dict[str, Any]) -> str:
    project_dir = DATA_ROOT / "projects" / config["project_id"] / "batches"
    if project_dir.exists():
        for batch_dir in sorted(project_dir.iterdir()):
            if not batch_dir.is_dir():
                continue
            ready_file = batch_dir / "_READY"
            if ready_file.exists():
                all_present = all(
                    (batch_dir / req_file).exists() for req_file in config.get("required_files", [])
                )
                if all_present:
                    return batch_dir.name
    raise RuntimeError("No ready batch found")


@task
def check_schema(config: dict[str, Any], batch_id: str) -> None:
    batch_dir = DATA_ROOT / "projects" / config["project_id"] / "batches" / batch_id
    manifest_file = batch_dir / "manifest.json"
    if manifest_file.exists():
        try:
            manifest_content = manifest_file.read_text(encoding="utf-8")
            manifest_data = json.loads(manifest_content)
            if manifest_data.get("schema_fingerprint") != config["schema_fingerprint"]:
                raise ValueError(f"Schema mismatch for batch {batch_id}")
        except json.JSONDecodeError:
            pass


@task
def dbt_build(config: dict[str, Any], batch_id: str) -> str:
    project_id = config["project_id"]
    code_version = config["code_version_id"]

    approved_dir = DATA_ROOT / "projects" / project_id / "approved" / code_version
    batch_dir = DATA_ROOT / "projects" / project_id / "batches" / batch_id
    workspace = DATA_ROOT / "projects" / project_id / "workspaces" / batch_id

    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(approved_dir, workspace)

    duckdb_path = workspace / "dataforge.duckdb"

    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(workspace)

    loaded_at = datetime.datetime.now(datetime.UTC).isoformat()

    cmd = [
        DBT_BIN,
        "build",
        "--project-dir",
        str(workspace),
        "--threads",
        str(config.get("dbt_threads", 2)),
        "--vars",
        json.dumps({"raw_dir": str(batch_dir), "batch_id": batch_id, "loaded_at": loaded_at}),
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(workspace))
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)

    return str(duckdb_path)


@task
def request_publish(config: dict[str, Any], batch_id: str, duckdb_path: str) -> None:
    payload = json.dumps(
        {"pipeline_id": config["pipeline_id"], "batch_id": batch_id, "duckdb_path": duckdb_path}
    ).encode("utf-8")

    request = urllib.request.Request(
        f"http://backend:8000/api/pipelines/{config['pipeline_id']}/publish",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request) as response:
            if response.status not in (200, 201, 202):
                raise RuntimeError(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(str(e)) from e


def build_dag(config: dict[str, Any]) -> DAG:
    dag_id = f"dataforge_pipeline_{config['pipeline_id']}"

    with DAG(
        dag_id=dag_id,
        schedule=config.get("schedule"),
        catchup=False,
        max_active_runs=1,
    ) as dag:
        b_id = wait_for_ready_batch(config)
        chk = check_schema(config, b_id)
        db = dbt_build(config, b_id)
        request_publish(config, b_id, db)

        chk >> db

    return dag


for config_path in sorted(DATA_ROOT.glob(CONFIG_GLOB)):
    pipeline_config = load_pipeline_config(config_path)
    if pipeline_config is not None:
        globals()[f"dataforge_{pipeline_config['pipeline_id']}"] = build_dag(pipeline_config)
