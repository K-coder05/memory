from rest_framework.pagination import CursorPagination


class MemoryCursorPagination(CursorPagination):
    page_size = 20
    ordering = ("-occurred_at", "-id")  # must match memory_user_recent_idx