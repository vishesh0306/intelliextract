from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.security import generate_api_key, hash_api_key
from app.db.session import get_db
from app.models import ApiKey
from app.schemas.auth import CreateApiKeyRequest, CreateApiKeyResponse
from app.schemas.errors import ErrorResponse

router = APIRouter()


@router.post(
    "/auth/keys",
    response_model=CreateApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    summary="Issue a new API key (admin-only)",
    description="Requires the X-Admin-Key header to match ADMIN_API_KEY. The "
    "returned api_key is shown once — only its hash is stored, so it "
    "cannot be recovered if lost.",
    responses={
        403: {"model": ErrorResponse, "description": "Missing or invalid X-Admin-Key"},
    },
)
async def create_api_key(
    body: CreateApiKeyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateApiKeyResponse:
    raw_key = generate_api_key()
    api_key = ApiKey(
        key_hash=hash_api_key(raw_key),
        owner_name=body.owner_name,
        rate_limit_per_min=body.rate_limit_per_min,
    )
    db.add(api_key)
    await db.commit()

    return CreateApiKeyResponse(
        api_key=raw_key,
        owner_name=api_key.owner_name,
        rate_limit_per_min=api_key.rate_limit_per_min,
    )
