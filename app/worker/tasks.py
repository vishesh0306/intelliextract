import asyncio
import uuid

from sqlalchemy import update

from app.db.session import async_session_factory
from app.models import Job, JobStatus


def process_document(job_id: str) -> None:
    """RQ entrypoint. RQ workers call plain sync functions, so this bridges
    into our async DB layer with asyncio.run() rather than duplicating a
    sync engine just for the worker.

    Phase 4 proves the queue/worker plumbing only: flips PENDING -> DONE
    with no real extraction. Staged processing (EXTRACTING, EXTRACTING_AI,
    VALIDATING, ...) lands in Phase 5 onward.
    """
    asyncio.run(mark_job_done(uuid.UUID(job_id)))


async def mark_job_done(job_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.DONE))
        await session.commit()
