import hashlib
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Job, JobResult, JobStatus
from app.storage.factory import get_storage_backend
from app.worker.tasks import process_document

PDF_BYTES = b"%PDF-1.4\n%Test PDF content for Phase 3 upload tests.\n%%EOF"


async def _cleanup_job(job_id: str, file_hash: str) -> None:
    async with async_session_factory() as session:
        # ORM-style delete (not a Core delete() statement) so cascade
        # removes job_results/job_attempts first — a bare DELETE FROM jobs
        # trips the FK constraint since those rows would still reference it.
        job = await session.get(Job, job_id)
        if job is not None:
            await session.delete(job)
            await session.commit()

    stored_path = Path(get_settings().local_storage_path) / f"{file_hash}.pdf"
    stored_path.unlink(missing_ok=True)


async def _create_completed_job(
    api_key_id,
    content: bytes,
    document_type: str,
    *,
    status_: JobStatus = JobStatus.DONE,
    extracted_json: dict | None = None,
) -> Job:
    file_hash = hashlib.sha256(content).hexdigest()
    s3_key = f"{file_hash}.pdf"
    await get_storage_backend().save(s3_key, content)

    async with async_session_factory() as session:
        job = Job(
            api_key_id=api_key_id,
            document_type=document_type,
            file_hash=file_hash,
            s3_key=s3_key,
            status=status_,
        )
        session.add(job)
        await session.flush()
        session.add(
            JobResult(job_id=job.id, raw_text="cached raw text", extracted_json=extracted_json)
        )
        await session.commit()
        await session.refresh(job)
        return job


async def test_upload_requires_auth(client) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )

    assert response.status_code == 401


async def test_upload_valid_pdf_returns_202_and_creates_job(client, api_key_factory) -> None:
    raw_key, api_key = await api_key_factory()

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"

    expected_hash = hashlib.sha256(PDF_BYTES).hexdigest()

    async with async_session_factory() as session:
        job = await session.get(Job, body["job_id"])
        assert job is not None
        assert job.status == "PENDING"
        assert job.document_type == "invoice"
        assert job.api_key_id == api_key.id
        assert job.file_hash == expected_hash
        assert job.s3_key == f"{expected_hash}.pdf"

    stored_path = Path(get_settings().local_storage_path) / f"{expected_hash}.pdf"
    assert stored_path.exists()

    await _cleanup_job(body["job_id"], expected_hash)


async def test_upload_rejects_invalid_document_type(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "not-a-real-type"},
    )

    assert response.status_code == 422


async def test_upload_rejects_unsupported_file_type(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("notes.txt", b"just plain text", "text/plain")},
        data={"document_type": "generic"},
    )

    assert response.status_code == 400


async def test_upload_rejects_oversized_file(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()
    oversized = b"%PDF-1.4\n" + b"0" * (21 * 1024 * 1024)

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("big.pdf", oversized, "application/pdf")},
        data={"document_type": "generic"},
    )

    assert response.status_code == 413


async def test_upload_enqueues_processing_job(client, api_key_factory, monkeypatch) -> None:
    raw_key, _ = await api_key_factory()
    mock_queue = MagicMock()
    monkeypatch.setattr("app.api.v1.documents.get_task_queue", lambda: mock_queue)

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )

    body = response.json()
    mock_queue.enqueue.assert_called_once_with(process_document, body["job_id"])

    await _cleanup_job(body["job_id"], hashlib.sha256(PDF_BYTES).hexdigest())


async def test_get_document_requires_auth(client) -> None:
    response = await client.get(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_get_document_not_found_returns_404(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    response = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers={"X-API-Key": raw_key})

    assert response.status_code == 404


async def test_get_document_owned_by_another_key_returns_404(client, api_key_factory) -> None:
    owner_key, _ = await api_key_factory()
    other_key, _ = await api_key_factory()

    upload = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": owner_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )
    job_id = upload.json()["job_id"]

    response = await client.get(f"/api/v1/documents/{job_id}", headers={"X-API-Key": other_key})
    assert response.status_code == 404

    await _cleanup_job(job_id, hashlib.sha256(PDF_BYTES).hexdigest())


async def test_get_document_returns_status(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    upload = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )
    job_id = upload.json()["job_id"]

    response = await client.get(f"/api/v1/documents/{job_id}", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["status"] == "PENDING"
    assert body["document_type"] == "invoice"

    await _cleanup_job(job_id, hashlib.sha256(PDF_BYTES).hexdigest())


async def test_upload_same_file_returns_cached_result(client, api_key_factory, monkeypatch) -> None:
    _, owner_api_key = await api_key_factory()
    cached_job = await _create_completed_job(
        owner_api_key.id,
        PDF_BYTES,
        "invoice",
        extracted_json={"invoice_number": "INV-CACHED"},
    )

    mock_queue = MagicMock()
    monkeypatch.setattr("app.api.v1.documents.get_task_queue", lambda: mock_queue)

    requester_key, requester_api_key = await api_key_factory()
    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": requester_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is True
    assert body["status"] == "DONE"
    assert body["job_id"] != str(cached_job.id)

    mock_queue.enqueue.assert_not_called()

    async with async_session_factory() as session:
        new_job = await session.get(Job, body["job_id"])
        assert new_job is not None
        assert new_job.api_key_id == requester_api_key.id
        assert new_job.status == JobStatus.DONE

        new_result = await session.get(JobResult, new_job.id)
        assert new_result is not None
        assert new_result.extracted_json == {"invoice_number": "INV-CACHED"}

    await _cleanup_job(str(cached_job.id), cached_job.file_hash)
    await _cleanup_job(body["job_id"], cached_job.file_hash)


async def test_upload_not_cached_across_different_document_types(
    client, api_key_factory, monkeypatch
) -> None:
    _, owner_api_key = await api_key_factory()
    cached_job = await _create_completed_job(owner_api_key.id, PDF_BYTES, "invoice")

    mock_queue = MagicMock()
    monkeypatch.setattr("app.api.v1.documents.get_task_queue", lambda: mock_queue)

    requester_key, _ = await api_key_factory()
    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": requester_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "receipt"},
    )

    assert response.status_code == 202
    assert response.json()["cached"] is False
    mock_queue.enqueue.assert_called_once()

    await _cleanup_job(str(cached_job.id), cached_job.file_hash)
    await _cleanup_job(response.json()["job_id"], cached_job.file_hash)


async def test_upload_not_cached_when_only_needs_review_job_exists(
    client, api_key_factory, monkeypatch
) -> None:
    _, owner_api_key = await api_key_factory()
    cached_job = await _create_completed_job(
        owner_api_key.id, PDF_BYTES, "invoice", status_=JobStatus.NEEDS_REVIEW
    )

    mock_queue = MagicMock()
    monkeypatch.setattr("app.api.v1.documents.get_task_queue", lambda: mock_queue)

    requester_key, _ = await api_key_factory()
    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": requester_key},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
        data={"document_type": "invoice"},
    )

    assert response.status_code == 202
    assert response.json()["cached"] is False
    mock_queue.enqueue.assert_called_once()

    await _cleanup_job(str(cached_job.id), cached_job.file_hash)
    await _cleanup_job(response.json()["job_id"], cached_job.file_hash)
