from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import ApiKey


async def test_create_api_key_requires_admin_header(client) -> None:
    response = await client.post(
        "/api/v1/auth/keys", json={"owner_name": "no-admin-header", "rate_limit_per_min": 10}
    )
    assert response.status_code == 403


async def test_create_api_key_rejects_wrong_admin_key(client) -> None:
    settings = get_settings()
    original = settings.admin_api_key
    settings.admin_api_key = "the-real-admin-secret"
    try:
        response = await client.post(
            "/api/v1/auth/keys",
            headers={"X-Admin-Key": "wrong-secret"},
            json={"owner_name": "wrong-admin-key", "rate_limit_per_min": 10},
        )
        assert response.status_code == 403
    finally:
        settings.admin_api_key = original


async def test_create_api_key_succeeds_with_valid_admin_key(client) -> None:
    settings = get_settings()
    original = settings.admin_api_key
    settings.admin_api_key = "the-real-admin-secret"
    try:
        response = await client.post(
            "/api/v1/auth/keys",
            headers={"X-Admin-Key": "the-real-admin-secret"},
            json={"owner_name": "test-created-key", "rate_limit_per_min": 15},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["owner_name"] == "test-created-key"
        assert body["rate_limit_per_min"] == 15
        assert isinstance(body["api_key"], str) and len(body["api_key"]) > 10

        # the returned key should actually work against a protected route
        ping_response = await client.get("/api/v1/_ping", headers={"X-API-Key": body["api_key"]})
        assert ping_response.status_code == 200
    finally:
        settings.admin_api_key = original
        async with async_session_factory() as session:
            await session.execute(delete(ApiKey).where(ApiKey.owner_name == "test-created-key"))
            await session.commit()
