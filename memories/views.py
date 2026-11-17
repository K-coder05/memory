from django.contrib.postgres.search import SearchQuery
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError

from .models import Memory
from .serializers import MemorySerializer
from .pagination import MemoryCursorPagination


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

def parse_when(value, param):
    try:
        dt = parse_datetime(value)
    except ValueError:
        dt = None
    if dt is None:
        raise ValidationError({param: "Use ISO 8601, e.g. 2024-01-31 or 2024-01-31T09:00:00Z"})
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
	pagination_class = MemoryCursorPagination
	
	def get_queryset(self):
		qs = (
			Memory.objects.filter(user=self.request.user)
			.select_related("source")
			.defer("search_vector", "embedding")
		)
		if self.action == "list":
			params = self.request.query_params
			if source := params.get("source"):
				qs = qs.filter(source__kind=source)
			if since := params.get("since"):
				qs = qs.filter(occurred_at__gte=parse_when(since, "since"))
			if until := params.get("until"):
				qs = qs.filter(occurred_at__lt=parse_when(until, "until"))
			if contains := params.get("contains"):
				qs = qs.filter(content__icontains=contains)
			if sender := params.get("sender"):
				qs = qs.filter(metadata__contains={"from": sender})
			if q:= params.get("q"):
				qs = qs.filter(search_vector=SearchQuery(q, search_type="websearch", config="english"))
		return qs

	def perform_create(self, serializer):
		serializer.save(user=self.request.user)