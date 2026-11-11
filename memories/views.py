from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError

from .models import Memory
from .serializers import MemorySerializer


def parse_since(value):
	try:
		dt = parse_datetime(value)
	except ValueError:
		dt = None
	if dt is None:
		raise ValidationError({"since": "Use ISO 8601, e.g. 2024-01-31 or 2024-01-31T09:00:00Z"})
	if timezone.is_naive(dt):
		dt = timezone.make_aware(dt)
	return dt


class MemoryViewSet(
	mixins.CreateModelMixin,
	mixins.RetrieveModelMixin,
	mixins.ListModelMixin,
	viewsets.GenericViewSet,
):
	serializer_class = MemorySerializer

	def get_queryset(self):
		qs = Memory.objects.filter(user=self.request.user)
		if self.action == "list":
			params = self.request.query_params
			if source := params.get("source"):
				qs = qs.filter(source__kind=source)
			if since := params.get("since"):
				qs = qs.filter(occurred_at__gte=parse_since(since))
			if q:= params.get("q"):
				qs = qs.filter(content__icontains=q)
		return qs

	def perform_create(self, serializer):
		serializer.save(user=self.request.user)