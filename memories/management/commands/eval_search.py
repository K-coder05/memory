import json
import statistics
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from memories import search
from memories.embeddings import embed_query
from memories.models import Memory


def ms_since(t0):
    return (time.perf_counter() - t0) * 1000


def p95(values):
    return statistics.quantiles(values, n=20)[18] if len(values) >= 2 else values[0]


class Command(BaseCommand):
    help = ("Top-k hit rate and latency for vector, keyword and hybrid search on an eval set. "
            "A hit is a returned chunk whose source URL is one of the question's relevant sources.")

    def add_arguments(self, parser):
        parser.add_argument("--user", default="rag_eval")
        parser.add_argument("--queries", default="eval/data/queries.jsonl")
        parser.add_argument("-k", type=int, default=5)
        parser.add_argument("--ef-search", type=int, default=100)
        parser.add_argument("--iterative-scan", default="off",
                            choices=["off", "strict_order", "relaxed_order"])
        parser.add_argument("--candidates", type=int, default=50,
                            help="how many results each list (vector, keyword) feeds into the RRF merge")
        parser.add_argument("--force-index", action="store_true",
                            help="disable bitmap scans so the planner uses the HNSW index")
        parser.add_argument("--repeats", type=int, default=3, help="timed runs per query (all pooled)")

    def handle(self, *args, **o):
        user = get_user_model().objects.get(username=o["user"])
        source_of = dict(Memory.objects.filter(user=user).values_list("id", "metadata__source_url"))
        with open(o["queries"], encoding="utf-8") as f:
            evals = [json.loads(line) for line in f if line.strip()]

        k, hnsw = o["k"], {"ef_search": o["ef_search"], "iterative_scan": o["iterative_scan"],
                "force_index": o["force_index"]}
        modes = {
            "vector": lambda text, vec: search.vector_search(user.id, vec, k, **hnsw),
            "keyword": lambda text, vec: search.keyword_search(user.id, text, k),
            "hybrid": lambda text, vec: search.hybrid_search(user.id, text, vec, k, candidates=o["candidates"], **hnsw),
        }

        warm = embed_query(evals[0]["query"])  # warm-up: client setup + caches
        for fn in modes.values():
            fn(evals[0]["query"], warm)

        hits = {m: 0 for m in modes}
        latency = {m: [] for m in modes}
        returned = {m: [] for m in modes}
        embed_ms = []
        for item in evals:
            t0 = time.perf_counter()
            vec = embed_query(item["query"])
            embed_ms.append(ms_since(t0))
            relevant = set(item["relevant_sources"])
            for name, fn in modes.items():
                for _ in range(o["repeats"]):
                    t0 = time.perf_counter()
                    ids = fn(item["query"], vec)
                    latency[name].append(ms_since(t0))
                returned[name].append(len(ids))
                if relevant & {source_of[i] for i in ids}:
                    hits[name] += 1

        n = len(evals)
        self.stdout.write(f"{n} queries, k={k}, ef_search={o['ef_search']}, "
                          f"iterative_scan={o['iterative_scan']}, candidates={o['candidates']}, force_index={o['force_index']}, "
                          f"{o['repeats']} timed runs per query")
        self.stdout.write(f"query embedding: p50 {statistics.median(embed_ms):.0f} ms, "
                          f"p95 {p95(embed_ms):.0f} ms")
        self.stdout.write(f"{'mode':<8} {'hit@k':>10} {'db p50':>8} {'db p95':>8} {'avg returned':>13}")
        for name in modes:
            self.stdout.write(
                f"{name:<8} {hits[name]:>3}/{n} {hits[name] / n:>4.0%} "
                f"{statistics.median(latency[name]):>6.1f}ms {p95(latency[name]):>6.1f}ms "
                f"{statistics.mean(returned[name]):>13.1f}"
            )
