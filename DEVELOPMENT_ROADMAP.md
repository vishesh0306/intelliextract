# Development Roadmap: IntelliExtract

This is the build order. Each phase produces something runnable and testable before moving to the next — never jump ahead to AI/queueing before the plain CRUD skeleton works. This order is also how you should narrate the project in an interview: "I built it incrementally, X first because Y."

## Phase 0 — Project scaffolding
- Initialize repo, `pyproject.toml`/`requirements.txt`, pre-commit hooks (ruff/black).
- Set up `docker-compose.yml` with empty service stubs for api, postgres, redis (worker added later).
- Set up GitHub Actions CI skeleton (runs lint on push, tests come later).
- Deliverable: `docker-compose up` boots an empty FastAPI app that responds on `/healthz`.

## Phase 1 — Data model & migrations
- Define SQLAlchemy models: `api_keys`, `jobs`, `job_results`, `job_attempts`.
- Set up Alembic, write the initial migration.
- Deliverable: migrations run cleanly against the dockerized Postgres; can insert/query rows via a throwaway script.

## Phase 2 — Auth & rate limiting (build this early, not last)
- API key generation + hashed storage.
- Middleware/dependency that validates `X-API-Key` on protected routes.
- Redis-backed token-bucket rate limiter, wired in as middleware.
- Deliverable: a protected test endpoint that returns 401 without a key, 429 when rate-limited, 200 otherwise. Write tests for all three cases now — this logic is easy to verify in isolation and painful to retrofit later.

## Phase 3 — Upload & storage
- `POST /api/v1/documents`: accept multipart upload, validate file type/size, compute SHA-256 hash.
- Storage abstraction: an interface with two implementations (local filesystem for dev, S3 for prod), selected by env var.
- Create the `jobs` row with `status=PENDING`, return `202` with `job_id`.
- Deliverable: can upload a PDF via curl/Postman and see a job row appear with status PENDING and the file present in storage.

## Phase 4 — Queue + worker skeleton
- Stand up Redis as the broker, add Celery (or RQ) worker service to docker-compose.
- Wire the upload endpoint to enqueue a job containing the `job_id`.
- Worker: minimal task that just flips `status` to `DONE` (no real processing yet) — this proves the plumbing works before adding complexity.
- Deliverable: upload a file, poll `GET /api/v1/documents/{id}`, watch status go `PENDING` → `DONE` without touching any AI code yet.

## Phase 5 — Text/layout extraction stage
- Implement extraction: native PDF text (PyMuPDF/pdfplumber) with OCR fallback (pytesseract) for scanned docs/images.
- Worker calls this in the `EXTRACTING` stage, stores raw text on `job_results`.
- Deliverable: unit tests with a few sample PDFs/images (native + scanned) in a `tests/fixtures/` folder, asserting extracted text contains expected substrings.

## Phase 6 — AI structured extraction
- Define per-`document_type` Pydantic schemas (start with just `invoice` — one type end-to-end beats three half-done types).
- Build the LLM client abstraction (interface + one concrete implementation for your chosen free-tier provider).
- Prompt design: system prompt + schema + raw text → structured JSON response (use the provider's structured-output/function-calling mode).
- Worker calls this in `EXTRACTING_AI` stage, stores result + raw prompt/response in `job_attempts` (this is your audit trail).
- Deliverable: mock the LLM client in tests (never call a real LLM in CI); one real end-to-end manual test with an actual invoice PDF.

## Phase 7 — Validation & self-correction loop
- Implement schema validation + business-rule validation (e.g. totals reconcile) for the `invoice` type.
- On failure, build the retry path: re-prompt with the specific validation errors, cap at 2 retries, then mark `NEEDS_REVIEW` if still failing.
- Confidence scoring per field.
- Deliverable: tests that simulate a bad first LLM response (via the mocked client) and assert the retry logic kicks in, then a test that exhausts retries and lands on `NEEDS_REVIEW`. This phase is the centerpiece of your interview story — spend real time here.

## Phase 8 — Caching
- On upload, check `file_hash` against existing completed jobs before creating a new one; short-circuit to return the cached result.
- Deliverable: upload the same file twice, second call returns instantly with `"cached": true`, and you can prove via logs/metrics that no LLM call happened the second time.

## Phase 9 — Audit trail & full API surface
- `GET /api/v1/documents/{id}/audit` returning every attempt, prompt, and validation error.
- `GET /api/v1/documents` (paginated list, filtered to caller's API key).
- Consistent error envelope across all endpoints.
- Deliverable: Swagger docs at `/docs` fully describe every endpoint with examples.

## Phase 10 — Observability
- Structured JSON logging with a correlation/job ID threaded through every log line across API + worker.
- (Stretch) `/metrics` endpoint in Prometheus format — job counts by status, average processing time, cache hit rate.
- Deliverable: can `grep` logs by job_id and see the full lifecycle of a request across both the API process and the worker process.

## Phase 11 — Load testing & numbers for the README
- Write a small load-testing script (locust, or even a plain asyncio script hitting the API concurrently).
- Measure: end-to-end latency for a typical document, cache-hit latency, throughput under N concurrent uploads, effect of rate limiting.
- Deliverable: a `benchmarks.md` or a section in the README with real numbers — this is what turns "I built a project" into "I understand production tradeoffs."

## Phase 12 — Docs, polish, deploy
- Finalize README: architecture (Mermaid diagram), setup steps, API examples, the self-correction and rate-limiting write-ups, benchmark numbers.
- Ensure `docker-compose up` is genuinely one command to a fully working stack.
- (Optional) Deploy: containers to AWS ECS/Fargate or a single EC2 box, RDS for Postgres, S3 already wired in Phase 3. Even a basic live deployment link in the README is a strong signal.
- Final pass: test coverage report, lint clean, CI green.

## Sequencing notes
- Do not build Phase 6 (AI extraction) before Phase 4 (queue plumbing) works with a no-op task — debugging async + AI failures simultaneously is miserable.
- Auth/rate-limiting (Phase 2) is deliberately early. It's a small, self-contained, highly testable piece of work that's easy to point to in an interview ("here's exactly how I implemented token-bucket rate limiting"), and it's a common interview follow-up question regardless of whether it was your main project.
- Keep every phase's deliverable actually running and committed before moving on — the roadmap is designed so you always have a working project, just with less functionality, rather than a broken one with more functionality.
