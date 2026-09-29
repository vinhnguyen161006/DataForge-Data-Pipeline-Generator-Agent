import uuid
from typing import Any

from fastapi import APIRouter

from app.api.schemas import MemberAdd, ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects() -> list[ProjectOut]:
    """TODO: projects the current user is a member of, with their roles."""
    raise NotImplementedError


@router.post("", response_model=ProjectOut)
async def create_project(body: ProjectCreate) -> ProjectOut:
    """TODO: create a project; creator becomes engineer (and reviewer in solo mode)."""
    raise NotImplementedError


@router.post("/{project_id}/members", status_code=204)
async def add_member(project_id: uuid.UUID, body: MemberAdd) -> None:
    """TODO: add a member with a role; engineer only."""
    raise NotImplementedError


@router.get("/{project_id}/approvals")
async def approval_history(project_id: uuid.UUID) -> list[dict[str, Any]]:
    """TODO: approval log for the project, including "no independent review" entries."""
    raise NotImplementedError
