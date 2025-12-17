from django.contrib import admin
from .models import MonitoredChannel

@admin.register(MonitoredChannel)
class MonitoredChannelAdmin(admin.ModelAdmin):
    """Admin interface for managing MonitoredChannel models."""
    list_display = ('username', 'added_at')
    search_fields = ('username',)
    list_filter = ('added_at',)
    ordering = ('-added_at',)
