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


## Checkpoint 2, part 9: pgvector vs Pinecone

### 9a: Pinecone baseline (measured, not remembered)
Setup of the RAG project (`Projects/rag`, Paul Graham essays + YC Startup Library):
- Embedding model `gemini-embedding-001`, **3072 dimensions**, cosine. Queries use task type RETRIEVAL_QUERY, chunks were embedded as documents.
- Pinecone serverless (aws us-east-1), index `startup-library`, namespace `startup-library`: **10,704 chunks** (chunk size 1000, overlap 200).
- Eval set: 18 hand-written questions, of which **14 have an expected source** (4 are out-of-scope and have none, so they can't be a "hit"). With 14 questions, one question is 7 percentage points. Treat all hit rates here as rough.
- A **hit** = one of the top-5 returned chunks comes from one of the question's `expected_sources` URLs (the eval set has no chunk ids, so the comparison is by source document).
- Exported with `eval/export_pinecone.py` (chunk text, source URL and the stored Pinecone vectors) so Postgres is tested on the **identical vectors**; `eval/pinecone_baseline.py` produced the numbers (3 timed runs per query, 1 warm-up, from my Windows machine over the internet):

| mode | hit@5 | p50 | p95 | what the latency includes |
|---|---|---|---|---|
| Pinecone dense | 13/14 (93%) | 93 ms | 206 ms | the `index.query` call only: network round trip + search |
| Pinecone dense + BM25 (RRF), as in `main.py` | 14/14 (100%) | 148 ms | 179 ms | the Pinecone call plus BM25 scoring of all 10,704 chunks in Python |
| query embedding (Gemini API) | n/a | 205 ms | 245 ms | one `embed_query` call, same for any vector store |

End to end (embedding + retrieval) the Pinecone dense path is about 300 ms at p50, which matches the "<300 ms" I remembered only if the embedding is included.

### 9c–9f: loading the data and building the HNSW index
- **Vector type:** `gemini-embedding-001` gives 3072 numbers, and pgvector's `vector` type can only be indexed up to 2000 dimensions. I used `halfvec(3072)` (16-bit floats, indexable up to 4000). Cost: the stored vectors are rounded from the float32 ones Pinecone holds, 6 KB per vector instead of 12 KB.
- **9c** `ADD COLUMN embedding halfvec(3072) NULL` on 5M rows: whole `migrate` (extension + column) took **1.9 s**. A nullable column without a default only changes the table definition (compare the 186 s generated column in 6c).
- **9e** `load_corpus`: 10,704 chunks with their **existing Pinecone vectors** in **43 s**, no API calls. `embed_memories`: 50,000 fake memories embedded through the Gemini API in about **24 min** (100 texts per request, 1 s delay between requests). After that, 60,704 of 5,030,704 rows have an embedding: `rag_eval` has 10,704 (**17.6% of the index**), and the rest are spread over 199 other users at ~5k each.
- **9f** `CREATE INDEX ... USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)` built in **40.6 s**, index size **473 MB** for 60,704 vectors, about 7.8 KB per vector (more than the 6 KB vector itself, because of the graph links). The 4.97M NULL rows aren't in the index, but the build still had to read the whole 3 GB table.
- Table (with TOAST) 2,696 MB → 3,207 MB. Of that, 474 MB is TOAST: the 6 KB vectors don't fit in the 8 KB page with the rest of the row, so Postgres stores them out of line.

### 9g: why the hybrid test passes (RRF by hand)
Query "budget" with vector `unit(0)`, k = 60. Vector list: `both` (distance 0) and `vector_only` (distance 0) tie for rank 1, `keyword_only` (distance 1) is rank 3. Keyword list: `both` and `keyword_only` match (equal `ts_rank_cd`, rank 1 each); `vector_only` has no match.
- `both` = 1/61 + 1/61 = **0.03279**
- `keyword_only` = 1/63 + 1/61 = 0.03226
- `vector_only` = 1/61 + 0 = 0.01639

A document found by both lists wins because it collects two terms. The margin over `keyword_only` is tiny (1/61 vs 1/63 for the vector term), so "found by both" is a strong signal but not an overwhelming one.

I changed the guide's SQL in one place: the nearest-neighbour query is a subquery with its own `ORDER BY distance LIMIT n`, and `RANK()` is applied outside it. With the window function next to `LIMIT` in the same query, Postgres can't stop after n rows, so it can't use the HNSW index to produce the ordered rows.

### 9h: three ways, same 14 questions, same 10,704 chunks (`eval_search`, k = 5, 3 timed runs per query)
`rag_eval` is 17.6% of the 60,704 indexed vectors. "db" times cover only the SQL (not the query embedding, ~210 ms p50 / 227 ms p95 from the Gemini API; Pinecone's baseline run measured 205 ms / 245 ms for the same call).

| mode | hit@5 | db p50 | db p95 | notes |
|---|---|---|---|---|
| Pinecone dense | 13/14 | 93 ms | 206 ms | baseline from 9a |
| Pinecone dense + BM25 (RRF) | 14/14 | 148 ms | 179 ms | baseline from 9a (the RAG project's own pipeline) |
| pgvector vector, **planner's default plan** | 13/14 | 50 ms | 111 ms | exact scan: `user_id` bitmap, then sort 10,704 rows by distance |
| pgvector vector, **HNSW forced** | 13/14 | **5.3 ms** | 8.4 ms | `enable_bitmapscan = off`, `ef_search = 100` |
| pgvector keyword only (OR query, `ts_rank_cd`) | 10/14 (71%) | 130 ms | 295–324 ms | misses e1, e5, t1, t2 |
| pgvector hybrid (RRF), 50 candidates per list | 13/14 | 191 ms default / 116 ms forced | 366 / 186 ms | |
| pgvector hybrid, 5 candidates per list | 14/14 | 86 ms (forced) | 156 ms | |

What I take from it:
- **Quality is the same as Pinecone's, within what 14 questions can show.** Dense retrieval gets 13/14 on both stores (e6 is missed by both). One question is 7 points, so differences of one question are noise. The hybrid result moved between 13/14 and 14/14 depending on `candidates` (5 vs 10 vs 50) and on exact vs HNSW vector results, which is also noise-sized. The honest summary is "hybrid 13–14/14 vs Pinecone dense+BM25 14/14".
- **Keyword search alone is the weakest (71%)**: it misses e1, e5, t1 and t2, all of which vector search finds. Vector search misses only e6, which keyword search finds, and hybrid recovers e6. So the two lists really are complementary, but with 50 candidates the noisier keyword list also pushed t1 out of the top 5 once. Natural-language questions are what embeddings are good at; keyword search adds value for exact names and terms, which this question set has few of.
- **The vector part is fast** (5 ms with the index) but the **keyword part isn't** (~130 ms): the GIN index covers all 5M rows and all users and the `user_id` filter is applied afterwards, the same problem as Q5b in 6c. The hybrid latency is mostly the keyword half.
- **End to end** (p50, query embedding + database): pgvector vector ≈ 210 + 5 = ~215 ms; pgvector hybrid ≈ 210 + 86–190 = ~300–400 ms; Pinecone dense ≈ 205 + 93 = ~300 ms; Pinecone dense+BM25 ≈ 205 + 148 = ~350 ms. The embedding call is the biggest single cost on every path, and it's identical for all of them.
- **Planner surprise:** for `rag_eval` (10,704 of 5M rows) Postgres estimates ~171 matching rows (it assumes the 1.2% of rows that have embeddings are spread evenly over users), so it picks the exact scan and ignores the HNSW index. Exact scan costs 50 ms warm and 141–805 ms cold. For a tenant this size the exact scan is acceptable, but it grows linearly with the tenant. Fixes: extended statistics on `(user_id, embedding IS NOT NULL)`, or a partial index `WHERE embedding IS NOT NULL` on the btree so the estimate is right. I haven't tried either.

### 9i: tenant filtering with HNSW
Setup: `rag_eval` owns 10,704 of the 60,704 indexed vectors (17.6%); HNSW forced (`--force-index`, otherwise the planner uses the exact scan and none of this happens); k = 5; hybrid with 10 candidates.

**Eval questions (on-topic: nearest neighbours are mostly this tenant's own chunks):**

| ef_search | iterative scan | vector hit@5 | vector avg returned | vector db p50 | hybrid hit@5 |
|---|---|---|---|---|---|
| 10 | off | 11/14 (79%) | **4.3** | 3.6 ms | 13/14 |
| 10 | relaxed_order | 13/14 (93%) | 5.0 | 3.6 ms | 13/14 |
| 40 | off | 12/14 (86%) | 4.6 | 3.9 ms | 13/14 |
| 200 | off | 13/14 (93%) | 5.0 | 6.0 ms | 13/14 |

**Off-topic queries** ("your invoice payment is overdue", "lunch with the client on Friday", ... asked as `rag_eval`, so the nearest vectors in the index belong to other tenants; 6 queries):

| ef_search | iterative scan | avg results returned (k = 5) | db p50 |
|---|---|---|---|
| 10 | off | **0.0** | 3.7 ms |
| 40 | off | **0.0** | 4.5 ms |
| 100 | off | 0.8 | 6.5 ms |
| 200 | off | 1.8 | 9.6 ms |
| 10 | relaxed_order | 5.0 | 27.0 ms |
| 40 | relaxed_order | 5.0 | 24.9 ms |

What this shows:
- HNSW finds the ~`ef_search` nearest vectors in the **whole index** first, then Postgres applies `user_id`. With 17.6% of the index and ef_search = 10, you expect ~2 survivors; for a query whose neighbours belong to other tenants you get **none, with no error**. The default `ef_search = 40` also returned 0 results on those queries, and even 200 only returned 1.8 of 5.
- On-topic queries hide the problem (4.3 of 5 returned, hit rate 79–93%) because their neighbours are the tenant's own chunks. A tenant whose queries drift off its own data gets empty results. That's the dangerous failure: it depends on the query, so it won't show up in an eval set built from the tenant's own questions.
- **Iterative scan (`relaxed_order`) fixed it**: 5.0 results every time, at any `ef_search`, because the scan keeps walking the graph until enough rows pass the filter. It cost latency only when needed: 3.7 ms → ~25 ms for the off-topic queries, nothing for the on-topic ones (3.6 ms both ways).
- Raising `ef_search` also helps but is a blunt tool: results climb slowly (0.8, 1.8 of 5) while latency grows, and it has no guarantee.
- Hybrid hides part of it: in the eval runs it always returned 5.0 results even when the vector list was short, because the keyword list filled the gap. I did not run hybrid on the off-topic queries. If the vector list is empty, the "semantic" half of the hybrid is silently missing.
- Other fixes, which I did not try: a **partial HNSW index per tenant** (`WHERE user_id = X`; works for a few big tenants, not for 200 small ones); **partitioning** the table by tenant so each partition has its own index; an **exact scan for small tenants** (what the planner chose here by default: 50 ms for 10k rows, linear in tenant size). Pinecone's equivalent is namespaces or metadata filters.
- The planner's default plan for this tenant is the exact scan, so the default behaviour of the code in `memories/search.py` never hit the problem on `rag_eval`. It would for a much bigger table or once statistics change, so `iterative_scan = relaxed_order` is the safe setting to ship with.
