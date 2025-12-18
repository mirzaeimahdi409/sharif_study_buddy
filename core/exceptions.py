"""Custom exception classes for the application."""


class BaseApplicationError(Exception):
    """Base exception for all application errors."""
    pass


class ConfigurationError(BaseApplicationError):
    """Raised when there's a configuration error."""
    pass


class ServiceError(BaseApplicationError):
    """Base exception for service-related errors."""
    pass


class RAGServiceError(ServiceError):
    """Raised when RAG service operations fail."""
    pass


class LLMServiceError(ServiceError):
    """Raised when LLM service operations fail."""
    pass


class TelegramServiceError(ServiceError):
    """Raised when Telegram service operations fail."""
    pass


class ValidationError(BaseApplicationError):
    """Raised when validation fails."""
    pass


class NotFoundError(BaseApplicationError):
    """Raised when a requested resource is not found."""
    pass


class AuthenticationError(BaseApplicationError):
    """Raised when authentication fails."""
    pass


class AuthorizationError(BaseApplicationError):
    """Raised when authorization fails."""
    pass

