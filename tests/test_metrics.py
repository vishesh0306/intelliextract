import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models import Job, JobStatus


def _extract_status_count(body: str, status_value: str) -> int:
    match = re.search(rf'intelliextract_jobs_total\{{status="{status_value}"\}} (\d+)', body)
    assert match is not None
    return int(match.group(1))


def _extract_avg_seconds(body: str) -> float:
    match = re.search(r"intelliextract_job_processing_seconds_avg ([\d.]+)", body)
    assert match is not None
    return float(match.group(1))


async def test_metrics_is_unauthenticated_and_well_formed(client) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "intelliextract_jobs_total" in body
    assert "intelliextract_job_processing_seconds_avg" in body
    assert "intelliextract_cache_hit_ratio" in body
    for job_status in JobStatus:
        assert f'intelliextract_jobs_total{{status="{job_status.value}"}}' in body


async def test_metrics_counts_and_average_reflect_new_jobs(client, api_key_factory) -> None:
    """The dev Postgres is shared across the whole suite (and manual
    testing), so this asserts deltas and cross-checks the average against
    an independent query rather than hardcoding absolute numbers.
    """
    _, api_key = await api_key_factory()

    before_body = (await client.get("/metrics")).text
    before_done = _extract_status_count(before_body, "DONE")
    before_failed = _extract_status_count(before_body, "FAILED")

    now = datetime.now(UTC)
    non_cached_jobs = [
        Job(
            api_key_id=api_key.id,
            document_type="generic",
            file_hash=f"metrics-test-{i}",
            s3_key=f"metrics-test-{i}.pdf",
            status=JobStatus.DONE,
            cached=False,
            created_at=now - timedelta(seconds=10 * (i + 1)),
            updated_at=now,
        )
        for i in range(2)
    ]
    cached_job = Job(
        api_key_id=api_key.id,
        document_type="generic",
        file_hash="metrics-test-cached",
        s3_key="metrics-test-cached.pdf",
        status=JobStatus.DONE,
        cached=True,
        created_at=now,
        updated_at=now,
    )
    failed_job = Job(
        api_key_id=api_key.id,
        document_type="generic",
        file_hash="metrics-test-failed",
        s3_key="metrics-test-failed.pdf",
        status=JobStatus.FAILED,
        cached=False,
        created_at=now,
        updated_at=now,
    )
    all_jobs = [*non_cached_jobs, cached_job, failed_job]

    async with async_session_factory() as session:
        for job in all_jobs:
            session.add(job)
        await session.commit()

    try:
        after_body = (await client.get("/metrics")).text
        after_done = _extract_status_count(after_body, "DONE")
        after_failed = _extract_status_count(after_body, "FAILED")

        assert after_done - before_done == 3  # 2 non-cached + 1 cached
        assert after_failed - before_failed == 1

        async with async_session_factory() as session:
            expected_avg = await session.scalar(
                select(func.avg(func.extract("epoch", Job.updated_at - Job.created_at))).where(
                    Job.status == JobStatus.DONE, Job.cached.is_(False)
                )
            )
        # Postgres's AVG() comes back as a Decimal via asyncpg; pytest.approx
        # can't subtract Decimal from float internally, so cast first.
        assert _extract_avg_seconds(after_body) == pytest.approx(float(expected_avg), abs=0.01)
    finally:
        async with async_session_factory() as session:
            for job in all_jobs:
                db_job = await session.get(Job, job.id)
                if db_job is not None:
                    await session.delete(db_job)
            await session.commit()
