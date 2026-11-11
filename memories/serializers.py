from rest_framework import serializers

from .models import Memory, Source

class SourceSerializer(serializers.ModelSerializer):
	class Meta:
		model = Source
		fields = ["id", "kind", "name"]

class MemorySerializer(serializers.ModelSerializer):
	source = SourceSerializer(read_only=True)
	source_id = serializers.PrimaryKeyRelatedField(
		source="source", queryset=Source.objects.none(), write_only=True
	)

	class Meta:
		model = Memory
		fields = ["id", "source", "source_id", "content", "occurred_at", "metadata", "created_at"]
		read_only_fields = ["id", "created_at"]

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		request = self.context.get("request")
		if request is not None and request.user.is_authenticated:
			self.fields["source_id"].queryset = Source.objects.filter(user=request.user)