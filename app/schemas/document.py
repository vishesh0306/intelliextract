import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import JobStatus


class DocumentType(enum.StrEnum):
    """The API-level allow-list of document_type hints from the spec.

    Deliberately separate from Job.document_type's DB column (a plain
    String) — adding a new type here is just an enum change, no migration.
    """

    INVOICE = "invoice"
    RESUME = "resume"
    RECEIPT = "receipt"
    GENERIC = "generic"


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "PENDING",
                    "cached": False,
                }
            ]
        }
    )

    job_id: uuid.UUID
    status: JobStatus
    cached: bool = False


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "DONE",
                    "document_type": "invoice",
                    "created_at": "2026-07-12T09:00:00Z",
                    "updated_at": "2026-07-12T09:00:05Z",
                }
            ]
        }
    )

    job_id: uuid.UUID
    status: JobStatus
    document_type: str
    created_at: datetime
    updated_at: datetime


class AttemptDetail(BaseModel):
    stage: str
    attempt_number: int
    prompt: str | None
    raw_llm_response: str | None
    validation_errors: list[dict] | None
    created_at: datetime


class JobAuditResponse(BaseModel):
    job_id: uuid.UUID
    raw_text: str | None
    attempts: list[AttemptDetail]


class JobListItem(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    document_type: str
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobListItem]
    total: int
    limit: int
    offset: int


class DocumentQueryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"fields": ["vendor_name", "total_amount"]}]}
    )

    fields: list[str] | None = Field(
        default=None,
        description="Field names to extract, used verbatim as the response's JSON keys. "
        "Omit or leave empty to let the model choose whatever fields it judges relevant.",
    )


class DocumentQueryResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "result": {"vendor_name": "Acme Corp", "total_amount": 1250.0},
                }
            ]
        }
    )

    job_id: uuid.UUID
    result: dict[str, Any]
