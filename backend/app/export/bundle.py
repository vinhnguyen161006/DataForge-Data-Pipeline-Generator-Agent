from pathlib import Path

from pydantic import BaseModel


class ExportManifest(BaseModel):
    project_slug: str
    code_version_id: str
    approval_fingerprint: str
    files: dict[str, str]


def build_export_tree(approved_dir: Path, dest: Path, manifest: ExportManifest) -> None:
    """TODO: lay out the standalone project (FR-18).

    dbt project, schema tests and macros, CSV loader + source manifest,
    scripts/publish_to_postgres.py, dashboard config + rebuild script,
    Dockerfile + compose with pinned versions, the DAG file, version manifest
    and verification report. Must not call any platform API at runtime.
    """
    raise NotImplementedError


def build_zip(tree: Path, zip_path: Path) -> str:
    """TODO: deterministic ZIP (sorted entries, fixed timestamps); return its sha256.

    The ZIP and the pull request must contain the same approved version.
    """
    raise NotImplementedError
