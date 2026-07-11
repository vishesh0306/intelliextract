"""Throwaway script for Phase 1: insert one row per table, query it back
through the relationships, then clean up. Run with:

    uv run python scripts/verify_db.py
"""

import asyncio
import hashlib
import uuid

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import ApiKey, Job, JobAttempt, JobResult, JobStatus


async def main() -> None:
    async with async_session_factory() as session:
        api_key = ApiKey(
            key_hash=hashlib.sha256(b"throwaway-test-key").hexdigest(),
            owner_name="verify_db.py",
            rate_limit_per_min=30,
        )
        session.add(api_key)
        await session.flush()

        job = Job(
            api_key_id=api_key.id,
            document_type="invoice",
            file_hash=hashlib.sha256(b"fake-file-bytes").hexdigest(),
            s3_key=f"dev/{uuid.uuid4()}.pdf",
            status=JobStatus.DONE,
        )
        session.add(job)
        await session.flush()

        session.add(
            JobResult(
                job_id=job.id,
                extracted_json={"invoice_number": "INV-001", "total": 42.50},
                confidence_scores={"invoice_number": 0.98, "total": 0.95},
                raw_text="INVOICE #INV-001 ... TOTAL: $42.50",
            )
        )
        session.add(
            JobAttempt(
                job_id=job.id,
                stage="EXTRACTING_AI",
                attempt_number=1,
                prompt="Extract invoice fields as JSON...",
                raw_llm_response='{"invoice_number": "INV-001", "total": 42.50}',
            )
        )
        await session.commit()

        print(f"Inserted api_key={api_key.id} job={job.id}")

        fetched = await session.scalar(select(Job).where(Job.id == job.id))
        assert fetched is not None
        await session.refresh(fetched, attribute_names=["result", "attempts", "api_key"])

        print(f"Queried job status={fetched.status}, document_type={fetched.document_type}")
        print(f"  api_key.owner_name={fetched.api_key.owner_name}")
        print(f"  result.extracted_json={fetched.result.extracted_json}")
        print(f"  attempts=[{len(fetched.attempts)}] stage={fetched.attempts[0].stage}")

        await session.delete(fetched)
        await session.delete(api_key)
        await session.commit()
        print("Cleaned up test rows.")


if __name__ == "__main__":
    asyncio.run(main())
