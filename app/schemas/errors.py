import enum

from pydantic import BaseModel, ConfigDict


class ErrorCode(enum.StrEnum):
    MISSING_API_KEY = "MISSING_API_KEY"
    INVALID_API_KEY = "INVALID_API_KEY"
    RATE_LIMITED = "RATE_LIMITED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"error": {"code": "JOB_NOT_FOUND", "message": "Job not found"}}]
        }
    )

    error: ErrorDetail
