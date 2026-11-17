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
| Q4a icontains common word | Same plan + filter `upper(content) LIKE` (~6.9k matches), 158,791 buffers read, **617 ms** | Bitmap Index Scan on `memory_content_trgm` (97k candidates) → Bitmap Heap Scan, 449k rows removed by recheck, 6.9k matches; **1,565 ms** | SLOWER than baseline: trigram index estimated 36 rows, actually 6,930; the bitmap path loses to the old plan for common words |
| Q4b icontains no match | Same plan + filter, 0 rows out, 158,790 buffers read, **585 ms** | Bitmap Index Scan on `memory_content_trgm`, 0 candidates; **0.3 ms** | expression GIN `UPPER(content) gin_trgm_ops` (859 MB) |
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

### 6d: trigram index for `?contains=`
- `migrate` (extension + `CREATE INDEX ... USING gin ((UPPER("content")) gin_trgm_ops)`): **206 s**. `memory_content_trgm` is **859 MB**, bigger than every other index combined and ~1/3 of the table.
- Q4b (no match): 585 ms baseline → **0.3 ms**. The index knows no trigram combination exists.
- Q4a (common word, ~6.9k matches for user0) got **slower**, 617 ms → 1,565 ms. The index matches 97k rows across all users (trigram search ignores `user_id`), then the heap scan rechecks them, discarding 449k lossy-index candidates. The planner estimated 36 rows, so it picked the bitmap plan. A trigram index only pays off for rare substrings; for common ones a plain scan of the user's rows is cheaper.
- Fuzzy search works: `UPPER('finacial') <% UPPER(content)` with `pg_trgm.word_similarity_threshold = 0.5` returns rows containing "financial". With `LIMIT 5` the planner used a Seq Scan and finished in 2.7 ms because matches are dense.

### 6e: write cost of the indexes
- Seed 20,000 memories: **946 rows/s** (21.1 s), vs **4,925 rows/s** in Checkpoint 1 with 3 indexes. Now 6 indexes (pkey, source_id, composite btree, metadata GIN, search GIN, trigram GIN) plus the stored `tsvector` computed per row. Caveat: the table is also 50x bigger now (5M vs 100k rows), so this isn't a pure index comparison.
- Index sizes after `VACUUM ANALYZE`: trigram 865 MB, search GIN 184 MB, composite btree 193 MB, metadata GIN 68 MB (+ pkey and source_id btrees). Table 2,696 MB.


### 8: pg_stat_statements (after)
Reset stats, then `.\scripts\load.ps1 -Rounds 10` (50 requests as user0, same traffic mix as before). Top 3 by total time:

| calls | total_ms | mean_ms | rows | query |
|---|---|---|---|---|
| 20 | 95,924 | 4,796.2 | 210 | `search_vector @@ websearch_to_tsquery(...)` ORDER BY occurred_at DESC LIMIT |
| 20 | 19 | 1.0 | 420 | `WHERE user_id = $1` ORDER BY ... LIMIT (`/memories` and `?page=5000`, which is now the same request) |
| 10 | 3 | 0.3 | 210 | `WHERE user_id = $1 AND occurred_at >= $2` ORDER BY ... LIMIT (`?since=`) |

- The full-text search is now essentially the whole bill: ~96 s of ~96 s total. `?q=meeting` and `?q=zqxjvk` normalize into the same row, so the 4.8 s mean is the average of fast calls (matches are dense, the scan stops after 20) and slow ones. The slow ones are the no-match term, which walks all of user0's rows newest-first (see Q5b in 6c: the planner doesn't use `memory_search_gin` together with the `user_id` filter). My inference is that the 10 no-match calls cost ~9.5 s each; I didn't time them separately.
- No `SELECT COUNT(*)` appears any more: cursor pagination needs no count. The listing and `?since=` queries are ~1 ms each, so the composite index plus cursor pagination removed them from the top of the list.
- `?page=5000` in `load.ps1` is ignored by `CursorPagination` and just returns the first page, so that request is now a copy of `/memories`.
- Compared with the earlier "highest total_ms" table (taken from `bench.sql` EXPLAINs, ~620 ms each, not from API traffic), the list/date queries went from ~600 ms to ~1 ms. Only search is left worth optimizing, and mostly for the rare/no-match term (a per-user GIN via `btree_gin`, or a `(user_id, search_vector)` strategy, would be the next experiment).
