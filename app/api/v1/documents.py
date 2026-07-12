import hashlib
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit
from app.core.config import get_settings
from app.db.session import get_db
from app.models import ApiKey, Job, JobResult, JobStatus
from app.schemas.document import DocumentType, DocumentUploadResponse, JobStatusResponse
from app.services.file_validation import EXTENSION_BY_CONTENT_TYPE, sniff_content_type
from app.storage.factory import get_storage_backend
from app.worker.queue import get_task_queue
from app.worker.tasks import process_document

router = APIRouter()


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    response: Response,
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

    cached_job = await _find_cache_hit(db, file_hash=file_hash, document_type=document_type)
    if cached_job is not None:
        new_job = await _clone_from_cache(db, cached_job=cached_job, api_key=api_key)
        response.status_code = status.HTTP_200_OK
        return DocumentUploadResponse(job_id=new_job.id, status=new_job.status, cached=True)

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

    get_task_queue().enqueue(process_document, str(job.id))

    return DocumentUploadResponse(job_id=job.id, status=job.status, cached=False)


async def _find_cache_hit(
    db: AsyncSession, *, file_hash: str, document_type: DocumentType
) -> Job | None:
    """Only a DONE job counts as cacheable — a FAILED job has no usable
    result, and NEEDS_REVIEW hasn't earned enough trust to hand back
    silently. document_type is part of the key because a given file's
    processing (and whether it even gets AI extraction) depends on it.
    """
    return await db.scalar(
        select(Job)
        .where(
            Job.file_hash == file_hash,
            Job.document_type == document_type.value,
            Job.status == JobStatus.DONE,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )


async def _clone_from_cache(db: AsyncSession, *, cached_job: Job, api_key: ApiKey) -> Job:
    """Creates a new job owned by the requesting key rather than handing
    back the original job_id — the original may belong to a different API
    key, and GET /documents/{id} is scoped to the owning key. The file
    itself isn't re-saved: storage keys are content-addressed, so the
    identical bytes are already sitting at cached_job.s3_key.
    """
    new_job = Job(
        api_key_id=api_key.id,
        document_type=cached_job.document_type,
        file_hash=cached_job.file_hash,
        s3_key=cached_job.s3_key,
        status=JobStatus.DONE,
    )
    db.add(new_job)
    await db.flush()

    cached_result = await db.get(JobResult, cached_job.id)
    if cached_result is not None:
        db.add(
            JobResult(
                job_id=new_job.id,
                raw_text=cached_result.raw_text,
                extracted_json=cached_result.extracted_json,
                confidence_scores=cached_result.confidence_scores,
            )
        )

    await db.commit()
    return new_job


@router.get("/documents/{job_id}", response_model=JobStatusResponse)
async def get_document(
    job_id: uuid.UUID,
    api_key: Annotated[ApiKey, Depends(enforce_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JobStatusResponse:
    job = await db.get(Job, job_id)
    if job is None or job.api_key_id != api_key.id:
        # Same 404 either way — confirming a job ID belongs to someone
        # else's key is itself an information leak.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        document_type=job.document_type,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
