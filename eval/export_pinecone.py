"""Export the RAG project's Pinecone namespace so Postgres can be tested on identical data.

Run it with the RAG project's interpreter (it has `pinecone` installed), e.g.:

    <rag>\\.venv\\Scripts\\python.exe eval\\export_pinecone.py --rag-dir <rag> --env <rag>\\.env

Writes, into eval/data/ (git-ignored):
    corpus.jsonl   one chunk per line: {"id", "text", "source_url"}
    vectors.npy    float32 matrix (n_chunks x 3072), row i = vector of line i of corpus.jsonl
    queries.jsonl  eval questions: {"id", "query", "category", "relevant_sources": [urls]}
"""
import argparse
import csv
import json
import os
import pathlib

import numpy as np
from dotenv import load_dotenv
from pinecone import Pinecone


def norm(path):
    return str(path).replace("\\", "/").lstrip("./")


def url_by_file(rag_dir):
    """Map corpus file path -> public URL, using the scrapers' manifests."""
    mapping = {}
    with open(rag_dir / "corpus/pg_essays/_manifest.json", encoding="utf-8") as f:
        for item in json.load(f):
            mapping[norm(item["file"])] = item["url"]
    with open(rag_dir / "corpus/yc_library/_manifest.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            mapping[norm(row["file"])] = row["url"]
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rag-dir", required=True)
    ap.add_argument("--env", required=True, help="the RAG project's .env (PINECONE_API_KEY)")
    ap.add_argument("--index", default="startup-library")
    ap.add_argument("--namespace", default="startup-library")
    ap.add_argument("--out", default="eval/data")
    args = ap.parse_args()

    rag_dir, out = pathlib.Path(args.rag_dir), pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    load_dotenv(args.env)
    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(args.index)

    ids = sorted(v.id for page in index.list(namespace=args.namespace) for v in page.vectors)
    print(f"{len(ids):,} chunk ids in namespace {args.namespace!r}")

    urls = url_by_file(rag_dir)
    rows, vectors, unmapped = [], [], set()
    for start in range(0, len(ids), 100):
        fetched = index.fetch(ids=ids[start:start + 100], namespace=args.namespace).vectors
        for chunk_id in ids[start:start + 100]:
            rec = fetched[chunk_id]
            source = norm(rec.metadata["source"])
            if source not in urls:
                unmapped.add(source)
            rows.append({"id": chunk_id, "text": rec.metadata["text"], "source_url": urls.get(source, source)})
            vectors.append(rec.values)
        print(f"  fetched {min(start + 100, len(ids)):,}/{len(ids):,}")
    if unmapped:
        print(f"WARNING: {len(unmapped)} sources have no URL in the manifests, e.g. {sorted(unmapped)[:3]}")

    with open(out / "corpus.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    matrix = np.array(vectors, dtype=np.float32)
    np.save(out / "vectors.npy", matrix)

    with open(rag_dir / "eval_set.json", encoding="utf-8") as f:
        items = json.load(f)
    kept = [i for i in items if i["expected_sources"]]  # out-of-scope questions have nothing to hit
    with open(out / "queries.jsonl", "w", encoding="utf-8") as f:
        for i in kept:
            f.write(json.dumps({"id": i["id"], "query": i["query"], "category": i["category"],
                                "relevant_sources": i["expected_sources"]}, ensure_ascii=False) + "\n")
    print(f"corpus.jsonl: {len(rows):,} chunks, vectors.npy: {matrix.shape}, "
          f"queries.jsonl: {len(kept)} of {len(items)} questions (out-of-scope dropped)")


if __name__ == "__main__":
    main()
