import hashlib
from pathlib import Path

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Job, JobResult, JobStatus
from app.storage.factory import get_storage_backend
from app.worker.tasks import run_extraction
from tests.fixtures.generators import build_native_pdf


async def _create_job(api_key_id, content: bytes, extension: str = ".pdf") -> Job:
    file_hash = hashlib.sha256(content).hexdigest()
    s3_key = f"{file_hash}{extension}"
    await get_storage_backend().save(s3_key, content)

    async with async_session_factory() as session:
        job = Job(
            api_key_id=api_key_id,
            document_type="invoice",
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
    """Exercises the real pipeline (async run_extraction, not the sync
    process_document wrapper) so it can run on the same event loop as the
    rest of the suite — asyncio.run() inside process_document assumes no
    loop is already running, true for a real RQ worker process but not for
    a pytest-asyncio test. The sync wrapper is exercised for real in the
    Docker manual verification instead.
    """
    _, api_key = await api_key_factory()
    content = build_native_pdf("Hello IntelliExtract worker test")
    job = await _create_job(api_key.id, content)

    await run_extraction(job.id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.DONE

        result = await session.get(JobResult, job.id)
        assert result is not None
        assert "IntelliExtract" in result.raw_text

        # cascade="all, delete-orphan" on Job.result/attempts removes the
        # children too — no need to delete them separately.
        await session.delete(refreshed)
        await session.commit()

    _cleanup_stored_file(job.s3_key)


async def test_run_extraction_marks_failed_on_unreadable_file(api_key_factory) -> None:
    _, api_key = await api_key_factory()
    # Not a real PDF/image — sniff_content_type returns None, and
    # extract_text fails trying to OCR-decode it as an image.
    job = await _create_job(api_key.id, b"not a real document", extension=".pdf")

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
