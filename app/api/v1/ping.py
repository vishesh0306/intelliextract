from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import enforce_rate_limit
from app.models import ApiKey

router = APIRouter()


@router.get(
    "/_ping",
    summary="Debug: auth + rate-limit check",
    description="Not part of the real API surface — a minimal protected route "
    "used to test the auth/rate-limit dependency chain in isolation from "
    "the upload endpoint's complexity.",
)
async def ping(api_key: Annotated[ApiKey, Depends(enforce_rate_limit)]) -> dict[str, str]:
    return {"status": "ok", "owner": api_key.owner_name}
