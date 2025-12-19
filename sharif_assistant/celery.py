"""
Celery configuration for sharif_assistant project.
"""
import os
from celery import Celery
from core.logging_config import setup_logging

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sharif_assistant.settings")

# Setup logging for Celery
setup_logging(level="INFO", use_colors=False)

app = Celery("sharif_assistant")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
