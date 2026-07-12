"""Phase 11 load test. Run against the live Docker stack:

    docker compose up -d
    uv run python -m scripts.load_test

Prints real, measured numbers — never fabricated (see BUILD_PROMPT.md
rule 8). Those numbers feed directly into benchmarks.md and the README.
Creates its own throwaway API keys and jobs, and cleans them up on exit.
"""

import asyncio
import time
import uuid

import fitz
import httpx
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import ApiKey, Job, JobAttempt, JobResult

BASE_URL = "http://localhost:8000"
BENCH_PREFIX = "bench-"


def _build_invoice_pdf(invoice_number: str, amount: float) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    text = (
        "INVOICE\n\n"
        f"Invoice Number: {invoice_number}\n"
        "Date: 2026-06-01\n"
        "Vendor: Load Test Vendor\n\n"
        "Line Items:\n"
        f"1. Widget   Qty: 1   Unit Price: ${amount:.2f}   Amount: ${amount:.2f}\n\n"
        f"Total: ${amount:.2f}\n"
    )
    page.insert_text((50, 50), text, fontsize=11)
    try:
        return doc.tobytes()
    finally:
        doc.close()


async def _create_api_key(client: httpx.AsyncClient, owner_suffix: str, rate_limit: int) -> str:
    settings = get_settings()
    response = await client.post(
        f"{BASE_URL}/api/v1/auth/keys",
        headers={"X-Admin-Key": settings.admin_api_key},
        json={"owner_name": f"{BENCH_PREFIX}{owner_suffix}", "rate_limit_per_min": rate_limit},
    )
    response.raise_for_status()
    return response.json()["api_key"]


async def _upload(client: httpx.AsyncClient, api_key: str, content: bytes) -> httpx.Response:
    return await client.post(
        f"{BASE_URL}/api/v1/documents",
        headers={"X-API-Key": api_key},
        files={"file": ("invoice.pdf", content, "application/pdf")},
        data={"document_type": "invoice"},
    )


async def _poll_until_terminal(
    client: httpx.AsyncClient, api_key: str, job_id: str, timeout: float = 60.0
) -> tuple[str, float]:
    terminal = {"DONE", "NEEDS_REVIEW", "FAILED"}
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        response = await client.get(
            f"{BASE_URL}/api/v1/documents/{job_id}", headers={"X-API-Key": api_key}
        )
        current_status = response.json()["status"]
        if current_status in terminal:
            return current_status, time.perf_counter() - start
        await asyncio.sleep(0.2)
    raise TimeoutError(f"job {job_id} did not reach a terminal state within {timeout}s")


async def benchmark_single_upload_latency(client: httpx.AsyncClient, api_key: str) -> None:
    content = _build_invoice_pdf(f"BENCH-SINGLE-{uuid.uuid4().hex[:8]}", 42.50)

    start = time.perf_counter()
    response = await _upload(client, api_key, content)
    upload_elapsed = time.perf_counter() - start
    job_id = response.json()["job_id"]

    final_status, processing_elapsed = await _poll_until_terminal(client, api_key, job_id)
    total_elapsed = upload_elapsed + processing_elapsed

    print(f"[single upload] POST /documents accepted (202) in {upload_elapsed * 1000:.0f}ms")
    print(
        f"[single upload] end-to-end upload -> {final_status} in {total_elapsed:.2f}s "
        f"(native PDF text extraction + one Groq call, no retries)"
    )


async def benchmark_cache_hit_latency(client: httpx.AsyncClient, api_key: str) -> None:
    content = _build_invoice_pdf(f"BENCH-CACHE-{uuid.uuid4().hex[:8]}", 99.00)

    first = await _upload(client, api_key, content)
    await _poll_until_terminal(client, api_key, first.json()["job_id"])

    start = time.perf_counter()
    second = await _upload(client, api_key, content)
    elapsed = time.perf_counter() - start

    body = second.json()
    assert second.status_code == 200
    assert body["cached"] is True
    print(
        f"[cache hit] re-upload of the identical file: {elapsed * 1000:.1f}ms "
        f"(200, cached=true, no LLM call)"
    )


async def benchmark_concurrent_cached_throughput(
    client: httpx.AsyncClient, api_key: str, n: int
) -> None:
    content = _build_invoice_pdf(f"BENCH-THROUGHPUT-{uuid.uuid4().hex[:8]}", 15.00)
    warm = await _upload(client, api_key, content)
    await _poll_until_terminal(client, api_key, warm.json()["job_id"])

    start = time.perf_counter()
    responses = await asyncio.gather(*[_upload(client, api_key, content) for _ in range(n)])
    elapsed = time.perf_counter() - start

    ok = sum(1 for r in responses if r.status_code == 200 and r.json().get("cached") is True)
    print(
        f"[cache-hit throughput] {n} concurrent uploads of the same cached file: "
        f"{ok}/{n} succeeded in {elapsed:.3f}s ({n / elapsed:.1f} req/s) "
        f"— pure API+DB path, no LLM/OCR involved"
    )


async def benchmark_concurrent_real_processing(
    client: httpx.AsyncClient, api_key: str, n: int
) -> None:
    contents = [
        _build_invoice_pdf(f"BENCH-CONCURRENT-{i}-{uuid.uuid4().hex[:6]}", 10.0 + i)
        for i in range(n)
    ]

    start = time.perf_counter()
    responses = await asyncio.gather(*[_upload(client, api_key, c) for c in contents])
    accept_elapsed = time.perf_counter() - start
    assert all(r.status_code == 202 for r in responses)

    job_ids = [r.json()["job_id"] for r in responses]
    results = await asyncio.gather(
        *[_poll_until_terminal(client, api_key, jid, timeout=120.0) for jid in job_ids]
    )
    total_elapsed = time.perf_counter() - start
    statuses = [s for s, _ in results]

    print(
        f"[concurrency={n}] all {n} uploads accepted (202) in {accept_elapsed * 1000:.0f}ms total "
        f"— upload acceptance is decoupled from processing"
    )
    print(
        f"[concurrency={n}] all {n} jobs reached a terminal state in {total_elapsed:.2f}s "
        f"({total_elapsed / n:.2f}s/job average — a single worker replica processes serially)"
    )
    print(f"[concurrency={n}] final statuses: {statuses}")


async def benchmark_rate_limiting(client: httpx.AsyncClient) -> None:
    limited_key = await _create_api_key(client, f"ratelimit-{uuid.uuid4().hex[:6]}", rate_limit=5)
    headers = {"X-API-Key": limited_key}

    responses = []
    start = time.perf_counter()
    for _ in range(8):
        responses.append(await client.get(f"{BASE_URL}/api/v1/_ping", headers=headers))
    elapsed = time.perf_counter() - start

    ok = sum(1 for r in responses if r.status_code == 200)
    limited = sum(1 for r in responses if r.status_code == 429)
    retry_after = next(
        (r.headers.get("retry-after") for r in responses if r.status_code == 429), None
    )

    print(
        f"[rate limiting] key capped at 5/min, 8 rapid sequential requests in "
        f"{elapsed * 1000:.0f}ms: {ok} succeeded (200), {limited} rejected (429), "
        f"Retry-After={retry_after}s"
    )


async def _cleanup() -> None:
    async with async_session_factory() as session:
        api_key_ids = (
            await session.scalars(
                select(ApiKey.id).where(ApiKey.owner_name.startswith(BENCH_PREFIX))
            )
        ).all()
        if not api_key_ids:
            return

        job_ids = (
            await session.scalars(select(Job.id).where(Job.api_key_id.in_(api_key_ids)))
        ).all()
        await session.execute(delete(JobAttempt).where(JobAttempt.job_id.in_(job_ids)))
        await session.execute(delete(JobResult).where(JobResult.job_id.in_(job_ids)))
        await session.execute(delete(Job).where(Job.id.in_(job_ids)))
        await session.execute(delete(ApiKey).where(ApiKey.id.in_(api_key_ids)))
        await session.commit()
        print(f"[cleanup] removed {len(job_ids)} jobs and {len(api_key_ids)} api keys")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        api_key = await _create_api_key(client, f"main-{uuid.uuid4().hex[:6]}", rate_limit=1000)

        print("=" * 78)
        await benchmark_single_upload_latency(client, api_key)
        print("=" * 78)
        await benchmark_cache_hit_latency(client, api_key)
        print("=" * 78)
        await benchmark_concurrent_cached_throughput(client, api_key, n=20)
        print("=" * 78)
        await benchmark_concurrent_real_processing(client, api_key, n=5)
        print("=" * 78)
        await benchmark_rate_limiting(client)
        print("=" * 78)

    await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
