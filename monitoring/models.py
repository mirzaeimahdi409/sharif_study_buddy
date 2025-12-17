from django.db import models

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
