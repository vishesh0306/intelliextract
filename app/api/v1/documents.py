import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit
from app.core.config import get_settings
from app.db.session import get_db
from app.models import ApiKey, Job, JobStatus
from app.schemas.document import DocumentType, DocumentUploadResponse
from app.services.file_validation import EXTENSION_BY_CONTENT_TYPE, sniff_content_type
from app.storage.factory import get_storage_backend

router = APIRouter()


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    api_key: Annotated[ApiKey, Depends(enforce_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    document_type: Annotated[DocumentType, Form()],
) -> DocumentUploadResponse:
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    # Reject early from the Content-Length header when present, before
    # buffering the body into memory at all.
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb}MB upload limit",
        )

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb}MB upload limit",
        )

    content_type = sniff_content_type(content)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type; expected PDF, PNG, or JPEG",
        )

    file_hash = hashlib.sha256(content).hexdigest()
    storage_key = f"{file_hash}{EXTENSION_BY_CONTENT_TYPE[content_type]}"

    storage = get_storage_backend()
    await storage.save(storage_key, content)

    job = Job(
        api_key_id=api_key.id,
        document_type=document_type.value,
        file_hash=file_hash,
        s3_key=storage_key,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()

    return DocumentUploadResponse(job_id=job.id, status=job.status)
