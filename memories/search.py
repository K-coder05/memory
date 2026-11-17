"""Retrieval over one user's memories: vector, keyword and hybrid (RRF)."""
from django.db import connection, transaction

RRF_K = 60

# The nearest-neighbour query is a subquery with its own ORDER BY ... LIMIT, so Postgres
# can answer it straight from the HNSW index. The rank is computed outside it, on at most
# %(n)s rows.
VECTOR_SQL = """
    SELECT id, RANK() OVER (ORDER BY dist) AS rnk
      FROM (
        SELECT id, embedding <=> %(qvec)s::halfvec AS dist
          FROM memories_memory
         WHERE user_id = %(user_id)s AND embedding IS NOT NULL
         ORDER BY embedding <=> %(qvec)s::halfvec
         LIMIT %(n)s
      ) AS nearest
"""

KEYWORD_SQL = """
    SELECT id, RANK() OVER (ORDER BY score DESC) AS rnk
      FROM (
        SELECT id, ts_rank_cd(search_vector, q.query) AS score
          FROM memories_memory
         CROSS JOIN (
             SELECT replace(plainto_tsquery('english', %(text)s)::text, ' & ', ' | ')::tsquery AS query
         ) AS q
         WHERE user_id = %(user_id)s AND search_vector @@ q.query
         ORDER BY score DESC
         LIMIT %(n)s
      ) AS best
"""

HYBRID_SQL = f"""
    WITH semantic AS ({VECTOR_SQL}),
         keyword  AS ({KEYWORD_SQL})
    SELECT COALESCE(semantic.id, keyword.id) AS id,
           COALESCE(1.0 / (%(rrf_k)s + semantic.rnk), 0.0)
         + COALESCE(1.0 / (%(rrf_k)s + keyword.rnk), 0.0) AS score
      FROM semantic
      FULL OUTER JOIN keyword ON semantic.id = keyword.id
     ORDER BY score DESC, id
     LIMIT %(k)s
"""


def _vec(values):
    """Python list -> pgvector text literal '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.7f}" for x in values) + "]"


def _ids(sql, params, ef_search, iterative_scan, force_index=False):
    # set_config(..., true) lasts for this transaction only, so it can't leak into other
    # queries on the same connection.
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SELECT set_config('hnsw.ef_search', %s, true)", [str(ef_search)])
        cur.execute("SELECT set_config('hnsw.iterative_scan', %s, true)", [iterative_scan])
        if force_index:
            # Experiment switch. For a user with ~10k of 5M rows, the planner estimates far
            # fewer matching rows than there are, so it prefers "bitmap scan on user_id,
            # then sort exactly" over the HNSW index. Switching bitmap scans off makes the
            # HNSW index the cheapest remaining way to get rows in distance order.
            cur.execute("SELECT set_config('enable_bitmapscan', 'off', true)")
        cur.execute(sql, params)
        return [row[0] for row in cur.fetchall()]


def vector_search(user_id, qvec, k=5, ef_search=100, iterative_scan="off", force_index=False):
    return _ids(VECTOR_SQL + " ORDER BY rnk, id",
                {"user_id": user_id, "qvec": _vec(qvec), "n": k},
                ef_search, iterative_scan, force_index)


def keyword_search(user_id, text, k=5):
    return _ids(KEYWORD_SQL + " ORDER BY rnk, id",
                {"user_id": user_id, "text": text, "n": k}, 40, "off")


def hybrid_search(user_id, text, qvec, k=5, candidates=50, ef_search=100,
                  iterative_scan="off", force_index=False):
    params = {"user_id": user_id, "text": text, "qvec": _vec(qvec),
              "n": candidates, "k": k, "rrf_k": RRF_K}
    return _ids(HYBRID_SQL, params, ef_search, iterative_scan, force_index)
