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
| Q1 latest 20 | Parallel Bitmap Heap Scan on user_id index → Hash Join source → top-N sort; reads all 356k of the user's rows to return 20, 158,783 buffers read, **573 ms** | | |
| Q2 date range | Same plan + filter on occurred_at (removes 115k rows/worker), 158,785 buffers read, **505 ms** | | |
| Q3 JSONB sender | Same plan + filter `metadata @>` (6 rows out of 356k), 158,789 buffers read, **586 ms** | | |
| Q4a icontains common word | Same plan + filter `upper(content) LIKE` (~6.9k matches), 158,791 buffers read, **617 ms** | | |
| Q4b icontains no match | Same plan + filter, 0 rows out, 158,790 buffers read, **585 ms** | | |

Queries with the highest `total_ms`:
 calls | total_ms | mean_ms | rows |                                                     query
-------+----------+---------+------+----------------------------------------------------------------------------------------------------------------
     2 |     1237 |   618.7 |    0 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem
     2 |     1235 |   617.4 |   20 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem
     1 |      618 |   618.0 |    0 | EXPLAIN (ANALYZE, BUFFERS) SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name FROM memories_mem