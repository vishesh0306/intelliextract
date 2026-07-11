import hashlib
import json
from pathlib import Path

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Job, JobResult, JobStatus
from app.services import ai_extraction
from app.storage.factory import get_storage_backend
from app.worker.tasks import run_extraction
from tests.fixtures.generators import build_native_pdf

VALID_INVOICE_JSON = json.dumps(
    {
        "invoice_number": "INV-001",
        "date": "2026-01-15",
        "vendor": "Acme Corp",
        "line_items": [
            {"description": "Widget", "quantity": 2, "unit_price": 10.0, "amount": 20.0}
        ],
        "total": 20.0,
    }
)


class _FakeLLMClient:
    def __init__(self, response: str) -> None:
        self._response = response

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._response


async def _create_job(
    api_key_id, content: bytes, document_type: str, extension: str = ".pdf"
) -> Job:
    file_hash = hashlib.sha256(content).hexdigest()
    s3_key = f"{file_hash}{extension}"
    await get_storage_backend().save(s3_key, content)

    async with async_session_factory() as session:
        job = Job(
            api_key_id=api_key_id,
            document_type=document_type,
            file_hash=file_hash,
            s3_key=s3_key,
            status=JobStatus.PENDING,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job


def _cleanup_stored_file(s3_key: str) -> None:
    (Path(get_settings().local_storage_path) / s3_key).unlink(missing_ok=True)


async def test_run_extraction_stores_raw_text_and_marks_done(api_key_factory) -> None:
    """A non-invoice document type: exercises Phase 5's extraction stage
    only, stopping at DONE without touching the LLM (Phase 6 only added a
    schema for invoices, so other types still behave exactly as in Phase 5).

    Runs the async run_extraction directly rather than the sync
    process_document wrapper so it can share the suite's event loop —
    asyncio.run() inside process_document assumes no loop is already
    running, true for a real RQ worker process but not for a
    pytest-asyncio test. The sync wrapper is exercised for real in the
    Docker manual verification instead.
    """
    _, api_key = await api_key_factory()
    content = build_native_pdf("Hello IntelliExtract worker test")
    job = await _create_job(api_key.id, content, document_type="generic")

    await run_extraction(job.id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.DONE

        result = await session.get(JobResult, job.id)
        assert result is not None
        assert "IntelliExtract" in result.raw_text
        assert result.extracted_json is None

        # cascade="all, delete-orphan" on Job.result/attempts removes the
        # children too — no need to delete them separately.
        await session.delete(refreshed)
        await session.commit()

    _cleanup_stored_file(job.s3_key)


async def test_run_extraction_marks_failed_on_unreadable_file(api_key_factory) -> None:
    _, api_key = await api_key_factory()
    # Not a real PDF/image — sniff_content_type returns None, and
    # extract_text fails trying to OCR-decode it as an image.
    job = await _create_job(api_key.id, b"not a real document", document_type="generic")

    await run_extraction(job.id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.FAILED
        await session.refresh(refreshed, attribute_names=["attempts"])
        assert len(refreshed.attempts) == 1
        assert refreshed.attempts[0].stage == "EXTRACTING"

        await session.delete(refreshed)
        await session.commit()

    _cleanup_stored_file(job.s3_key)


async def test_run_extraction_invoice_success(api_key_factory, monkeypatch) -> None:
    monkeypatch.setattr(ai_extraction, "get_llm_client", lambda: _FakeLLMClient(VALID_INVOICE_JSON))
    _, api_key = await api_key_factory()
    content = build_native_pdf("INVOICE #INV-001 Acme Corp Widget x2 @10 Total 20")
    job = await _create_job(api_key.id, content, document_type="invoice")

    await run_extraction(job.id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.DONE

        result = await session.get(JobResult, job.id)
        assert result is not None
        assert result.extracted_json["invoice_number"] == "INV-001"
        assert result.extracted_json["total"] == 20.0

        await session.refresh(refreshed, attribute_names=["attempts"])
        ai_attempts = [a for a in refreshed.attempts if a.stage == "EXTRACTING_AI"]
        assert len(ai_attempts) == 1
        assert ai_attempts[0].raw_llm_response == VALID_INVOICE_JSON
        assert ai_attempts[0].prompt is not None

        await session.delete(refreshed)
        await session.commit()

    _cleanup_stored_file(job.s3_key)


async def test_run_extraction_invoice_ai_parse_failure(api_key_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        ai_extraction, "get_llm_client", lambda: _FakeLLMClient("not valid json at all")
    )
    _, api_key = await api_key_factory()
    content = build_native_pdf("INVOICE #INV-002")
    job = await _create_job(api_key.id, content, document_type="invoice")

    await run_extraction(job.id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.FAILED

        await session.refresh(refreshed, attribute_names=["attempts"])
        ai_attempts = [a for a in refreshed.attempts if a.stage == "EXTRACTING_AI"]
        assert len(ai_attempts) == 1
        assert ai_attempts[0].raw_llm_response == "not valid json at all"

        await session.delete(refreshed)
        await session.commit()

    _cleanup_stored_file(job.s3_key)
