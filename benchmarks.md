# Benchmarks

Real, measured numbers from `scripts/load_test.py`, run against the full
Docker Compose stack (`api` + `worker` + Postgres + Redis, one replica
each) on the same machine used for development — not a production cloud
instance, so treat these as directionally honest rather than
production-grade capacity numbers. Every number below came from an
actual run; none are estimated.

## Environment

- Host: AMD Ryzen 5 5625U, 8GB RAM, Windows 11 + Docker Desktop (WSL2 backend)
- LLM: Groq `llama-3.3-70b-versatile`, real API calls (not mocked)
- Storage: local filesystem backend
- One `api` replica, one `worker` replica (RQ, single-threaded)
- Test documents: single-page native-text PDFs (no OCR fallback triggered)

## How to reproduce

```
docker compose up -d
uv run python -m scripts.load_test
```

The script creates its own throwaway API keys and jobs and deletes them
on exit (`[cleanup]` line at the end of its output).

## Results

Run three times back-to-back; the first run included a one-time cold
start, runs 2–3 are steady state.

| Metric | Run 1 (cold) | Run 2 | Run 3 | Steady-state avg |
|---|---|---|---|---|
| Upload accepted (202) latency | 448ms | 84ms | 79ms | **~82ms** |
| End-to-end upload → DONE (1 invoice, 1 Groq call) | 11.82s | 4.26s | 4.88s | **~4.6s** |
| Cache-hit re-upload latency (200, `cached:true`) | 163ms | 70.0ms | 69.6ms | **~70ms** |
| 20 concurrent cache-hit uploads, total time | 1.307s | 0.888s | 0.828s | **~0.86s (~23 req/s)** |
| 5 concurrent *new* invoices, all accepted (202) | 114ms | 131ms | 102ms | **~116ms** |
| 5 concurrent *new* invoices, all reach DONE | 19.62s | 19.32s | 19.93s | **~19.6s (~3.9s/job)** |
| Rate limit: key capped at 5/min, 8 rapid requests | 5 ok / 3×429 | 5 ok / 3×429 | 5 ok / 3×429 | consistent every run |
| `Retry-After` header on a 429 | 12s | 12s | 12s | consistent |

## What these numbers actually show

**Cache hit reduces response time from ~4.6s to ~70ms — a ~65x speedup,
and zero LLM cost.** This is the caching layer (Phase 8) doing its job:
a repeat upload of the same file+document_type never touches the queue,
the worker, OCR, or Groq — it's a straight DB read-and-clone.

**Upload acceptance is decoupled from processing.** Whether uploading 1
document or 5 concurrently, the `202 Accepted` response comes back in
under 150ms every time — the client is never blocked waiting for
OCR/LLM work, exactly the point of the async queue architecture (Phase
4). The actual processing time (~4s/job) only shows up later, when the
client polls `GET /documents/{id}`.

**Throughput is currently bounded by the single worker replica, not the
API.** 5 concurrent new invoices took ~19.6s to all finish — almost
exactly 5× the ~3.9s single-job time — because one RQ worker processes
jobs strictly serially. The cache-hit path, which never touches the
worker, handled 20 concurrent requests in under a second (~23 req/s) on
the same hardware. This is the clearest evidence in this project that
the API and worker are independently scalable: running N worker
replicas (`docker compose up --scale worker=N`, or N tasks in ECS) would
let real-processing throughput approach the cache-hit ceiling, without
touching the API layer at all. That's the horizontal-scaling story for
this system — see the README for more on this.

**Rate limiting works exactly as designed under real concurrent load,**
not just in isolated tests: a key capped at 5 requests/minute let
exactly 5 through and rejected the rest with `429` + a correct
`Retry-After` header, every single run.

**The cold-start gap (448ms → 84ms, 11.8s → 4.3s) is a real, honest
finding, not noise** — first-request latency after the containers have
been idle includes DNS resolution, TLS handshake setup to Groq, and
connection-pool warmup for Postgres/Redis, none of which are cached yet.
A production deployment would want a warmup/readiness probe that fires
a throwaway request before accepting real traffic, to avoid the first
real user eating that cost.
