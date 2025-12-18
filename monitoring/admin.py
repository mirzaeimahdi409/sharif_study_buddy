from django.contrib import admin
from .models import MonitoredChannel, IngestedTelegramMessage

@admin.register(MonitoredChannel)
class MonitoredChannelAdmin(admin.ModelAdmin):
    """Admin interface for managing MonitoredChannel models."""
    list_display = ('username', 'added_at')
    search_fields = ('username',)
    list_filter = ('added_at',)
    ordering = ('-added_at',)


@admin.register(IngestedTelegramMessage)
class IngestedTelegramMessageAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "channel_username",
        "message_id",
        "ingested",
        "attempts",
        "ingested_at",
        "last_attempt_at",
    )
    search_fields = ("external_id", "channel_username")
    list_filter = ("ingested", "channel_username")
    ordering = ("-created_at",)
