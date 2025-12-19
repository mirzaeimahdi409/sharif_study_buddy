from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Import signal handlers
        from . import signals  # noqa: F401
        
        # Initialize LangSmith tracing if configured
        try:
            from core.services.langsmith_client import configure_langsmith_environment
            configure_langsmith_environment()
        except Exception:
            # LangSmith initialization is optional, fail silently if not configured
            pass

