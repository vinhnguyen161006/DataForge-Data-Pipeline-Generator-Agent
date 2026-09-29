import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.schemas import PullRequestCreate

router = APIRouter(prefix="/projects/{project_id}/runs/{run_id}/export", tags=["export"])


@router.get("/zip")
async def download_zip(project_id: uuid.UUID, run_id: uuid.UUID) -> FileResponse:
    """TODO: build (or reuse) the deterministic ZIP of the approved version (FR-18)."""
    raise NotImplementedError


@router.post("/pull-request")
async def open_pull_request(
    project_id: uuid.UUID, run_id: uuid.UUID, body: PullRequestCreate
) -> dict[str, Any]:
    """TODO: open a PR with the same approved tree as the ZIP; never merge (FR-19)."""
    raise NotImplementedError
