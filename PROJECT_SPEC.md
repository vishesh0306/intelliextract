# Project Spec: IntelliExtract — AI-Powered Document Extraction & Validation Pipeline API

## 1. One-line pitch
A backend-only, production-style REST API that ingests documents (PDFs/images), runs them through an OCR + LLM extraction pipeline with automatic validation and self-correction, and returns structured, confidence-scored JSON — built the way a real data-extraction platform would be built (async processing, queuing, caching, rate limiting, auth, observability), not as a script.

## 2. Why this project (positioning)
This project should map directly onto your S&P Global work experience (data extraction, AI output refinement, Flask/backend APIs, AWS) so that in an interview you can say: "At work I contributed to extraction and AI-refinement pipelines; I wanted to understand the full system end-to-end, so I designed and built my own version, including the production concerns — queuing, retries, validation, rate limiting — that a real system needs." That narrative consistency is worth more than the project being flashy.

Target bar: fresher backend/AI-engineering roles at 20+ LPA. At this bar, interviewers care less about "you called an LLM" and more about: does this person understand async systems, failure handling, data validation, and API design under load. Every design decision below is chosen to demonstrate one of those.

## 3. Core Workflow (end-to-end)

1. **Upload**: Client calls `POST /api/v1/documents` with a file (multipart/form-data) and a `document_type` hint (e.g. `invoice`, `resume`, `receipt`, `generic`).
2. **Validation & storage**: API validates file type/size, computes a SHA-256 hash of the file, checks cache (see §7) for an existing result with the same hash. If not cached, stores the file in S3 (or local disk in dev mode) and creates a `Job` row in Postgres with `status = PENDING`. Returns `202 Accepted` with `{ "job_id": "...", "status": "PENDING" }` immediately — the API never blocks on processing.
3. **Enqueue**: A message with the job ID is pushed onto a Redis-backed queue (Celery or RQ).
4. **Worker — Stage 1: Text/layout extraction**. A background worker pulls the job, downloads the file, and extracts raw text:
   - Native PDFs → direct text extraction (PyMuPDF / pdfplumber), preserving rough layout/page structure.
   - Scanned PDFs/images → OCR fallback (Tesseract via pytesseract).
   - Job status → `EXTRACTING`.
5. **Worker — Stage 2: AI structured extraction**. The raw text is sent to an LLM with a schema-constrained prompt (Pydantic model per `document_type`, e.g. `InvoiceFields(invoice_number, date, vendor, line_items, total)`). The LLM must return JSON matching the schema. Use function-calling / structured-output mode if the provider supports it, not free-text parsing.
   - Job status → `EXTRACTING_AI`.
6. **Worker — Stage 3: Validation & self-correction**. The extracted JSON is checked against:
   - Schema validation (types, required fields present).
   - Business rules per document type (e.g., for invoices: `sum(line_items.amount) == total`, dates are parseable and not in the future).
   - If validation fails, re-prompt the LLM once with the specific validation errors included ("the totals do not reconcile, re-check line item X") — this is the "self-correction" loop, capped at 2 retries.
   - Each field gets a confidence score (from LLM logprobs if available, else a heuristic based on whether validation passed).
   - Job status → `VALIDATING` → `DONE` or `NEEDS_REVIEW` (if still failing after retries).
7. **Persistence**: Final structured result, raw OCR text, confidence scores, and a full audit trail (every LLM call + response, every validation attempt) are stored in Postgres, linked to the job.
8. **Retrieval**: Client polls `GET /api/v1/documents/{job_id}` for status/result, or (optional, stretch goal) registers a webhook URL at upload time and the worker POSTs the result there on completion.
9. **Caching**: If the same file hash is uploaded again, the API returns the cached result instantly with `200 OK` and `"cached": true` — no reprocessing, no LLM cost.
10. **Rate limiting & auth**: Every request requires an API key (`X-API-Key` header). Each key has a token-bucket rate limit (e.g. 30 req/min) enforced via Redis. Exceeding it returns `429` with a `Retry-After` header.

## 4. API Surface (draft)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/documents` | Upload a document, returns `job_id` |
| GET | `/api/v1/documents/{job_id}` | Get status + result (if done) |
| GET | `/api/v1/documents/{job_id}/audit` | Full audit trail: raw text, every LLM attempt, validation errors |
| GET | `/api/v1/documents` | List jobs for the caller's API key (paginated) |
| POST | `/api/v1/auth/keys` | (admin-only, or seeded) issue an API key |
| GET | `/healthz` | Liveness check |
| GET | `/metrics` | Prometheus-format metrics (optional stretch) |

All responses follow a consistent envelope, all errors use a consistent error schema with an error code, and the API is versioned (`/api/v1/...`) from day one — these are small things that signal API design maturity to a reviewer.

## 5. Data Model (draft)

- `api_keys`: id, key_hash, owner_name, rate_limit_per_min, created_at
- `jobs`: id (UUID), api_key_id, document_type, file_hash, s3_key, status, created_at, updated_at
- `job_results`: job_id, extracted_json, confidence_scores (jsonb), raw_text
- `job_attempts` (audit trail): job_id, stage, attempt_number, prompt, raw_llm_response, validation_errors, created_at

## 6. Tech Stack

- **Framework**: FastAPI (async-native — matters because this workload is I/O-bound: file storage, LLM calls, DB. Async also happens to be the current market-standard for AI-backend roles; it's a natural extension of your Flask experience, not a replacement for it).
- **DB**: PostgreSQL + SQLAlchemy (async) + Alembic migrations.
- **Queue/Broker**: Redis + Celery (or RQ if you want something simpler to reason about first, then optionally migrate to Celery).
- **Storage**: AWS S3 via boto3 (local filesystem fallback behind an interface/env flag so the project runs without an AWS account for local dev).
- **OCR/parsing**: PyMuPDF or pdfplumber for native PDFs, pytesseract (Tesseract) for scanned documents/images.
- **LLM**: Any OpenAI-SDK-compatible endpoint — use a free tier (Groq, Google Gemini free tier, or OpenRouter free models) so the project costs nothing to run and demo. Abstract the LLM call behind a small interface so the provider is swappable.
- **Validation**: Pydantic v2 for both request/response schemas and the per-document-type extraction schemas.
- **Auth**: API key header, hashed at rest, checked per request.
- **Rate limiting**: Redis token-bucket (roll your own — it's a great interview talking point — or `slowapi`).
- **Testing**: pytest + httpx (async test client) + pytest-mock for mocking the LLM provider in tests (never hit a real LLM in CI).
- **CI**: GitHub Actions — lint (ruff), type-check (mypy optional), test on every push.
- **Containerization**: Docker + docker-compose (api, worker, postgres, redis — one command to run the whole stack locally).
- **Observability**: structured JSON logging (structlog) with a request/job correlation ID threaded through every log line; optional Prometheus metrics.
- **Docs**: FastAPI's auto-generated OpenAPI/Swagger UI serves as the "frontend" — no separate UI needed.

## 7. Explicitly Out of Scope (v1)
- No frontend/UI beyond Swagger docs.
- No multi-tenant billing.
- No fine-tuning of models — prompt engineering + structured output only.
- No horizontal auto-scaling setup — document the scaling story in the README instead (this is a valid and expected thing to write about, not a gap).

## 8. What "done" looks like for the resume
- A public GitHub repo with a README containing: architecture diagram (can be ASCII/Mermaid), setup instructions, and **real measured numbers** — e.g. "processes a 3-page invoice in ~Xs end-to-end," "handles Y concurrent uploads," "cache hit reduces response time from Xs to Yms." These numbers come from actually load-testing your own project (locust or a simple script), not guesses.
- At least 70%+ meaningful test coverage on the extraction/validation logic (not just trivial tests).
- One paragraph in the README explicitly explaining the self-correction retry loop and the rate-limiting design — these are the two things most likely to get asked about in an interview, so they should be documented well enough that you can re-explain them cold six months from now.
