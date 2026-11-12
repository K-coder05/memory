## Checkpoint 1
- Seed: 100,000 memories in 20.3 s (4925 rows/s) with bulk_create, batch 5,000
- N+1 on GET /memories: 22 queries → 2 queries per page after select_related("source")

# Entry 1.1
- docker compose exec db psql -U recall -c "SELECT count(*) FROM memories_memory;"
- 10002 memories
- docker compose exec db psql -U recall -c "SELECT metadata FROM memories_memory LIMIT 3;"
- metadata of dictionaries of fields and values