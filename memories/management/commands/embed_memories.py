import time

from django.core.management.base import BaseCommand
from django.db import connection

from memories.embeddings import embed_passages
from memories.models import Memory, Source


class Command(BaseCommand):
    help = "Embed existing memories that have no embedding yet (skips the eval corpus)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50_000)
        parser.add_argument("--batch-size", type=int, default=100)  # the API's maximum
        parser.add_argument("--delay", type=float, default=1.0, help="seconds between API calls")

    def handle(self, *args, **opts):
        todo = (Memory.objects.filter(embedding__isnull=True)
                .exclude(source__kind=Source.Kind.DOCS)
                .order_by("id")
                .only("id", "content"))
        done, limit = 0, opts["limit"]
        while done < limit:
            batch = list(todo[: min(opts["batch_size"], limit - done)])
            if not batch:
                break
            vectors = embed_passages(m.content for m in batch)
            # One UPDATE per row, sent in a single round trip. (bulk_update would build a huge
            # CASE WHEN statement holding every vector, ~3,000 numbers per row.)
            with connection.cursor() as cur:
                cur.executemany(
                    "UPDATE memories_memory SET embedding = %s::halfvec WHERE id = %s",
                    [("[" + ",".join(f"{x:.7f}" for x in vec) + "]", m.id)
                     for m, vec in zip(batch, vectors)],
                )
            done += len(batch)
            if done % 1000 == 0 or done >= limit:
                self.stdout.write(f"  embedded {done:,}/{limit:,}")
            time.sleep(opts["delay"])
        self.stdout.write(self.style.SUCCESS(f"Done: embedded {done:,} memories"))
