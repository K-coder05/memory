import random
import time
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from faker import Faker

from memories.models import Memory, Source


class Command(BaseCommand):
    help = "Load fake users, sources and memories for local development."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=10)
        parser.add_argument("--memories", type=int, default=100_000)
        parser.add_argument("--batch-size", type=int, default=5_000)
        parser.add_argument("--seed", type=int, default=42, help="for reproducible data")

    def handle(self, *args, **opts):
        Faker.seed(opts["seed"])
        fake = Faker()
        rng = random.Random(opts["seed"])
        User = get_user_model()

        # 1. Users and their sources (get_or_create makes re-running safe)
        sources = []
        for i in range(opts["users"]):
            user, created = User.objects.get_or_create(username=f"user{i}")
            if created:
                user.set_password("password")
                user.save()
            for kind in Source.Kind.values:
                source, _ = Source.objects.get_or_create(user=user, kind=kind, name=f"{kind}-main")
                sources.append(source)

        # 2. Memories, in batches
        total, batch_size = opts["memories"], opts["batch_size"]
        done = 0
        start = time.perf_counter()
        while done < total:
            n = min(batch_size, total - done)
            batch = []
            for _ in range(n):
                source = rng.choice(sources)
                batch.append(
                    Memory(
                        user_id=source.user_id,  # keep user consistent with source
                        source=source,
                        content=fake.paragraph(nb_sentences=rng.randint(2, 6)),
                        occurred_at=fake.date_time_between(
                            start_date="-3y", end_date="now", tzinfo=dt_timezone.utc
                        ),
                        metadata=self.fake_metadata(fake, rng, source.kind),
                    )
                )
            Memory.objects.bulk_create(batch, batch_size=batch_size)
            done += n
            self.stdout.write(f"  inserted {done:,}/{total:,}")

        elapsed = time.perf_counter() - start
        self.stdout.write(self.style.SUCCESS(
            f"Done: {total:,} memories in {elapsed:.1f}s ({total / elapsed:,.0f} rows/s)"
        ))

    @staticmethod
    def fake_metadata(fake, rng, kind):
        if kind == Source.Kind.GMAIL:
            return {
                "from": fake.email(),
                "subject": fake.sentence(nb_words=6),
                "labels": rng.sample(["inbox", "work", "travel", "receipts", "family"], k=2),
            }
        if kind == Source.Kind.SLACK:
            return {"channel": f"#{fake.word()}", "author": fake.user_name()}
        return {"meeting_title": fake.catch_phrase(), "duration_min": rng.choice([15, 30, 45, 60])}