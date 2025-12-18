from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitoring"

    def ready(self) -> None:
        # Import signal handlers
        from . import signals  # noqa: F401
        return super().ready()
