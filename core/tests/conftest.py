"""Pytest configuration and fixtures."""
import pytest
from django.contrib.auth import get_user_model
from core.models import UserProfile, ChatSession, KnowledgeDocument


@pytest.fixture
def user():
    """Create a test user."""
    User = get_user_model()
    return User.objects.create_user(
        username="test_user",
        email="test@example.com",
    )


@pytest.fixture
def user_profile(user):
    """Create a test user profile."""
    return UserProfile.objects.create(
        user=user,
        telegram_id="123456",
        display_name="Test User",
    )


@pytest.fixture
def chat_session(user_profile):
    """Create a test chat session."""
    return ChatSession.objects.create(
        user_profile=user_profile,
        is_active=True,
    )


@pytest.fixture
def knowledge_document():
    """Create a test knowledge document."""
    return KnowledgeDocument.objects.create(
        title="Test Document",
        content="This is a test document content.",
        source_url="https://example.com/test",
    )

