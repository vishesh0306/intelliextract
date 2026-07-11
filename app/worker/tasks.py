import asyncio
import uuid

from app.db.session import async_session_factory
from app.models import Job, JobAttempt, JobResult, JobStatus
from app.schemas.document import DocumentType
from app.services.ai_extraction import extract_invoice_fields
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
    """EXTRACTING: fetch the stored file and pull its raw text (native PDF
    layer, falling back to OCR). EXTRACTING_AI: for invoices only, send
    that text to the LLM for structured extraction — other document types
    have no schema yet (Phase 6 is deliberately one type done well), so
    they stop at DONE right after extraction, same as Phase 5.

    No retry loop here — that's Phase 7's self-correction logic, which
    needs a validation failure reason to feed back into a second prompt.
    A parse failure here just fails the job outright for now.
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

        result = JobResult(job_id=job.id, raw_text=raw_text)
        session.add(result)

        if job.document_type != DocumentType.INVOICE.value:
            job.status = JobStatus.DONE
            await session.commit()
            return

        job.status = JobStatus.EXTRACTING_AI
        await session.commit()

        try:
            ai_result = await extract_invoice_fields(raw_text)
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
            return

        session.add(
            JobAttempt(
                job_id=job.id,
                stage="EXTRACTING_AI",
                attempt_number=1,
                prompt=ai_result.prompt,
                raw_llm_response=ai_result.raw_response,
            )
        )

        if ai_result.parsed is None:
            job.status = JobStatus.FAILED
            await session.commit()
            return

        result.extracted_json = ai_result.parsed.model_dump(mode="json")
        job.status = JobStatus.DONE
        await session.commit()
