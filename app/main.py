from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import auth, documents, metrics, ping
from app.core.error_handlers import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware

configure_logging()

app = FastAPI(
    title="IntelliExtract",
    description="AI-powered document extraction & validation pipeline API",
    version="0.1.0",
)

app.add_middleware(RequestLoggingMiddleware)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(ping.router, prefix="/api/v1", tags=["debug"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(metrics.router, tags=["health"])


@app.get(
    "/healthz",
    tags=["health"],
    summary="Liveness check",
    description="Unauthenticated. Returns 200 as long as the API process is up "
    "— doesn't check DB/Redis connectivity.",
)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
