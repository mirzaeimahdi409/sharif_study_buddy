"""Configuration management for the application."""
import os
import logging
from typing import Optional, Set
from django.conf import settings
from decouple import config

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when a required configuration is missing or invalid."""
    pass


class TelegramConfig:
    """Telegram bot configuration."""

    @staticmethod
    def get_bot_token() -> str:
        """Get Telegram bot token."""
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None) or config(
            "TELEGRAM_BOT_TOKEN", default=None
        )
        if not token:
            raise ConfigError(
                "TELEGRAM_BOT_TOKEN is required but not configured")
        return token

    @staticmethod
    def get_api_id() -> Optional[int]:
        """Get Telegram API ID."""
        return getattr(settings, "TELEGRAM_API_ID", None) or config(
            "TELEGRAM_API_ID", default=None, cast=int
        )

    @staticmethod
    def get_api_hash() -> Optional[str]:
        """Get Telegram API hash."""
        return getattr(settings, "TELEGRAM_API_HASH", None) or config(
            "TELEGRAM_API_HASH", default=None
        )

    @staticmethod
    def get_admin_ids() -> Set[str]:
        """Get admin Telegram IDs."""
        raw = getattr(settings, "ADMIN_TELEGRAM_IDS", None) or config(
            "ADMIN_TELEGRAM_IDS", default=""
        )
        return {s.strip() for s in raw.split(",") if s.strip()}

    @staticmethod
    def get_dedup_by_content() -> bool:
        """Get deduplication by content setting."""
        return getattr(settings, "TELEGRAM_DEDUP_BY_CONTENT", False) or config(
            "TELEGRAM_DEDUP_BY_CONTENT", default=False, cast=bool
        )

    @staticmethod
    def get_webhook_domain() -> Optional[str]:
        """Get webhook domain for production."""
        return getattr(settings, "WEBHOOK_DOMAIN", None) or config(
            "WEBHOOK_DOMAIN", default=None
        )

    @staticmethod
    def get_webhook_path() -> str:
        """Get webhook path prefix (optional). Defaults to '/webhook'."""
        path = getattr(settings, "WEBHOOK_PATH", None) or config(
            "WEBHOOK_PATH", default="/webhook"
        )
        # Ensure path starts with / and doesn't end with /
        if path and not path.startswith("/"):
            path = "/" + path
        if path.endswith("/"):
            path = path.rstrip("/")
        return path

    @staticmethod
    def get_webhook_secret_token() -> Optional[str]:
        """Get webhook secret token for security (optional but recommended)."""
        return getattr(settings, "WEBHOOK_SECRET_TOKEN", None) or config(
            "WEBHOOK_SECRET_TOKEN", default=None
        )


class RAGConfig:
    """RAG service configuration."""

    @staticmethod
    def get_api_url() -> str:
        """Get RAG API URL."""
        url = (
            getattr(settings, "RAG_API_URL", None)
            or config("RAG_API_URL", default="http://45.67.139.109:8033/api")
        )
        if not url:
            raise ConfigError("RAG_API_URL is required but not configured")
        return url.rstrip("/")

    @staticmethod
    def get_api_key() -> Optional[str]:
        """Get RAG API key."""
        return (
            getattr(settings, "RAG_API_KEY", None)
            or config("RAG_API_KEY", default=None)
        )

    @staticmethod
    def get_user_id() -> int:
        """Get RAG user ID."""
        return (
            getattr(settings, "RAG_USER_ID", None)
            or config("RAG_USER_ID", default=5, cast=int)
        )

    @staticmethod
    def get_microservice() -> str:
        """Get RAG microservice name."""
        return (
            getattr(settings, "RAG_MICROSERVICE", None)
            or config("RAG_MICROSERVICE", default="telegram_bot")
        )


class LLMConfig:
    """LLM service configuration."""

    @staticmethod
    def get_api_key() -> str:
        """Get OpenRouter API key."""
        key = (
            getattr(settings, "OPENROUTER_API_KEY", None)
            or config("OPENROUTER_API_KEY", default=None)
        )
        if not key:
            raise ConfigError(
                "OPENROUTER_API_KEY is required but not configured")
        return key

    @staticmethod
    def get_model() -> str:
        """Get OpenRouter model."""
        return config("OPENROUTER_MODEL", default="openrouter/auto")

    @staticmethod
    def get_temperature() -> float:
        """Get LLM temperature."""
        return float(config("LLM_TEMPERATURE", default="0.2"))


class ChatConfig:
    """Chat configuration."""

    @staticmethod
    def get_max_history() -> int:
        """Get maximum chat history length."""
        return int(config("CHAT_MAX_HISTORY", default="8"))

    @staticmethod
    def get_rag_top_k() -> int:
        """Get RAG top K results."""
        return int(config("RAG_TOP_K", default="5"))

    @staticmethod
    def is_feedback_enabled() -> bool:
        """Check if feedback loop is enabled."""
        return config("ENABLE_FEEDBACK_LOOP", default=True, cast=bool)


class LangSmithConfig:
    """LangSmith observability configuration."""

    @staticmethod
    def get_api_key() -> Optional[str]:
        """Get LangSmith API key."""
        return (
            getattr(settings, "LANGSMITH_API_KEY", None)
            or config("LANGSMITH_API_KEY", default=None)
        )

    @staticmethod
    def get_project_name() -> str:
        """Get LangSmith project name."""
        return (
            getattr(settings, "LANGSMITH_PROJECT", None)
            or config("LANGSMITH_PROJECT", default="sharif-assistant")
        )

    @staticmethod
    def get_tracing_enabled() -> bool:
        """Check if LangSmith tracing is enabled."""
        return (
            getattr(settings, "LANGSMITH_TRACING_ENABLED", None)
            or config("LANGSMITH_TRACING_ENABLED", default="true", cast=bool)
        )

    @staticmethod
    def get_endpoint() -> Optional[str]:
        """Get LangSmith endpoint (optional, defaults to cloud)."""
        return (
            getattr(settings, "LANGSMITH_ENDPOINT", None)
            or config("LANGSMITH_ENDPOINT", default=None)
        )

    @staticmethod
    def is_configured() -> bool:
        """Check if LangSmith is properly configured."""
        return (
            LangSmithConfig.get_tracing_enabled()
            and LangSmithConfig.get_api_key() is not None
        )


class DatabaseConfig:
    """Database configuration."""

    @staticmethod
    def get_database_config() -> dict:
        """Get database configuration."""
        return settings.DATABASES["default"]


class RedisConfig:
    """Redis configuration."""

    @staticmethod
    def get_host() -> str:
        """Get Redis host."""
        return config("REDIS_HOST", default="localhost")

    @staticmethod
    def get_port() -> int:
        """Get Redis port."""
        return config("REDIS_PORT", default="6379", cast=int)

    @staticmethod
    def get_db() -> int:
        """Get Redis database number."""
        return config("REDIS_DB", default=0, cast=int)

    @staticmethod
    def get_password() -> str:
        """Get Redis password."""
        return config("REDIS_PASSWORD", default="", cast=str)


def validate_required_config() -> None:
    """Validate that all required configuration is present."""
    errors = []
    try:
        TelegramConfig.get_bot_token()
    except ConfigError as e:
        errors.append(str(e))

    try:
        RAGConfig.get_api_url()
    except ConfigError as e:
        errors.append(str(e))

    try:
        LLMConfig.get_api_key()
    except ConfigError as e:
        errors.append(str(e))

    if errors:
        raise ConfigError(f"Configuration errors: {', '.join(errors)}")
