import logging
from typing import Iterable

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import MonitoredChannel, IngestedTelegramMessage
from core.services.rag_client import RAGClient
from core.exceptions import RAGServiceError

logger = logging.getLogger(__name__)


def _delete_rag_documents(doc_ids: Iterable[str]) -> None:
    """
    Best-effort deletion of documents from the RAG service.

    Uses RAGClient to delete documents. Failures are logged but do not block channel deletion.
    Handles sync/async context issues properly by using a new event loop for each call.
    """
    try:
        client = RAGClient()
    except RAGServiceError as e:
        logger.warning(
            "RAGClient initialization failed; skipping RAG deletions: %s", e
        )
        return

    # Use RAGClient's synchronous wrapper which handles event loop creation
    for doc_id in doc_ids:
        if not doc_id:
            continue
        try:
            # delete_document_sync creates its own loop and thread, preventing
            # "Event loop is closed" errors in signal handlers
            client.delete_document_sync(doc_id)
            logger.debug("Successfully deleted RAG document %s", doc_id)
        except RAGServiceError as e:
            # RAGClient already handles 404 as success, so this is for other errors
            logger.warning("Failed to delete RAG document %s: %s", doc_id, e)
        except Exception as e:
            logger.warning(
                "Unexpected error deleting RAG document %s: %s", doc_id, e
            )
    
    # Clean up client resources
    try:
        # In a sync context, we can't await close(), but RAGClient uses httpx.AsyncClient
        # The sync wrappers manage their own loops, so the main client instance might need
        # to be closed if it was opened globally, but here it's local.
        pass 
    except Exception:
        pass


@receiver(pre_delete, sender=MonitoredChannel)
def delete_channel_rag_data(sender, instance: MonitoredChannel, **kwargs) -> None:
    """
    When a monitored channel is deleted, also delete all related RAG documents.

    We look up all IngestedTelegramMessage rows for this channel which have a
    rag_document_id and attempt to delete those documents from the RAG API.
    After that, we delete the ingestion records themselves.
    """
    channel_username = instance.username
    msgs = IngestedTelegramMessage.objects.filter(
        channel_username=channel_username,
        ingested=True,
    )

    doc_ids = [m.rag_document_id for m in msgs if m.rag_document_id]
    if doc_ids:
        logger.info(
            "Deleting %d RAG documents for channel @%s",
            len(doc_ids),
            channel_username,
        )
        _delete_rag_documents(doc_ids)

    # Clean up local ingestion records regardless of remote deletion success.
    deleted_count, _ = msgs.delete()
    logger.info(
        "Deleted %d IngestedTelegramMessage records for channel @%s",
        deleted_count,
        channel_username,
    )
