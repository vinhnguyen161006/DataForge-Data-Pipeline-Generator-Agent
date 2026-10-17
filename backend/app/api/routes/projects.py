import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CurrentUserDep,
    SessionDep,
    require_project_member,
    require_role,
)
from app.api.schemas import (
    ApprovalHistoryOut,
    MemberAdd,
    ProjectCreate,
    ProjectOut,
)
from app.db.models import (
    Approval,
    Project,
    ProjectMember,
    ProjectRole,
    ReviewMode,
    User,
)

router = APIRouter(prefix="/projects", tags=["projects"])

EngineerDep = Annotated[
    User,
    Depends(require_role(ProjectRole.ENGINEER)),
]

ProjectMemberDep = Annotated[
    User,
    Depends(require_project_member),
]


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: CurrentUserDep,
    session: SessionDep,
) -> list[ProjectOut]:
    """List member projects once, including the current user's roles."""
    result = await session.execute(
        select(Project, ProjectMember.role)
        .join(
            ProjectMember,
            ProjectMember.project_id == Project.id,
        )
        .where(ProjectMember.user_id == user.id)
        .order_by(
            Project.created_at,
            Project.id,
            ProjectMember.role,
        )
    )

    projects_by_id: dict[uuid.UUID, ProjectOut] = {}

    for project, role in result:
        output = projects_by_id.get(project.id)

        if output is None:
            output = ProjectOut(
                id=project.id,
                name=project.name,
                slug=project.slug,
                review_mode=project.review_mode,
                roles=[],
            )
            projects_by_id[project.id] = output

        output.roles.append(role)

    return list(projects_by_id.values())


@router.post("", response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    user: CurrentUserDep,
    session: SessionDep,
) -> ProjectOut:
    """Create a project and its creator memberships atomically."""
    project = Project(
        name=body.name,
        slug=body.slug,
        review_mode=body.review_mode,
        created_by=user.id,
    )

    roles = [ProjectRole.ENGINEER]
    if body.review_mode == ReviewMode.SOLO:
        roles.append(ProjectRole.REVIEWER)

    try:
        session.add(project)
        await session.flush()

        session.add_all(
            [
                ProjectMember(
                    project_id=project.id,
                    user_id=user.id,
                    role=role,
                )
                for role in roles
            ]
        )
        await session.flush()

        response = ProjectOut(
            id=project.id,
            name=project.name,
            slug=project.slug,
            review_mode=project.review_mode,
            roles=roles,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()

        if _is_duplicate_slug(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Project slug already exists",
            ) from exc

        raise
    except Exception:
        await session.rollback()
        raise

    return response


@router.post("/{project_id}/members", status_code=204)
async def add_member(
    project_id: uuid.UUID,
    body: MemberAdd,
    _engineer: EngineerDep,
    session: SessionDep,
) -> None:
    """Grant a project role while enforcing team separation."""
    try:
        project = await session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )

        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        target = await session.scalar(select(User).where(User.email == body.email))

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        existing = await session.get(
            ProjectMember,
            (project.id, target.id, body.role),
        )

        if existing is not None:
            await session.commit()
            return

        if project.review_mode == ReviewMode.TEAM:
            opposite_role = (
                ProjectRole.REVIEWER if body.role == ProjectRole.ENGINEER else ProjectRole.ENGINEER
            )

            opposite_membership = await session.scalar(
                select(ProjectMember.role).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == target.id,
                    ProjectMember.role == opposite_role,
                )
            )

            if opposite_membership is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Team members cannot hold both project roles",
                )

        await session.execute(
            insert(ProjectMember)
            .values(
                project_id=project.id,
                user_id=target.id,
                role=body.role,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ProjectMember.project_id,
                    ProjectMember.user_id,
                    ProjectMember.role,
                ]
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@router.get(
    "/{project_id}/approvals",
    response_model=list[ApprovalHistoryOut],
)
async def approval_history(
    project_id: uuid.UUID,
    _member: ProjectMemberDep,
    session: SessionDep,
) -> list[ApprovalHistoryOut]:
    """Return project approval history with recorded review independence."""
    approvals = await session.scalars(
        select(Approval)
        .where(Approval.project_id == project_id)
        .order_by(
            Approval.created_at.desc(),
            Approval.id.desc(),
        )
    )

    return [
        ApprovalHistoryOut(
            id=approval.id,
            project_id=approval.project_id,
            run_id=approval.run_id,
            gate=approval.gate,
            decision=approval.decision,
            approver_id=approval.approver_id,
            independent_review=approval.independent_review,
            fingerprint=approval.fingerprint,
            comment=approval.comment,
            created_at=approval.created_at,
            review_note=(None if approval.independent_review else "No independent review"),
        )
        for approval in approvals
    ]


def _is_duplicate_slug(exc: IntegrityError) -> bool:
    """Identify the project slug unique violation from asyncpg."""
    driver_error = getattr(exc.orig, "__cause__", None)
    return (
        getattr(driver_error, "sqlstate", None) == "23505"
        and getattr(driver_error, "constraint_name", None) == "uq_projects_slug"
    )
