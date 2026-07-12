import asyncio
import uuid

import structlog

from app.db.session import async_session_factory
from app.models import Job, JobAttempt, JobResult, JobStatus
from app.schemas.document import DocumentType
from app.services.extraction import extract_text
from app.services.file_validation import sniff_content_type
from app.services.self_correction import run_invoice_self_correction
from app.storage.factory import get_storage_backend

logger = structlog.get_logger()


def process_document(job_id: str) -> None:
    """RQ entrypoint. RQ workers call plain sync functions, so this bridges
    into our async DB layer with asyncio.run() rather than duplicating a
    sync engine just for the worker.
    """
    asyncio.run(run_extraction(uuid.UUID(job_id)))


async def run_extraction(job_id: uuid.UUID) -> None:
    """EXTRACTING: fetch the stored file and pull its raw text (native PDF
    layer, falling back to OCR). EXTRACTING_AI / VALIDATING: for invoices
    only, run the self-correction loop (LLM call -> validate -> re-prompt
    on failure, up to 3 attempts) — other document types have no schema
    yet (Phase 6 is deliberately one type done well), so they stop at
    DONE right after extraction, same as Phase 5.

    A job that never passes validation lands on NEEDS_REVIEW, not FAILED —
    FAILED is reserved for infrastructure problems (unreadable file, LLM
    API error), NEEDS_REVIEW for "the pipeline worked but isn't confident
    enough to call it done."
    """
    # A worker process handles many jobs over its lifetime, so contextvars
    # must be cleared before each one — otherwise the previous job's id
    # would leak onto this job's log lines.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id=str(job_id))
    logger.info("job_processing_started")

    async with async_session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("job_not_found")
            return

        job.status = JobStatus.EXTRACTING
        await session.commit()
        logger.info("job_stage_changed", stage="EXTRACTING")

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
            logger.error("job_extraction_failed", error=str(exc))
            return

        result = JobResult(job_id=job.id, raw_text=raw_text)
        session.add(result)

        if job.document_type != DocumentType.INVOICE.value:
            job.status = JobStatus.DONE
            await session.commit()
            logger.info("job_processing_finished", final_status=job.status.value)
            return

        job.status = JobStatus.EXTRACTING_AI
        await session.commit()
        logger.info("job_stage_changed", stage="EXTRACTING_AI")

        try:
            outcome = await run_invoice_self_correction(raw_text)
        except Exception as exc:
            job.status = JobStatus.FAILED
            session.add(
                JobAttempt(
                    job_id=job.id,
                    stage="EXTRACTING_AI",
                    attempt_number=1,
                    validation_errors={"error": str(exc)},
                )
            )
            await session.commit()
            logger.error("job_ai_extraction_failed", error=str(exc))
            return

        for attempt in outcome.attempts:
            session.add(
                JobAttempt(
                    job_id=job.id,
                    stage="EXTRACTING_AI",
                    attempt_number=attempt.attempt_number,
                    prompt=attempt.prompt,
                    raw_llm_response=attempt.raw_response,
                    validation_errors=(
                        [{"field": field, "message": message} for field, message in attempt.errors]
                        if attempt.errors
                        else None
                    ),
                )
            )
        logger.info(
            "job_self_correction_completed",
            attempts=len(outcome.attempts),
            needs_review=outcome.needs_review,
        )

        job.status = JobStatus.VALIDATING
        await session.commit()
        logger.info("job_stage_changed", stage="VALIDATING")

        if outcome.fields is not None:
            result.extracted_json = outcome.fields.model_dump(mode="json")
        if outcome.confidence_scores is not None:
            result.confidence_scores = outcome.confidence_scores

        job.status = JobStatus.NEEDS_REVIEW if outcome.needs_review else JobStatus.DONE
        await session.commit()
        logger.info("job_processing_finished", final_status=job.status.value)
