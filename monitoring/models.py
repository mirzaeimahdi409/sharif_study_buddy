from django.db import models
from django.utils import timezone


class MonitoredChannel(models.Model):
    """Represents a Telegram channel to be monitored for new messages."""
    username = models.CharField(
        max_length=100,
        unique=True,
        help_text="The username of the Telegram channel (e.g., 'durov_channel')."
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The date and time when the channel was added."
    )

    def __str__(self):
        return f"@{self.username}"

    class Meta:
        verbose_name = "Monitored Channel"
        verbose_name_plural = "Monitored Channels"
        ordering = ['-added_at']


class IngestedTelegramMessage(models.Model):
    """
    Tracks Telegram messages that were sent to the RAG ingest endpoint to avoid duplicates.

    We store both a unique external_id (channel + message_id) and an optional content_hash
    to support content-based deduplication if desired.
    """

    external_id = models.CharField(max_length=255, unique=True, db_index=True)
    channel_username = models.CharField(max_length=100, db_index=True)
    message_id = models.BigIntegerField(db_index=True)
    source_url = models.URLField(blank=True, null=True)
    rag_document_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Document ID in RAG knowledge base (for deletion/reprocess)",
    )
    content_hash = models.CharField(
        max_length=64, blank=True, null=True, db_index=True)

    ingested = models.BooleanField(default=False, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(blank=True, null=True)
    ingested_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["channel_username", "message_id"]),
            models.Index(fields=["content_hash", "ingested"]),
        ]

    def __str__(self) -> str:
        return self.external_id
