from pydantic import BaseModel, Field


class CreateApiKeyRequest(BaseModel):
    owner_name: str = Field(examples=["acme-corp-integration"])
    rate_limit_per_min: int = Field(default=30, ge=1, le=1000)


class CreateApiKeyResponse(BaseModel):
    api_key: str = Field(
        description="Shown once — only the hash is stored, it cannot be recovered later"
    )
    owner_name: str
    rate_limit_per_min: int
