import uuid

from fastapi import APIRouter, UploadFile

from app.api.schemas import BatchOut, ReadConfigConfirm, SourceFileOut

router = APIRouter(prefix="/projects/{project_id}/batches", tags=["batches"])


@router.post("", response_model=BatchOut)
async def create_batch(project_id: uuid.UUID) -> BatchOut:
    """TODO: open a new batch in UPLOADING state."""
    raise NotImplementedError


@router.post("/{batch_id}/files", response_model=SourceFileOut)
async def upload_file(
    project_id: uuid.UUID, batch_id: uuid.UUID, file: UploadFile
) -> SourceFileOut:
    """TODO: store the raw file unchanged, sniff read config, return preview (FR-01)."""
    raise NotImplementedError


@router.put("/{batch_id}/files/{file_id}/read-config", response_model=SourceFileOut)
async def confirm_read_config(
    project_id: uuid.UUID, batch_id: uuid.UUID, file_id: uuid.UUID, body: ReadConfigConfirm
) -> SourceFileOut:
    """TODO: save the Engineer-confirmed read config and re-render the preview."""
    raise NotImplementedError


@router.post("/{batch_id}/ready", response_model=BatchOut)
async def mark_ready(project_id: uuid.UUID, batch_id: uuid.UUID) -> BatchOut:
    """TODO: mark the batch ready once every file is confirmed."""
    raise NotImplementedError
