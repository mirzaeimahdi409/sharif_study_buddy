import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import KnowledgeDocument
from .tasks import delete_document_from_rag

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=KnowledgeDocument)
def delete_document_from_rag_on_model_delete(sender, instance: KnowledgeDocument, **kwargs):
    """
    When a KnowledgeDocument is deleted (including via Django admin),
    enqueue a background task to delete the corresponding document in the RAG microservice.
    """
    external_id = instance.external_id
    if not external_id:
        # Nothing to do if we never stored an external ID
        logger.info(
            "KnowledgeDocument (id=%s, title=%r) deleted without external_id; "
            "skipping RAG delete.",
            instance.id,
            instance.title,
        )
        return

    try:
        delete_document_from_rag.delay(external_id)
        logger.info(
            "Enqueued RAG delete for KnowledgeDocument (id=%s, title=%r, external_id=%s).",
            instance.id,
            instance.title,
            external_id,
        )
    except Exception as e:
        logger.exception(
            "Failed to enqueue RAG delete for KnowledgeDocument (id=%s, title=%r, external_id=%s): %s",
            instance.id,
            instance.title,
            external_id,
            e,
        )


