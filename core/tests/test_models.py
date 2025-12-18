"""Tests for core models."""
import pytest
from django.core.exceptions import ValidationError
from core.models import UserProfile, ChatSession, ChatMessage, KnowledgeDocument


@pytest.mark.django_db
class TestUserProfile:
    """Tests for UserProfile model."""

    def test_create_user_profile(self, user):
        """Test creating a user profile."""
        profile = UserProfile.objects.create(
            user=user,
            telegram_id="123456",
            display_name="Test User",
        )
        assert profile.telegram_id == "123456"
        assert profile.display_name == "Test User"

    def test_user_profile_str(self, user_profile):
        """Test user profile string representation."""
        assert str(user_profile) == "Test User"

    def test_user_profile_unique_telegram_id(self, user):
        """Test that telegram_id must be unique."""
        UserProfile.objects.create(
            user=user,
            telegram_id="123456",
        )
        with pytest.raises(Exception):  # IntegrityError
            UserProfile.objects.create(
                user=user,
                telegram_id="123456",
            )


@pytest.mark.django_db
class TestChatSession:
    """Tests for ChatSession model."""

    def test_create_chat_session(self, user_profile):
        """Test creating a chat session."""
        session = ChatSession.objects.create(
            user_profile=user_profile,
            is_active=True,
        )
        assert session.user_profile == user_profile
        assert session.is_active is True

    def test_chat_session_str(self, chat_session):
        """Test chat session string representation."""
        assert "Session" in str(chat_session)


@pytest.mark.django_db
class TestChatMessage:
    """Tests for ChatMessage model."""

    def test_create_chat_message(self, chat_session):
        """Test creating a chat message."""
        message = ChatMessage.objects.create(
            session=chat_session,
            role="user",
            content="Test message",
        )
        assert message.session == chat_session
        assert message.role == "user"
        assert message.content == "Test message"


@pytest.mark.django_db
class TestKnowledgeDocument:
    """Tests for KnowledgeDocument model."""

    def test_create_knowledge_document(self):
        """Test creating a knowledge document."""
        doc = KnowledgeDocument.objects.create(
            title="Test Document",
            content="Test content",
        )
        assert doc.title == "Test Document"
        assert doc.content == "Test content"
        assert doc.indexed_in_rag is False

    def test_knowledge_document_content_length(self):
        """Test content_length property."""
        doc = KnowledgeDocument.objects.create(
            title="Test",
            content="12345",
        )
        assert doc.content_length == 5

