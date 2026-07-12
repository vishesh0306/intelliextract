from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus


async def render_prometheus_metrics(db: AsyncSession) -> str:
    """Job counts by status, average processing time for genuinely-
    processed jobs, and the cache hit ratio — all computed straight from
    the jobs table rather than tracked separately, so there's nothing to
    keep in sync. cached is an explicit column (Phase 8) rather than an
    inferred one (e.g. "updated_at == created_at"), which would be a
    fragile heuristic.
    """
    status_rows = await db.execute(select(Job.status, func.count()).group_by(Job.status))
    counts_by_status = dict(status_rows.all())

    avg_seconds = await db.scalar(
        select(func.avg(func.extract("epoch", Job.updated_at - Job.created_at))).where(
            Job.status == JobStatus.DONE, Job.cached.is_(False)
        )
    )

    done_total = await db.scalar(
        select(func.count()).select_from(Job).where(Job.status == JobStatus.DONE)
    )
    done_cached = await db.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.DONE, Job.cached.is_(True))
    )
    cache_hit_ratio = (done_cached / done_total) if done_total else 0.0

    lines = [
        "# HELP intelliextract_jobs_total Total jobs by status",
        "# TYPE intelliextract_jobs_total gauge",
    ]
    for job_status in JobStatus:
        count = counts_by_status.get(job_status, 0)
        lines.append(f'intelliextract_jobs_total{{status="{job_status.value}"}} {count}')

    lines += [
        "",
        "# HELP intelliextract_job_processing_seconds_avg Average wall-clock "
        "time from created_at to updated_at for DONE jobs that were actually "
        "processed (excludes cache hits)",
        "# TYPE intelliextract_job_processing_seconds_avg gauge",
        f"intelliextract_job_processing_seconds_avg {avg_seconds or 0.0:.3f}",
        "",
        "# HELP intelliextract_cache_hit_ratio Fraction of DONE jobs served "
        "from cache rather than actually processed",
        "# TYPE intelliextract_cache_hit_ratio gauge",
        f"intelliextract_cache_hit_ratio {cache_hit_ratio:.3f}",
    ]

    return "\n".join(lines) + "\n"
