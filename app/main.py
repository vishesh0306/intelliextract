from fastapi import FastAPI

from app.api.v1 import ping

app = FastAPI(
    title="IntelliExtract",
    description="AI-powered document extraction & validation pipeline API",
    version="0.1.0",
)

app.include_router(ping.router, prefix="/api/v1", tags=["debug"])


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
