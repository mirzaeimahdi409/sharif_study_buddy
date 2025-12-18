"""
Celery tasks for background processing.
"""
import logging
from celery import shared_task
from django.core.cache import cache
from .models import KnowledgeDocument
from .services.rag_client import RAGClient, RAGClientError

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def push_document_to_rag(self, document_id: int) -> dict:
    """
    Push a KnowledgeDocument to RAG service asynchronously.

    Args:
        document_id: ID of the KnowledgeDocument to push

    Returns:
        Dictionary with result status and external_id if successful
    """
    try:
        doc = KnowledgeDocument.objects.get(id=document_id)
        client = RAGClient()

        metadata = {
            "title": doc.title,
            "django_id": str(doc.id),
            **(doc.metadata or {})
        }

        import asyncio

        if doc.source_url:
            result = asyncio.run(
                client.ingest_url(
                    url_to_fetch=doc.source_url,
                    metadata=metadata,
                )
            )
        else:
            result = asyncio.run(
                client.ingest_text(
                    title=doc.title,
                    content=doc.content,
                    metadata=metadata,
                )
            )

        # Extract external_id from RAG response
        external_id = (
            result.get("id")
            or result.get("document_id")
            or result.get("external_id")
        )

        # Update document
        update_fields = ["indexed_in_rag"]
        if external_id:
            doc.external_id = str(external_id)
            update_fields.append("external_id")

        doc.indexed_in_rag = True
        doc.save(update_fields=update_fields)

        logger.info(
            f"Successfully pushed document '{doc.title}' (ID: {document_id}) to RAG. "
            f"External ID: {external_id}"
        )

        return {
            "status": "success",
            "document_id": document_id,
            "external_id": external_id,
            "title": doc.title
        }

    except KnowledgeDocument.DoesNotExist:
        error_msg = f"Document with ID {document_id} not found"
        logger.error(error_msg)
        return {"status": "error", "error": error_msg}

    except RAGClientError as e:
        error_msg = f"RAG client error: {str(e)}"
        logger.error(
            f"Error pushing document {document_id} to RAG: {error_msg}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(
            f"Unexpected error pushing document {document_id} to RAG: {error_msg}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def reprocess_document_in_rag(self, document_id: int) -> dict:
    """
    Reprocess a document in RAG service asynchronously.

    Args:
        document_id: ID of the KnowledgeDocument to reprocess

    Returns:
        Dictionary with result status
    """
    try:
        doc = KnowledgeDocument.objects.get(id=document_id)
        client = RAGClient()

        # Use external_id if available, otherwise fall back to Django ID
        doc_id = doc.external_id or str(doc.id)

        import asyncio
        asyncio.run(client.reprocess_document(doc_id=doc_id))

        logger.info(
            f"Successfully reprocessed document '{doc.title}' (ID: {document_id}) in RAG. "
            f"Used doc_id: {doc_id}"
        )

        return {
            "status": "success",
            "document_id": document_id,
            "rag_doc_id": doc_id,
            "title": doc.title
        }

    except KnowledgeDocument.DoesNotExist:
        error_msg = f"Document with ID {document_id} not found"
        logger.error(error_msg)
        return {"status": "error", "error": error_msg}

    except RAGClientError as e:
        error_msg = f"RAG client error: {str(e)}"
        logger.error(
            f"Error reprocessing document {document_id} in RAG: {error_msg}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(
            f"Unexpected error reprocessing document {document_id}: {error_msg}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def delete_document_from_rag(self, external_id: str) -> dict:
    """
    Delete a document from RAG service asynchronously.

    Args:
        external_id: External ID of the document in RAG (usually stored on KnowledgeDocument.external_id)

    Returns:
        Dictionary with result status
    """
    try:
        client = RAGClient()

        import asyncio
        asyncio.run(client.delete_document(doc_id=external_id))

        logger.info(
            f"Successfully deleted document with external_id={external_id} from RAG."
        )

        return {
            "status": "success",
            "external_id": external_id,
        }

    except RAGClientError as e:
        error_msg = f"RAG client error: {str(e)}"
        logger.error(
            f"Error deleting document {external_id} from RAG: {error_msg}"
        )
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(
            f"Unexpected error deleting document {external_id} from RAG: {error_msg}"
        )
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task
def cleanup_old_chat_sessions(days_old: int = 90) -> dict:
    """
    Clean up old inactive chat sessions.

    Args:
        days_old: Number of days to keep sessions (default: 90)

    Returns:
        Dictionary with cleanup statistics
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import ChatSession

    cutoff_date = timezone.now() - timedelta(days=days_old)
    deleted_sessions = ChatSession.objects.filter(
        is_active=False,
        updated_at__lt=cutoff_date
    ).delete()

    logger.info(f"Cleaned up {deleted_sessions[0]} old chat sessions")

    return {
        "status": "success",
        "deleted_sessions": deleted_sessions[0],
        "cutoff_date": cutoff_date.isoformat()
    }
