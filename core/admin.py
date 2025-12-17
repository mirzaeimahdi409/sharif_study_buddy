import logging
from django.contrib import admin
from .models import UserProfile, ChatSession, ChatMessage, KnowledgeDocument
from .services.rag_client import RAGClient, RAGClientError
from django.contrib import messages

logger = logging.getLogger(__name__)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "telegram_id", "display_name", "created_at")
    search_fields = ("telegram_id", "display_name")
    readonly_fields = ("created_at",)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user_profile", "title", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("user_profile__telegram_id", "title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)
    readonly_fields = ("created_at",)


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "source_url",
        "external_id",
        "indexed_in_rag",
        "content_length_display",
        "created_at",
        "updated_at"
    )
    list_filter = ("indexed_in_rag", "created_at", "updated_at")
    search_fields = ("title", "content", "source_url", "external_id")
    readonly_fields = ("created_at", "updated_at", "content_length_display")
    actions = ("push_to_rag", "reprocess_in_rag",
               "mark_as_indexed", "unmark_as_indexed")

    fieldsets = (
        ("اطلاعات اصلی", {
            "fields": ("title", "content", "source_url")
        }),
        ("متادیتا", {
            "fields": ("metadata",)
        }),
        ("وضعیت RAG", {
            "fields": ("indexed_in_rag", "external_id")
        }),
        ("اطلاعات سیستم", {
            "fields": ("created_at", "updated_at", "content_length_display"),
            "classes": ("collapse",)
        }),
    )

    def content_length_display(self, obj):
        """Display content length in a human-readable format."""
        length = obj.content_length
        if length < 1000:
            return f"{length} کاراکتر"
        return f"{length / 1000:.1f}K کاراکتر"
    content_length_display.short_description = "طول محتوا"

    def push_to_rag(self, request, queryset):
        """Push selected documents to RAG service asynchronously using Celery."""
        from .tasks import push_document_to_rag

        queued = 0
        for doc in queryset:
            try:
                # Queue the task
                push_document_to_rag.delay(doc.id)
                queued += 1
                logger.info(
                    f"Queued document '{doc.title}' (ID: {doc.id}) for RAG push")
            except Exception as e:
                error_msg = f"'{doc.title}': Failed to queue task - {e}"
                logger.error(error_msg)
                self.message_user(
                    request, error_msg, level=messages.ERROR
                )

        if queued > 0:
            self.message_user(
                request,
                f"✅ {queued} سند در صف ارسال به RAG قرار گرفت. پردازش در پس‌زمینه انجام می‌شود.",
                level=messages.SUCCESS
            )

    push_to_rag.short_description = "📤 ارسال اسناد انتخاب‌شده به RAG"

    def reprocess_in_rag(self, request, queryset):
        """Reprocess documents in RAG service asynchronously using Celery."""
        from .tasks import reprocess_document_in_rag

        queued = 0
        for doc in queryset:
            try:
                # Queue the task
                reprocess_document_in_rag.delay(doc.id)
                queued += 1
                logger.info(
                    f"Queued document '{doc.title}' (ID: {doc.id}) for RAG reprocess")
            except Exception as e:
                error_msg = f"'{doc.title}': Failed to queue task - {e}"
                logger.error(error_msg)
                self.message_user(
                    request, error_msg, level=messages.ERROR
                )

        if queued > 0:
            self.message_user(
                request,
                f"✅ {queued} سند در صف بازپردازش قرار گرفت. پردازش در پس‌زمینه انجام می‌شود.",
                level=messages.SUCCESS
            )

    reprocess_in_rag.short_description = "🔄 بازپردازش اسناد در RAG"

    def mark_as_indexed(self, request, queryset):
        """Mark selected documents as indexed without actually pushing to RAG."""
        updated = queryset.update(indexed_in_rag=True)
        self.message_user(
            request,
            f"✅ {updated} سند به عنوان ایندکس‌شده علامت‌گذاری شد.",
            level=messages.SUCCESS
        )

    mark_as_indexed.short_description = "✓ علامت‌گذاری به عنوان ایندکس‌شده"

    def unmark_as_indexed(self, request, queryset):
        """Unmark selected documents as indexed."""
        updated = queryset.update(indexed_in_rag=False)
        self.message_user(
            request,
            f"✅ {updated} سند از حالت ایندکس‌شده خارج شد.",
            level=messages.SUCCESS
        )

    unmark_as_indexed.short_description = "✗ خارج کردن از حالت ایندکس‌شده"
