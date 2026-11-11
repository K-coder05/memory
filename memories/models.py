from django.conf import settings
from django.db import models

# Create your models here.
class Source(models.Model):
	class Kind(models.TextChoices):
		GMAIL = "gmail", "Gmail",
		SLACK = "slack", "Slack",
		ZOOM = "zoom", "Zoom"

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
		settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memories"
	)
	source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="memories")
	content = models.TextField()
	occurred_at = models.DateTimeField()
	metadata = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-occurred_at", "-id"]
		verbose_name_plural = "memories"

	def __str__(self):
		return f"Memory {self.pk} ({self.occurred_at:%Y-%m-%d})"