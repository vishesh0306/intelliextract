import uuid


async def test_missing_api_key_uses_consistent_error_envelope(client) -> None:
    response = await client.get("/api/v1/_ping")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "MISSING_API_KEY"
    assert "message" in body["error"]


async def test_invalid_api_key_uses_consistent_error_envelope(client) -> None:
    response = await client.get("/api/v1/_ping", headers={"X-API-Key": "ie_bogus"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_API_KEY"


async def test_not_found_uses_consistent_error_envelope(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    response = await client.get(f"/api/v1/documents/{uuid.uuid4()}", headers={"X-API-Key": raw_key})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


async def test_rate_limited_uses_consistent_error_envelope(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory(rate_limit_per_min=1)
    headers = {"X-API-Key": raw_key}

    await client.get("/api/v1/_ping", headers=headers)
    response = await client.get("/api/v1/_ping", headers=headers)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in response.headers


async def test_validation_error_uses_consistent_error_envelope(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory()

    response = await client.post(
        "/api/v1/documents",
        headers={"X-API-Key": raw_key},
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        data={"document_type": "not-a-real-type"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
