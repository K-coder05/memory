-- Grow memories_memory to :target_total rows by copying existing rows
-- onto random users. Run with:
--   Get-Content sql\expand.sql | docker compose exec -T db psql -U recall -d recall

\set ON_ERROR_STOP on
\set target_total 5000000
\timing on

CREATE TEMP TABLE tpl AS
  SELECT row_number() OVER (ORDER BY m.id) AS n, m.content, m.metadata, s.kind
  FROM memories_memory m JOIN memories_source s ON s.id = m.source_id;

CREATE TEMP TABLE usr AS
  SELECT row_number() OVER (ORDER BY id) AS n, id
  FROM auth_user WHERE username ~ '^user[0-9]+$';

ANALYZE tpl;
ANALYZE usr;

SELECT count(*) AS ntpl FROM tpl \gset
SELECT count(*) AS nusr FROM usr \gset
SELECT :target_total - count(*) AS to_add FROM memories_memory \gset
\echo Adding :to_add rows from :ntpl templates across :nusr users...

INSERT INTO memories_memory (user_id, source_id, content, occurred_at, metadata, created_at)
SELECT s.user_id, s.id, t.content, g.occurred_at, t.metadata, now()
FROM (
  SELECT 1 + floor(random() * :ntpl)::int                 AS tn,
         1 + floor(power(random(), 2) * :nusr)::int       AS un,  -- skewed
         now() - random() * interval '3 years'            AS occurred_at
  FROM generate_series(1, :to_add)
) g
JOIN tpl t ON t.n = g.tn
JOIN usr u ON u.n = g.un
JOIN memories_source s
  ON s.user_id = u.id AND s.kind = t.kind AND s.name = t.kind || '-main';