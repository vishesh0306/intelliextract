from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import enforce_rate_limit
from app.models import ApiKey

router = APIRouter()


@router.get("/_ping")
async def ping(api_key: Annotated[ApiKey, Depends(enforce_rate_limit)]) -> dict[str, str]:
    """Phase-2 scaffold proving the auth + rate-limit dependency chain
    works end-to-end. Superseded by real endpoints from Phase 3 onward.
    """
    return {"status": "ok", "owner": api_key.owner_name}
