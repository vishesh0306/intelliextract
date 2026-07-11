import enum
import uuid

from pydantic import BaseModel

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
    job_id: uuid.UUID
    status: JobStatus
