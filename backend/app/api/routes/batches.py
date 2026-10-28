import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import SessionDep, require_role
from app.api.schemas import BatchCreate, BatchOut, ReadConfigConfirm, SourceFileOut
from app.core.config import get_api_settings
from app.db.models import ProjectRole, User
from app.ingest.storage import Storage
from app.services import batches

router = APIRouter(prefix="/projects/{project_id}/batches", tags=["batches"])
EngineerDep = Annotated[User, Depends(require_role(ProjectRole.ENGINEER))]


def get_storage() -> Storage:
    return Storage(get_api_settings().storage_root)


@router.post("", response_model=BatchOut)
async def create_batch(
    project_id: uuid.UUID, body: BatchCreate, _engineer: EngineerDep, session: SessionDep
) -> BatchOut:
    """Declare the complete input file set before any bytes are uploaded."""
    try:
        batch = await batches.create_batch(
            session, project_id=project_id, required_files=body.required_files
        )
        response = await batches.batch_out(session, get_storage(), batch)
        await session.commit()
        return response
    except Exception:
        await session.rollback()
        raise


@router.post("/{batch_id}/files", response_model=SourceFileOut)
async def upload_file(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    file: UploadFile,
    _engineer: EngineerDep,
    session: SessionDep,
) -> SourceFileOut:
    """Store original bytes and return an unconfirmed CSV reading proposal."""
    try:
        await file.seek(0)
        response = await batches.upload_file(
            session,
            get_storage(),
            project_id=project_id,
            batch_id=batch_id,
            filename=file.filename or "",
            stream=file.file,
            max_bytes=get_api_settings().max_upload_bytes,
        )
        await session.commit()
        return response
    except batches.BatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await file.close()


@router.put("/{batch_id}/files/{file_id}/read-config", response_model=SourceFileOut)
async def confirm_read_config(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    body: ReadConfigConfirm,
    _engineer: EngineerDep,
    session: SessionDep,
) -> SourceFileOut:
    """Confirm the submitted config only after rendering its preview without resniffing."""
    try:
        response = await batches.confirm_read_config(
            session,
            get_storage(),
            project_id=project_id,
            batch_id=batch_id,
            file_id=file_id,
            config=body.read_config,
        )
        await session.commit()
        return response
    except batches.BatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise


@router.post("/{batch_id}/ready", response_model=BatchOut)
async def mark_ready(
    project_id: uuid.UUID, batch_id: uuid.UUID, _engineer: EngineerDep, session: SessionDep
) -> BatchOut:
    """Commit the immutable snapshot before publishing its marker; retries complete publication."""
    storage = get_storage()
    try:
        response = await batches.mark_batch_ready(
            session, storage, project_id=project_id, batch_id=batch_id
        )
        await session.commit()
        await batches.publish_ready_marker(
            session, storage, project_id=project_id, batch_id=batch_id
        )
        await session.commit()
        return response
    except batches.BatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
