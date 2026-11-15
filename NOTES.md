## Checkpoint 1
- Seed: 100,000 memories in 20.3 s (4925 rows/s) with bulk_create, batch 5,000
- N+1 on GET /memories: 22 queries → 2 queries per page after select_related("source")

# Entry 1.1
- docker compose exec db psql -U recall -c "SELECT count(*) FROM memories_memory;"
- 10002 memories
- docker compose exec db psql -U recall -c "SELECT metadata FROM memories_memory LIMIT 3;"
- metadata of dictionaries of fields and values

## Checkpoint 2
- Copied: 4,900,000 memories across 200 users in 2:06 minutes
- Results Table

Data: 5,000,000 memories, 200 users (user0 = 356,496), table 1.4 GB (1.6 GB with indexes), VACUUM ANALYZE done.
Benchmark user: user0. Times are warm runs from sql/bench.sql.

| Query | Before: plan, time | After: plan, time | What changed |
|---|---|---|---|
| Q1 latest 20 | Parallel Bitmap Heap Scan on user_id index → Hash Join source → top-N sort; reads all 356k of the user's rows to return 20, 158,783 buffers read, **573 ms** | Index Scan on `memory_user_recent_idx`, no Sort, 20 rows read; **0.44 ms** | composite index `(user, -occurred_at, -id)` serves filter and order at once |
| Q2 date range | Same plan + filter on occurred_at (removes 115k rows/worker), 158,785 buffers read, **505 ms** | Same index scan, stops after 20 rows; **0.45 ms** | same composite index; `occurred_at` range is an index condition |
| Q3 JSONB sender | Same plan + filter `metadata @>` (6 rows out of 356k), 158,789 buffers read, **586 ms** | Bitmap Index Scan on `memory_metadata_gin` → Bitmap Heap Scan, 6 rows; **2.2 ms** | GIN `jsonb_path_ops` on `metadata` (65 MB) |
| Q4a icontains common word | Same plan + filter `upper(content) LIKE` (~6.9k matches), 158,791 buffers read, **617 ms** | | |
| Q4b icontains no match | Same plan + filter, 0 rows out, 158,790 buffers read, **585 ms** | | |
| Q5a full-text, common word | new query (compare Q4a: 617 ms) | Index Scan on `memory_user_recent_idx` with `search_vector @@` as filter, stops after 20 matches; **4.2 ms** | planner walks newest-first and finds 20 matches quickly, so it skips `memory_search_gin` |
| Q5b full-text, no match | new query (compare Q4b: 585 ms) | Index Scan on `memory_user_recent_idx` with filter, 0 rows out, walks all of user0's rows; **1,400 ms** | did NOT use `memory_search_gin` (see below) |

Queries with the highest `total_ms`:
 calls | total_ms | mean_ms | rows |                                                     query
-------+----------+---------+------+----------------------------------------------------------------------------------------------------------------
     2 |     1237 |   618.7 |    0 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem
     2 |     1235 |   617.4 |   20 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem
     1 |      618 |   618.0 |    0 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem

### 6b: GIN selectivity experiment
`metadata @> '{"labels": ["travel"]}'` for user0 with `LIMIT 20` does a Seq Scan and stops after 20 matches (2.3 ms), ignoring the GIN index. About a quarter of rows match, so scanning until 20 are found is cheaper than building and intersecting a bitmap of tens of thousands of rows. An index is only worth using when the predicate is selective.

### 6c: full-text search (generated tsvector column)
- `migrate` (ADD COLUMN ... GENERATED ALWAYS AS (to_tsvector('english', content)) STORED + GIN index) took **186 s** on 5M rows. It rewrites the whole table under an exclusive lock.
- Table size 1.4 GB → **2,695 MB**. `memory_search_gin` is 180 MB.
- Stored vector looks like `'accept':9 'arriv':14 'black':5 ...`: stemmed ("everybody" → "everybodi"), with positions, stop words removed.
- Q5b did not use the GIN index, unlike the guide predicted. For a word that is absent from the table the planner estimates ~1,800 matching rows for user0, so walking `memory_user_recent_idx` newest-first and filtering looks cheaper than a bitmap, but with 0 real matches it reads the user's whole history (~1.4 s). The GIN index would answer "no row anywhere has this word" instantly, but the `user_id` filter is on the btree, so the planner has no cheap way to combine them. Compare Q4b (1.7 s) to Q5b: the tsvector filter is only a little cheaper than `UPPER(content) LIKE` per row.
