from fastapi import FastAPI

from app.api.v1 import documents, ping

app = FastAPI(
    title="IntelliExtract",
    description="AI-powered document extraction & validation pipeline API",
    version="0.1.0",
)

app.include_router(ping.router, prefix="/api/v1", tags=["debug"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
