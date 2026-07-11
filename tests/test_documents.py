import hashlib
from pathlib import Path

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Job

PDF_BYTES = b"%PDF-1.4\n%Test PDF content for Phase 3 upload tests.\n%%EOF"


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

        await session.execute(delete(Job).where(Job.id == job.id))
        await session.commit()

    stored_path = Path(get_settings().local_storage_path) / f"{expected_hash}.pdf"
    assert stored_path.exists()
    stored_path.unlink()


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
