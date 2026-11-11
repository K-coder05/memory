# Recall — Build Checklist

## Checkpoint 1 — Django API + Postgres (Day 1)

- [ ] Set up `docker-compose` with two services: `web` (Django) and `db` (Postgres 16)
- [ ] Models: `Source` (gmail/slack/zoom, FK to user) and `Memory` (FK to user and source, `content` text, `occurred_at`, `metadata` JSONB, `created_at`)
- [ ] Endpoints: `POST /memories`, `GET /memories/{id}`, `GET /memories?source=&since=&q=` (use `icontains` for now; full-text search comes in Checkpoint 2), paginated
- [ ] Scope every query to the requesting user, and write a test that proves user A can't read user B's memories
- [ ] Write at least 5 `pytest-django` tests, plus a `seed` management command that loads 100k fake memories with Faker and `bulk_create`
- [ ] Turn on SQL logging or django-debug-toolbar, then find and fix one N+1 query

## Checkpoint 2 — PostgreSQL optimization + hybrid search (Day 2)

- [ ] Load 2–5M memories with `generate_series` or the seed command
- [ ] Get baseline `EXPLAIN (ANALYZE, BUFFERS)` plans for four queries: latest 20 memories for a user, a user's memories in a date range, a JSONB metadata filter, and keyword search
- [ ] Add a composite `(user_id, occurred_at DESC)` index, a GIN index on `metadata`, a generated `tsvector` column with a GIN index, and `pg_trgm` for fuzzy search. Re-measure each query and log before/after in `NOTES.md`
- [ ] Switch the list endpoint to keyset (cursor) pagination and compare it against `OFFSET 100000`
- [ ] Enable `pg_stat_statements` and find the query with the highest total time
- [ ] Port my RAG search engine's retrieval to Postgres: install pgvector, add an `embedding` column, build an HNSW index, and combine vector similarity with `tsvector` full-text ranking using rank fusion. Compare latency and top-5 hit rate against my Pinecone numbers (under 300 ms, ~85%) and write down the trade-offs: ops cost, filtering by tenant, joins with relational data, scale limits

## Checkpoint 3 — Redis caching + rate limiting (Day 3)

- [ ] Add Redis to `docker-compose` and use `django-redis` as the cache backend
- [ ] Cache-aside on `GET /memories/{id}`, with key `memory:{user}:{id}` and a TTL of ~300 s plus jitter. Invalidate it on update and delete
- [ ] Cache each user's "recent memories" list. Invalidate it on a new memory, or use versioned keys: bump a per-user version counter so old keys stop being read
- [ ] Build a rate limiter, either a sliding window on a sorted set or a token bucket in Lua. Return 429 with a `Retry-After` header
- [ ] Measure p50 and p95 latency with and without the cache using `hey`, `wrk` or Locust, and log the results in `NOTES.md`
- [ ] Cause a stampede by expiring a hot key under load, then fix it with a lock

## Checkpoint 4 — Kafka async ingestion (Day 4)

- [ ] Add a single-broker Kafka (KRaft mode) to `docker-compose`
- [ ] Make `POST /memories` save the row with `status=pending` and publish a `memory.ingested` event keyed by `user_id`
- [ ] Bonus: add a transactional outbox table and a relay process, so the DB write and the publish can't get out of sync
- [ ] Write a worker with `confluent-kafka-python` that consumes the event, enriches the memory (extract keywords; compute or fake an embedding) and updates the row. Make it idempotent by checking the memory id and status before processing
- [ ] Send a message to a DLQ topic after 3 failures. Kill the worker mid-stream and confirm nothing is lost

## Checkpoint 5 — Monitoring with Prometheus + Grafana (Day 4)

- [ ] Add Prometheus and Grafana to `docker-compose`. Use `django-prometheus` on the web app and `prometheus_client` in the worker (Kafka, Postgres and Redis exporters optional)
- [ ] Build a dashboard with request rate, error rate, p95 latency, cache hit ratio, consumer lag and ingest throughput
- [ ] Add one alert rule: p95 above 500 ms for 5 minutes, or consumer lag above 1,000

## Checkpoint 6 — CI + infrastructure as code (Day 4)

- [ ] Write `.github/workflows/ci.yml` that runs lint (ruff), then pytest against a Postgres service container, then `docker build`, with pip caching
- [ ] Write a ~20-line Terraform `main.tf` for a managed Postgres plus a managed Redis. Don't apply it
- [ ] Use a multi-stage Dockerfile for the web app and worker

## Checkpoint 7 — Ship it (Day 5)

- [ ] README: architecture diagram, `docker compose up` instructions, and a results table built from `NOTES.md`
- [ ] Push to GitHub and pin the repo