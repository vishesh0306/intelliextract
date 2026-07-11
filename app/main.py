from fastapi import FastAPI

app = FastAPI(
    title="IntelliExtract",
    description="AI-powered document extraction & validation pipeline API",
    version="0.1.0",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
