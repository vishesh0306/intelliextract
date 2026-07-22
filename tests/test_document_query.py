import hashlib
import json
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import Job, JobResult, JobStatus
from app.services import generic_extraction
from app.storage.factory import get_storage_backend

PDF_BYTES = b"%PDF-1.4\n%Test PDF content for query endpoint tests.\n%%EOF"


class _FakeLLMClient:
    def __init__(self, response: str) -> None:
        self._response = response

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._response


async def _create_job_with_result(
    api_key_id,
    *,
    raw_text: str | None = "some extracted invoice text",
    document_type: str = "invoice",
) -> Job:
    content = PDF_BYTES + uuid.uuid4().bytes
    file_hash = hashlib.sha256(content).hexdigest()
    s3_key = f"{file_hash}.pdf"
    await get_storage_backend().save(s3_key, content)

    async with async_session_factory() as session:
        job = Job(
            api_key_id=api_key_id,
            document_type=document_type,
            file_hash=file_hash,
            s3_key=s3_key,
            status=JobStatus.DONE,
        )
        session.add(job)
        await session.flush()
        if raw_text is not None:
            session.add(JobResult(job_id=job.id, raw_text=raw_text))
        await session.commit()
        await session.refresh(job)
        return job


async def _cleanup(job: Job) -> None:
    async with async_session_factory() as session:
        db_job = await session.get(Job, job.id)
        if db_job is not None:
            await session.delete(db_job)
            await session.commit()
    (Path(get_settings().local_storage_path) / job.s3_key).unlink(missing_ok=True)


async def test_query_requires_auth(client) -> None:
    response = await client.post(f"/api/v1/documents/{uuid.uuid4()}/query", json={})
    assert response.status_code == 401


async def test_query_returns_404_for_foreign_job(client, api_key_factory) -> None:
    _, owner_api_key = await api_key_factory()
    other_key, _ = await api_key_factory()
    job = await _create_job_with_result(owner_api_key.id)

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": other_key},
            json={"fields": ["vendor_name"]},
        )
        assert response.status_code == 404
    finally:
        await _cleanup(job)


async def test_query_returns_409_when_no_text_extracted(client, api_key_factory) -> None:
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(api_key.id, raw_text=None)

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["vendor_name"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_READY"
    finally:
        await _cleanup(job)


async def test_query_with_fields_returns_requested_keys(
    client, api_key_factory, monkeypatch
) -> None:
    response_json = json.dumps({"vendor_name": "Acme Corp", "total_amount": 99.5})
    monkeypatch.setattr(generic_extraction, "get_llm_client", lambda: _FakeLLMClient(response_json))
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(api_key.id)

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["vendor_name", "total_amount"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == str(job.id)
        assert body["result"] == {"vendor_name": "Acme Corp", "total_amount": 99.5}

        async with async_session_factory() as session:
            refreshed = await session.get(Job, job.id)
            await session.refresh(refreshed, attribute_names=["attempts"])
            query_attempts = [a for a in refreshed.attempts if a.stage == "CUSTOM_QUERY"]
            assert len(query_attempts) == 1
            assert query_attempts[0].raw_llm_response == response_json
            assert query_attempts[0].validation_errors is None
    finally:
        await _cleanup(job)


async def test_query_works_on_non_invoice_document_type(
    client, api_key_factory, monkeypatch
) -> None:
    response_json = json.dumps({"name": "Jane Doe", "skills": ["Python", "SQL"]})
    monkeypatch.setattr(generic_extraction, "get_llm_client", lambda: _FakeLLMClient(response_json))
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(
        api_key.id, raw_text="resume text with skills", document_type="resume"
    )

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["name", "skills"]},
        )

        assert response.status_code == 200
        assert response.json()["result"] == {"name": "Jane Doe", "skills": ["Python", "SQL"]}
    finally:
        await _cleanup(job)


async def test_query_without_fields_lets_model_decide(client, api_key_factory, monkeypatch) -> None:
    response_json = json.dumps({"invoice_number": "INV-1", "total": 10.0})
    monkeypatch.setattr(generic_extraction, "get_llm_client", lambda: _FakeLLMClient(response_json))
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(api_key.id)

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={},
        )

        assert response.status_code == 200
        assert response.json()["result"] == {"invoice_number": "INV-1", "total": 10.0}
    finally:
        await _cleanup(job)


async def test_query_records_parse_error_in_audit_when_json_never_valid(
    client, api_key_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        generic_extraction, "get_llm_client", lambda: _FakeLLMClient("not json at all")
    )
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(api_key.id)

    try:
        response = await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["vendor_name"]},
        )

        assert response.status_code == 200
        assert response.json()["result"] == {}

        async with async_session_factory() as session:
            refreshed = await session.get(Job, job.id)
            await session.refresh(refreshed, attribute_names=["attempts"])
            query_attempts = [a for a in refreshed.attempts if a.stage == "CUSTOM_QUERY"]
            assert len(query_attempts) == 1
            assert query_attempts[0].validation_errors is not None
    finally:
        await _cleanup(job)


async def test_query_increments_attempt_number_across_multiple_calls(
    client, api_key_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        generic_extraction,
        "get_llm_client",
        lambda: _FakeLLMClient(json.dumps({"vendor_name": "Acme"})),
    )
    raw_key, api_key = await api_key_factory()
    job = await _create_job_with_result(api_key.id)

    try:
        await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["vendor_name"]},
        )
        await client.post(
            f"/api/v1/documents/{job.id}/query",
            headers={"X-API-Key": raw_key},
            json={"fields": ["vendor_name"]},
        )

        async with async_session_factory() as session:
            refreshed = await session.get(Job, job.id)
            await session.refresh(refreshed, attribute_names=["attempts"])
            query_attempts = sorted(
                (a for a in refreshed.attempts if a.stage == "CUSTOM_QUERY"),
                key=lambda a: a.attempt_number,
            )
            assert [a.attempt_number for a in query_attempts] == [1, 2]
    finally:
        await _cleanup(job)
