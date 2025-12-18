import logging
from typing import Iterable

from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import MonitoredChannel, IngestedTelegramMessage

import requests

logger = logging.getLogger(__name__)


def _delete_rag_documents(doc_ids: Iterable[str]) -> None:
    """
    Best-effort deletion of documents from the RAG service.

    Uses the DELETE /knowledge/documents/{id}/ endpoint for each id.
    Failures are logged but do not block channel deletion.
    """
    base_url = getattr(settings, "RAG_API_URL", "").rstrip("/")
    if not base_url:
        logger.warning(
            "RAG_API_URL is not configured; skipping RAG deletions.")
        return

    headers = {}
    rag_api_key = getattr(settings, "RAG_API_KEY", None)
    if rag_api_key:
        headers["Authorization"] = f"Bearer {rag_api_key}"

    # RAG delete endpoint expects user_id (and often microservice) as query params.
    # Keep them consistent with what we use for ingest/search.
    user_id = str(getattr(settings, "RAG_USER_ID", "") or "")
    microservice = getattr(settings, "RAG_MICROSERVICE",
                           None) or "telegram_bot"
    base_params = {}
    if user_id:
        base_params["user_id"] = user_id
    if microservice:
        base_params["microservice"] = microservice

    for doc_id in doc_ids:
        if not doc_id:
            continue
        url = f"{base_url}/knowledge/documents/{doc_id}/"
        try:
            resp = requests.delete(
                url,
                headers=headers,
                params=base_params,
                timeout=10,
            )
            if resp.status_code not in (200, 204, 404):
                logger.warning(
                    "Unexpected status when deleting RAG document %s: %s %s",
                    doc_id,
                    resp.status_code,
                    resp.text[:200],
                )
        except requests.RequestException as e:
            logger.warning("Failed to delete RAG document %s: %s", doc_id, e)


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
