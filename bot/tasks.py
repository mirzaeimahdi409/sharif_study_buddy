from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from core.models import UserProfile
from bot.metrics import active_users_24h
import logging

logger = logging.getLogger(__name__)

@shared_task
def update_active_users_metric():
    """
    Calculates the number of active users in the last 24 hours
    and updates the corresponding Prometheus gauge.
    """
    try:
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
        # Count unique user profiles that have sent a message in the last 24 hours
        active_users_count = UserProfile.objects.filter(
            chat_sessions__messages__created_at__gte=twenty_four_hours_ago,
            chat_sessions__messages__role='user'  # Only count user messages
        ).distinct().count()

        active_users_24h.set(active_users_count)
        logger.info(f"Updated active_users_24h gauge to: {active_users_count}")
    except Exception as e:
        logger.error(f"Failed to update active users metric: {e}", exc_info=True)

