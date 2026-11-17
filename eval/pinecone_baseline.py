"""Top-k hit rate and latency of the RAG project's Pinecone retrieval, on eval/data/queries.jsonl.

Run it with the RAG project's interpreter (needs pinecone, langchain-google-genai, rank-bm25):

    <rag>\\.venv\\Scripts\\python.exe eval\\pinecone_baseline.py --env <rag>\\.env

Two modes, both measured as the *retrieval call only* (query embedding is timed separately):
    dense        Pinecone top-k by cosine similarity
    dense+bm25   what the RAG project does: dense top-k and BM25 top-k fused with RRF (k = 60)
A hit = at least one returned chunk comes from one of the question's `relevant_sources` URLs.
"""
import argparse
import json
import os
import statistics
import time

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pinecone import Pinecone
from rank_bm25 import BM25Okapi

RRF_K = 60


def ms_since(t0):
    return (time.perf_counter() - t0) * 1000


def p95(values):
    return statistics.quantiles(values, n=20)[18] if len(values) >= 2 else values[0]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--data", default="eval/data")
    ap.add_argument("--index", default="startup-library")
    ap.add_argument("--namespace", default="startup-library")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=3, help="timed runs per query (all are pooled)")
    args = ap.parse_args()

    load_dotenv(args.env)
    corpus = read_jsonl(f"{args.data}/corpus.jsonl")
    queries = read_jsonl(f"{args.data}/queries.jsonl")
    source_of = {c["id"]: c["source_url"] for c in corpus}
    ranker = BM25Okapi([c["text"].lower().split() for c in corpus], k1=1.5, b=0.65, epsilon=0.25)  # as main.py
    ids = [c["id"] for c in corpus]

    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(args.index)
    model = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", task_type="RETRIEVAL_QUERY")
    k = args.k

    def dense(vec):
        res = index.query(vector=vec, top_k=k, namespace=args.namespace)
        return [m["id"] for m in res["matches"]]

    def dense_bm25(vec, text):
        dense_ids = dense(vec)
        scores = ranker.get_scores(text.lower().split())
        bm25_ids = [ids[i] for i in sorted(range(len(ids)), key=scores.__getitem__, reverse=True)[:k]]
        fused = {}
        for rank, i in enumerate(dense_ids, 1):
            fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank)
        for rank, i in enumerate(bm25_ids, 1):
            fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank)
        return sorted(fused, key=fused.get, reverse=True)[:k]

    modes = {"dense": lambda vec, text: dense(vec), "dense+bm25": dense_bm25}

    warm = model.embed_query(queries[0]["query"])  # warm-up: connections, lazy imports
    for fn in modes.values():
        fn(warm, queries[0]["query"])

    hits = {m: 0 for m in modes}
    latency = {m: [] for m in modes}
    embed_ms = []
    for q in queries:
        t0 = time.perf_counter()
        vec = model.embed_query(q["query"])
        embed_ms.append(ms_since(t0))
        relevant = set(q["relevant_sources"])
        for name, fn in modes.items():
            for rep in range(args.repeats):
                t0 = time.perf_counter()
                got = fn(vec, q["query"])
                latency[name].append(ms_since(t0))
            if relevant & {source_of[i] for i in got}:
                hits[name] += 1

    n = len(queries)
    print(f"Pinecone {args.index}/{args.namespace}: {len(corpus):,} chunks, {n} queries, k={k}, "
          f"{args.repeats} timed runs per query")
    print(f"query embedding (Gemini API): p50 {statistics.median(embed_ms):.0f} ms, p95 {p95(embed_ms):.0f} ms")
    print(f"{'mode':<11} {'hit@k':>7} {'p50':>8} {'p95':>8}")
    for name in modes:
        print(f"{name:<11} {hits[name]:>3}/{n} {hits[name] / n:>4.0%} {statistics.median(latency[name]):>6.0f}ms "
              f"{p95(latency[name]):>6.0f}ms")


if __name__ == "__main__":
    main()
