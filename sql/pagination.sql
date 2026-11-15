\set ON_ERROR_STOP on
\pset pager off
SELECT id AS uid FROM auth_user WHERE username = 'user0' \gset

\echo ===== OFFSET 100000
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, occurred_at FROM memories_memory
 WHERE user_id = :uid
 ORDER BY occurred_at DESC, id DESC
OFFSET 100000 LIMIT 20;

-- The position where the OFFSET page starts, i.e. the last row of the previous page:
SELECT occurred_at AS cur_ts, id AS cur_id FROM memories_memory
 WHERE user_id = :uid ORDER BY occurred_at DESC, id DESC
OFFSET 99999 LIMIT 1 \gset

\echo ===== KEYSET after (:cur_ts, :cur_id)
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, occurred_at FROM memories_memory
 WHERE user_id = :uid AND (occurred_at, id) < (:'cur_ts', :cur_id)
 ORDER BY occurred_at DESC, id DESC
 LIMIT 20;