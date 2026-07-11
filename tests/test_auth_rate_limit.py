async def test_missing_api_key_returns_401(client) -> None:
    response = await client.get("/api/v1/_ping")
    assert response.status_code == 401


async def test_invalid_api_key_returns_401(client) -> None:
    response = await client.get("/api/v1/_ping", headers={"X-API-Key": "ie_not-a-real-key"})
    assert response.status_code == 401


async def test_valid_api_key_returns_200(client, api_key_factory) -> None:
    raw_key, api_key = await api_key_factory()

    response = await client.get("/api/v1/_ping", headers={"X-API-Key": raw_key})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "owner": api_key.owner_name}


async def test_rate_limit_exceeded_returns_429(client, api_key_factory) -> None:
    raw_key, _ = await api_key_factory(rate_limit_per_min=2)
    headers = {"X-API-Key": raw_key}

    first = await client.get("/api/v1/_ping", headers=headers)
    second = await client.get("/api/v1/_ping", headers=headers)
    third = await client.get("/api/v1/_ping", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "Retry-After" in third.headers
