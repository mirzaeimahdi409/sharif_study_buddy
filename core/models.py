from django.conf import settings
from django.db import models
from django.utils import timezone
from typing import Optional


class UserProfile(models.Model):
    """User profile model for Telegram users."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    telegram_id = models.CharField(max_length=64, unique=True, db_index=True)
    display_name = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        """Return string representation of the user profile."""
        return self.display_name or f"User {self.user_id}"

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        ordering = ["-created_at"]


class ChatSession(models.Model):
    """Chat session model for user conversations."""

    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name="sessions"
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        """Return string representation of the chat session."""
        return f"Session {self.id} for {self.user_profile}"

    class Meta:
        verbose_name = "Chat Session"
        verbose_name_plural = "Chat Sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user_profile", "is_active", "-created_at"]),
        ]


class ChatMessage(models.Model):
    """Chat message model for storing conversation messages."""

    ROLE_CHOICES = (
        ("system", "System"),
        ("user", "User"),
        ("assistant", "Assistant"),
    )

    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, db_index=True)
    content = models.TextField()
    tokens = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self) -> str:
        """Return string representation of the chat message."""
        return f"{self.role}: {self.content[:40]}..."

    class Meta:
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]


class KnowledgeDocument(models.Model):
    """Knowledge document model for storing documents in the knowledge base."""

    title = models.CharField(max_length=255, help_text="Document title")
    content = models.TextField(help_text="Document content")
    source_url = models.URLField(
        blank=True, null=True, help_text="Source URL of the document"
    )
    metadata = models.JSONField(
        default=dict, blank=True, help_text="Additional metadata as JSON"
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="External document ID from RAG service",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_in_rag = models.BooleanField(
        default=False, db_index=True, help_text="Whether document is indexed in RAG"
    )

    def __str__(self) -> str:
        """Return string representation of the knowledge document."""
        return self.title

    @property
    def content_length(self) -> int:
        """Return the length of content for display purposes."""
        return len(self.content)

    class Meta:
        verbose_name = "Knowledge Document"
        verbose_name_plural = "Knowledge Documents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["indexed_in_rag", "created_at"]),
        ]
