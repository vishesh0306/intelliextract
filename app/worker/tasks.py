import asyncio
import uuid

from app.db.session import async_session_factory
from app.models import Job, JobAttempt, JobResult, JobStatus
from app.services.extraction import extract_text
from app.services.file_validation import sniff_content_type
from app.storage.factory import get_storage_backend


def process_document(job_id: str) -> None:
    """RQ entrypoint. RQ workers call plain sync functions, so this bridges
    into our async DB layer with asyncio.run() rather than duplicating a
    sync engine just for the worker.
    """
    asyncio.run(run_extraction(uuid.UUID(job_id)))


async def run_extraction(job_id: uuid.UUID) -> None:
    """Phase 5's only real stage: fetch the stored file, extract its text
    (native PDF layer, falling back to OCR), and store it. No AI/validation
    stage exists yet, so a successful extraction is DONE for now — Phase 6
    onward inserts EXTRACTING_AI/VALIDATING between EXTRACTING and DONE.
    """
    async with async_session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.EXTRACTING
        await session.commit()

        content = await get_storage_backend().read(job.s3_key)
        content_type = sniff_content_type(content)

        try:
            raw_text = extract_text(content, content_type)
        except Exception as exc:
            job.status = JobStatus.FAILED
            session.add(
                JobAttempt(
                    job_id=job.id,
                    stage="EXTRACTING",
                    attempt_number=1,
                    validation_errors={"error": str(exc)},
                )
            )
            await session.commit()
            return

        session.add(JobResult(job_id=job.id, raw_text=raw_text))
        job.status = JobStatus.DONE
        await session.commit()
