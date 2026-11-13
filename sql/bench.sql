-- Baseline benchmark queries. Run with:
--   Get-Content sql\bench.sql | docker compose exec -T db psql -U recall -d recall
\set ON_ERROR_STOP on
\pset pager off

SELECT id AS uid FROM auth_user WHERE username = 'user0' \gset
SELECT metadata->>'from' AS email FROM memories_memory
 WHERE user_id = :uid AND metadata ? 'from' ORDER BY id LIMIT 1 \gset
SELECT w AS word
  FROM (SELECT content FROM memories_memory WHERE user_id = :uid ORDER BY id LIMIT 1) m,
       regexp_split_to_table(lower(m.content), '[^a-z]+') AS w
 WHERE length(w) >= 6 LIMIT 1 \gset
\set missing 'zqxjvk'
\echo user=:uid email=:email word=:word missing=:missing

\echo
\echo ===== Q1: latest 20 for a user
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id
 WHERE m.user_id = :uid
 ORDER BY m.occurred_at DESC, m.id DESC LIMIT 20;

\echo ===== Q2: date range (January 2026)
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id
 WHERE m.user_id = :uid
   AND m.occurred_at >= '2026-01-01' AND m.occurred_at < '2026-02-01'
 ORDER BY m.occurred_at DESC, m.id DESC LIMIT 20;

\echo ===== Q3: JSONB filter (emails from one sender)
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id
 WHERE m.user_id = :uid AND m.metadata @> jsonb_build_object('from', :'email')
 ORDER BY m.occurred_at DESC, m.id DESC LIMIT 20;

\echo ===== Q4a: keyword search, common word (icontains)
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id
 WHERE m.user_id = :uid AND UPPER(m.content) LIKE UPPER('%' || :'word' || '%')
 ORDER BY m.occurred_at DESC, m.id DESC LIMIT 20;

\echo ===== Q4b: keyword search, word that matches nothing (icontains)
EXPLAIN (ANALYZE, BUFFERS)
SELECT m.id, m.content, m.occurred_at, m.metadata, s.kind, s.name
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id
 WHERE m.user_id = :uid AND UPPER(m.content) LIKE UPPER('%' || :'missing' || '%')
 ORDER BY m.occurred_at DESC, m.id DESC LIMIT 20;