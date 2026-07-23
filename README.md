# IntelliExtract 🚀

**Upload a document. Get validated, structured JSON back. No babysitting required.**

An async REST API that ingests PDFs/images, runs them through OCR + LLM
extraction, validates the output against real business rules, self-corrects
when it's wrong, and caches so you never pay for the same document twice.
Built the way a real extraction platform is built — not a script with an
LLM call bolted on.

Why: I do extraction + AI-refinement pipeline work at S&P Global and wanted
to build the *whole* thing myself — queuing, retries, validation, rate
limits, caching, observability — not just the "call the LLM" part.

## The gist

- 📤 Upload → **`202` instantly**, real work happens async in the background
- 🧾 Native PDF text, or Tesseract OCR fallback for scans/images
- 🤖 Structured extraction via Groq, checked against real math (do the numbers add up?)
- 🔁 Wrong answer? Self-corrects — re-prompts the LLM with the *exact* error, up to 2 retries
- ⚡ Same file twice? Cached. **~4.6s → ~70ms**, zero LLM cost
- 🔍 Don't want the fixed schema? `/query` any document for whatever fields you want — invoice, resume, anything
- 🔐 API keys + atomic Redis rate limiting (a real token bucket, not a toy)
- 📊 Structured JSON logs, one `job_id` traceable across the API *and* worker processes

## Architecture

```mermaid
flowchart LR
    Client([Client])

    subgraph API[api service]
        FastAPI[FastAPI]
    end

    subgraph Worker[worker service]
        RQWorker[RQ Worker]
    end

    Postgres[(PostgreSQL)]
    Redis[(Redis)]
    Storage[(Storage\nlocal disk / S3)]
    Groq[Groq LLM API]

    Client -- "POST /documents\n(multipart upload)" --> FastAPI
    FastAPI -- "validate, hash,\ncheck cache" --> Postgres
    FastAPI -- "save file" --> Storage
    FastAPI -- "enqueue job_id" --> Redis
    FastAPI -- "202 job_id" --> Client

    Redis -- "dequeue job_id" --> RQWorker
    RQWorker -- "read file" --> Storage
    RQWorker -- "OCR / native text" --> RQWorker
    RQWorker -- "structured extraction" --> Groq
    RQWorker -- "status, result,\naudit trail" --> Postgres

    Client -- "GET /documents/{id}\n(poll)" --> FastAPI
    FastAPI -- "read status/result" --> Postgres
```

Upload → validate/hash/cache-check → queue → **`202` back immediately**. A
separate worker does the real work (OCR, LLM calls, validation) and updates
the DB as it goes. The client polls. The API never blocks on processing —
accept fast, work async, that's the whole design.

## API surface

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/documents` | Upload a document, returns `job_id` |
| `GET` | `/api/v1/documents/{job_id}` | Get status + result |
| `GET` | `/api/v1/documents/{job_id}/audit` | Full audit trail — raw text, every LLM attempt, validation errors |
| `POST` | `/api/v1/documents/{job_id}/query` | Ask for specific (or open-ended) fields from any processed document |
| `GET` | `/api/v1/documents` | List jobs for your key (paginated) |
| `POST` | `/api/v1/auth/keys` | Issue an API key (admin-only, `X-Admin-Key`) |
| `GET` | `/healthz` | Liveness check |
| `GET` | `/metrics` | Prometheus-format metrics |

Every error comes back in the same shape (`{"error": {"code", "message"}}`).
Versioned from day one (`/api/v1/...`). Full interactive docs + examples at
`/docs` once the stack's up.

## Get it running

```bash
git clone https://github.com/vishesh0306/intelliextract.git
cd intelliextract
cp .env.example .env   # add GROQ_API_KEY — free @ console.groq.com
docker compose up -d --build
```

That's it. One command. Migrations run automatically, health checks gate
`api`/`worker` startup — fresh clone to fully working stack, zero manual
steps.

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

**Get yourself an API key:**

```bash
uv run python -m scripts.create_api_key --owner me --rate-limit 30
```

(or `POST /api/v1/auth/keys` with `X-Admin-Key`, if you've set `ADMIN_API_KEY`)

**Upload something:**

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -H "X-API-Key: <your key>" \
  -F "file=@invoice.pdf;type=application/pdf" \
  -F "document_type=invoice"
# {"job_id": "...", "status": "PENDING", "cached": false}

curl http://localhost:8000/api/v1/documents/<job_id> -H "X-API-Key: <your key>"
```

**Or skip curl entirely** — hit `http://localhost:8000/docs`, click "Try it
out" on any endpoint. Swagger does the rest.

**Run the tests:**

```bash
uv run pytest -v                                    # 71 tests, ~10s
uv run pytest --cov=app --cov-report=term-missing    # 93% coverage
```

Real Postgres/Redis, but the LLM is always mocked — no test ever calls the
real Groq API, so the suite is deterministic and CI-safe.

## The interesting engineering bits

**Self-correction loop** — the LLM gets one shot at structured extraction,
the output gets checked against real business rules (line items sum to the
total, tax/discount/adjustments reconcile, the date isn't nonsense). Fails?
Gets re-prompted with the *specific* error, not "try again." Up to 3
attempts total. Still no good? → `NEEDS_REVIEW`, not `FAILED` — those mean
different things — and the model's best attempt is kept, not thrown away.

**Rate limiting** — a token bucket, entirely in Redis, evaluated as one
atomic Lua script. Why that matters: a naive `GET`-then-`SET` from Python
has a race window where two concurrent requests both read the same count
and both spend a token — over-admitting under load. One atomic script
closes that gap completely.

**Caching** — storage keys are content-addressed (SHA-256 of the file).
Re-upload the same file? Instant clone of the cached result under a *new*
`job_id` (ownership-scoped, so you never see someone else's job), zero LLM
cost, zero reprocessing.

**Ask-anything queries** — `/query` skips the fixed schema entirely. Ask for
exact fields (`{"fields": ["vendor_name"]}`) or send nothing and let the
model decide what's relevant. Works on any document type. No business-rule
validation here — there's no generalizable "does this reconcile" check for
a resume — just one retry if the JSON comes back broken.

**Observability** — every log line is JSON, correlated by `request_id` and
`job_id` across *both* the API and worker processes. `grep` one `job_id`,
see that job's entire life story.

## Real numbers, not vibes

Full breakdown in [benchmarks.md](benchmarks.md). TL;DR:

- Cache hit: **~65x faster** — ~4.6s down to ~70ms
- Upload stays under ~150ms no matter the load — proves the async queue
  actually decouples "accept" from "process"
- 1 worker replica processes jobs serially (~3.9s/job); the cache-hit path
  alone does ~23 req/s on the same hardware — API and worker scale
  *independently*
- Rate limiting held exactly at 5/min under real concurrent load, every
  single run, with a correct `Retry-After` header

## Coverage: 93%

`extraction.py` and `validation.py` — the logic that actually matters — sit
at **100%**. CI enforces a 70% floor. The honest 0%s: `storage/s3.py` (no
real AWS creds to test against) and the worker's process entrypoint
(verified live in Docker instead — not meaningfully unit-testable).

## If this had to scale tomorrow

No autoscaling wired up (deliberately out of scope for v1), but the shape's
already there for it:

- **Worker and API scale independently** — they only talk through Redis,
  neither knows how many instances of the other exist
- **API is stateless** → put a load balancer in front, done
- **Storage already has an S3 interface** — `STORAGE_BACKEND=s3` away from
  multi-instance-ready, no code changes
- **Real deploy** = RDS + ElastiCache + two ECS Fargate services, `api`
  scaled on request rate, `worker` scaled on queue depth. Infra changes
  only, zero code changes.

## Stack

FastAPI (async) · PostgreSQL + SQLAlchemy (async) + Alembic · Redis + RQ ·
PyMuPDF + Tesseract OCR · Groq (OpenAI-compatible SDK) · Pydantic v2 ·
structlog · pytest + httpx + pytest-cov · Docker Compose · GitHub Actions
CI · uv

## License

MIT — see [LICENSE](LICENSE).
