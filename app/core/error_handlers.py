import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.errors import ErrorCode, ErrorDetail, ErrorResponse

logger = structlog.get_logger()

# Fallback only — every HTTPException we raise ourselves passes an explicit
# {"code": ..., "message": ...} detail (see app/api/deps.py,
# app/api/v1/*.py). This covers anything from FastAPI/Starlette itself
# (e.g. a plain 404 for a route that doesn't exist).
_DEFAULT_CODE_BY_STATUS: dict[int, ErrorCode] = {
    401: ErrorCode.INVALID_API_KEY,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


def _error_response(
    status_code: int, code: ErrorCode, message: str, headers: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump(
            mode="json"
        ),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = ErrorCode(exc.detail["code"])
        message = exc.detail.get("message", "")
    else:
        code = _DEFAULT_CODE_BY_STATUS.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = str(exc.detail)

    return _error_response(exc.status_code, code, message, headers=exc.headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    message = "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
    return _error_response(422, ErrorCode.VALIDATION_ERROR, message)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Without this, anything that isn't an HTTPException (a missing env
    var, an unexpected library error) falls through to FastAPI's default
    handler — a bare "Internal Server Error" with no JSON body, breaking
    the "every error uses the same envelope" promise. The real exception
    is logged server-side (with the request/job_id context already bound
    by the logging middleware); the client only gets a generic message —
    exception details are an internal implementation detail, not
    something to hand back to an API caller.
    """
    logger.error("unhandled_exception", exc_info=exc)
    return _error_response(
        500, ErrorCode.INTERNAL_ERROR, "An unexpected error occurred. Please try again."
    )
