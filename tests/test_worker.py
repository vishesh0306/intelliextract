import hashlib

from app.db.session import async_session_factory
from app.models import Job, JobStatus
from app.worker.tasks import mark_job_done


async def test_mark_job_done_flips_status_to_done(api_key_factory) -> None:
    """Exercises the same DB-update logic process_document (the sync RQ
    entrypoint) wraps with asyncio.run(). Tested directly rather than
    through process_document itself so it can run on the same event loop
    as the rest of the suite — asyncio.run() assumes no loop is already
    running, which is true for a real RQ worker process but not for a
    pytest-asyncio test. The sync wrapper is exercised for real in the
    Docker manual verification instead.
    """
    _, api_key = await api_key_factory()

    async with async_session_factory() as session:
        job = Job(
            api_key_id=api_key.id,
            document_type="invoice",
            file_hash=hashlib.sha256(b"worker-test-fixture").hexdigest(),
            s3_key="dummy.pdf",
            status=JobStatus.PENDING,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    await mark_job_done(job_id)

    async with async_session_factory() as session:
        refreshed = await session.get(Job, job_id)
        assert refreshed is not None
        assert refreshed.status == JobStatus.DONE

        await session.delete(refreshed)
        await session.commit()
