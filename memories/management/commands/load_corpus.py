import json

import numpy as np
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from memories.models import EMBEDDING_DIM, Memory, Source


class Command(BaseCommand):
    help = ("Load the exported RAG corpus (corpus.jsonl + vectors.npy, written by "
            "eval/export_pinecone.py) as one user's memories. The vectors are the ones "
            "already stored in Pinecone, so nothing is re-embedded.")

    def add_arguments(self, parser):
        parser.add_argument("--dir", default="eval/data")
        parser.add_argument("--user", default="rag_eval")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **opts):
        with open(f"{opts['dir']}/corpus.jsonl", encoding="utf-8") as f:
            docs = [json.loads(line) for line in f if line.strip()]
        vectors = np.load(f"{opts['dir']}/vectors.npy")
        if vectors.shape != (len(docs), EMBEDDING_DIM):
            raise SystemExit(f"vectors.npy is {vectors.shape}, expected ({len(docs)}, {EMBEDDING_DIM})")

        user, created = get_user_model().objects.get_or_create(username=opts["user"])
        if created:
            user.set_password("password")
            user.save()
        source, _ = Source.objects.get_or_create(user=user, kind=Source.Kind.DOCS, name="rag-corpus")

        deleted, _ = Memory.objects.filter(source=source).delete()  # makes re-runs safe
        if deleted:
            self.stdout.write(f"  removed {deleted:,} previously loaded rows")

        now, bs = timezone.now(), opts["batch_size"]
        for start in range(0, len(docs), bs):
            Memory.objects.bulk_create([
                Memory(user=user, source=source, content=d["text"], occurred_at=now,
                       metadata={"doc_id": d["id"], "source_url": d["source_url"]},
                       embedding=vec.tolist())
                for d, vec in zip(docs[start:start + bs], vectors[start:start + bs])
            ])
            self.stdout.write(f"  loaded {min(start + bs, len(docs)):,}/{len(docs):,}")
        self.stdout.write(self.style.SUCCESS(f"Done: {len(docs):,} documents for {user.username}"))
