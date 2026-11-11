from django.contrib import admin

# Register your models here.
from .models import Memory, Source

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "kind", "name")
	list_filter = ("kind",)

@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
	list_display = ("id", "user", "source", "occurred_at")
	list_filter = ("source__kind",)
	list_select_related = ("user", "source")
	raw_id_fields = ("user", "source")