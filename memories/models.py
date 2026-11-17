from django.conf import settings
from django.db import models
from django.db.models.functions import Upper
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector, SearchVectorField
from pgvector.django import HalfVectorField

# gemini-embedding-001 (the model the RAG project's Pinecone index uses) gives 3072 numbers.
# pgvector's plain `vector` type can only be indexed up to 2000 dimensions; `halfvec`
# (16-bit floats, half the storage) can be indexed up to 4000.
EMBEDDING_DIM = 3072

# Create your models here.
class Source(models.Model):
    class Kind(models.TextChoices):
        GMAIL = "gmail", "Gmail",
        SLACK = "slack", "Slack",
        ZOOM = "zoom", "Zoom"
        DOCS = "docs", "Documents"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sources"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "name"], name="uniq_source_per_user"
            )
        ]

    def __str__(self):
        return f"{self.kind}:{self.name}"

class Memory(models.Model):
	user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memories",
        db_index=False,  # covered by memory_user_recent_idx (user_id is its first column)
    )
	source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="memories")
	content = models.TextField()
	occurred_at = models.DateTimeField()
	metadata = models.JSONField(default=dict, blank=True)
	search_vector = models.GeneratedField(
		expression=SearchVector("content", config="english"),
		output_field=SearchVectorField(),
		db_persist=True,  # STORED: computed on write, kept on disk
	)
	embedding = HalfVectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-occurred_at", "-id"]
		verbose_name_plural = "memories"
		indexes = [
			models.Index(fields=["user", "-occurred_at", "-id"], name="memory_user_recent_idx"),
			GinIndex(fields=["metadata"], opclasses=["jsonb_path_ops"], name="memory_metadata_gin"),
			GinIndex(fields=["search_vector"], name="memory_search_gin"),
			GinIndex(OpClass(Upper("content"), name="gin_trgm_ops"), name="memory_content_trgm"),
		]

	def __str__(self):
		return f"Memory {self.pk} ({self.occurred_at:%Y-%m-%d})"