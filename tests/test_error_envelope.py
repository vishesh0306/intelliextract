import json
import uuid

from starlette.requests import Request

from app.core.error_handlers import unhandled_exception_handler


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


async def test_unhandled_exception_handler_returns_consistent_error_envelope() -> None:
    """Unit-tests the handler function directly rather than through the
    full ASGI stack: httpx's test transport deliberately re-raises any
    unhandled exception into the test (raise_app_exceptions=True is the
    right default — it's what makes every OTHER test in this suite fail
    loudly on an unexpected 500 instead of silently passing), which means
    it can't be used to inspect what a real deployed server would have
    sent back. The handler itself is what matters here.

    Real-world trigger for adding this handler: GROQ_API_KEY was missing
    from the api container's env (the query endpoint calls Groq directly,
    unlike the worker-only pipeline), which raised a raw openai.OpenAIError
    that reached the client as a bare "Internal Server Error" with no JSON
    body at all, before this handler existed.
    """
    request = Request(scope={"type": "http", "method": "GET", "path": "/whatever", "headers": []})
    exc = RuntimeError("simulated unexpected failure")

    response = await unhandled_exception_handler(request, exc)

    assert response.status_code == 500
    body = json.loads(response.body)
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "simulated unexpected failure" not in body["error"]["message"]
