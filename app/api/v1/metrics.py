from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.metrics import render_prometheus_metrics

router = APIRouter()


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus-format metrics",
    description="Unauthenticated, like /healthz. Job counts by status, "
    "average processing time for genuinely-processed (non-cached) DONE "
    "jobs, and the cache hit ratio.",
)
async def metrics(db: Annotated[AsyncSession, Depends(get_db)]) -> PlainTextResponse:
    body = await render_prometheus_metrics(db)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
