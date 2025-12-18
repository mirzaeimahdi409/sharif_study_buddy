import os
import logging
from typing import Any, Dict, Optional, List
import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class RAGClientError(Exception):
    """Exception raised for RAG client errors."""
    pass


class RAGClient:
    """
    Client for interacting with the RAG microservice API.

    Base URL should be set to the API root, e.g., 'http://45.67.139.109:8033/api'
    Endpoints:
    - POST /knowledge/search/ - Search for relevant documents
    - POST /knowledge/documents/ - Ingest text document
    - POST /knowledge/documents/ingest-url/ - Ingest document from URL
    - POST /knowledge/documents/{id}/reprocess/ - Reprocess a document
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: Optional[float] = None):
        # Try to get from Django settings first, then environment variables
        self.base_url = (
            base_url
            or getattr(settings, "RAG_API_URL", None)
            or os.getenv("RAG_API_URL", "")
        ).rstrip("/")

        if not self.base_url:
            raise RAGClientError(
                "RAG_API_URL not configured. Set it in Django settings or environment variable."
            )

        self.api_key = (
            api_key
            or getattr(settings, "RAG_API_KEY", None)
            or os.getenv("RAG_API_KEY")
        )
        # Default identifiers / knobs for RAG
        # Always prefer Django's RAG_USER_ID; fall back to envs only if missing.
        # This ensures the same user_id is used consistently for ingest + search.
        self.default_user_id = str(
            getattr(settings, "RAG_USER_ID", None)
            or os.getenv("RAG_USER_ID")
            or os.getenv("RAG_DEFAULT_USER_ID")
            or "5"
        )
        # Use Django settings first, then env, then default
        # This ensures consistency with monitoring/tasks.py ingest
        self.microservice = (
            getattr(settings, "RAG_MICROSERVICE", None)
            or os.getenv("RAG_MICROSERVICE")
            or "telegram_bot"
        )
        # Default retrieval score threshold (can be overridden via env)
        self.score_threshold = float(
            os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.25")
        )

        self.timeout = timeout or float(os.getenv("RAG_TIMEOUT", "30"))
        self._client = httpx.AsyncClient(timeout=self.timeout)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RAGClient initialized with base_url: {self.base_url[:50]}...")

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search for relevant documents in the RAG system.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional filters (e.g., document type, language, department)
            metadata_filter: Optional metadata-based filters

        Returns:
            Dictionary with search results (typically contains 'results' or 'data' key)
        """
        payload: Dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "score_threshold": self.score_threshold,
        }
        # Attach user_id and microservice for RAG API audit fields
        final_user_id = user_id or self.default_user_id
        if final_user_id:
            payload["user_id"] = str(final_user_id)
        if self.microservice:
            payload["microservice"] = self.microservice
        if filters:
            payload["filters"] = filters
        if metadata_filter:
            payload["metadata_filter"] = metadata_filter

        url = f"{self.base_url}/knowledge/search/"

        # Also send audit fields as query parameters in case the API expects them there
        params: Dict[str, Any] = {}
        if final_user_id:
            params["user_id"] = str(final_user_id)
        if self.microservice:
            params["microservice"] = self.microservice

        # Log exact payload for debugging (always, not just DEBUG level)
        try:
            import json
            pretty_payload = json.dumps(payload, ensure_ascii=False, indent=2)
            logger.info(
                "🔍 RAG search payload:\n%s\nURL: %s\nQuery params: %s",
                pretty_payload,
                url,
                params,
            )
        except Exception:
            logger.info(
                "🔍 RAG search: query=%s, user_id=%s, microservice=%s, top_k=%s",
                query[:100],
                final_user_id,
                self.microservice,
                top_k,
            )

        try:
            resp = await self._client.post(
                url,
                params=params,
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            result = resp.json()

            if logger.isEnabledFor(logging.DEBUG):
                result_count = len(result.get("results")
                                   or result.get("data") or [])
                logger.debug(f"RAG search returned {result_count} results")

            return result
        except httpx.HTTPStatusError as e:
            error_msg = f"Search error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during search: {str(e)}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e

    async def ingest_url(
        self,
        url_to_fetch: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a document from a URL into the RAG system.

        Args:
            url_to_fetch: URL of the document to fetch and ingest
            metadata: Optional metadata (e.g., title, department, category)

        Returns:
            Dictionary with ingestion result (may include document ID)
        """
        payload: Dict[str, Any] = {"url": url_to_fetch}
        final_user_id = user_id or self.default_user_id
        if final_user_id:
            payload["user_id"] = str(final_user_id)
        if self.microservice:
            payload["microservice"] = self.microservice
        if metadata:
            payload["metadata"] = metadata

        url = f"{self.base_url}/knowledge/documents/ingest-url/"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"RAG ingest URL: {url_to_fetch}")

        try:
            resp = await self._client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()

            if logger.isEnabledFor(logging.DEBUG):
                doc_id = result.get("id") or result.get("document_id")
                logger.debug(f"RAG ingest URL successful, doc_id: {doc_id}")

            return result
        except httpx.HTTPStatusError as e:
            error_msg = f"Ingest URL error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during URL ingest: {str(e)}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e

    async def ingest_text(
        self,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a text document into the RAG system.

        Args:
            title: Document title
            content: Document content/text
            metadata: Optional metadata (e.g., department, category, source_url)

        Returns:
            Dictionary with ingestion result (may include document ID)
        """
        payload: Dict[str, Any] = {"title": title, "content": content}
        final_user_id = user_id or self.default_user_id
        if final_user_id:
            payload["user_id"] = str(final_user_id)
        if self.microservice:
            payload["microservice"] = self.microservice
        if metadata:
            payload["metadata"] = metadata

        url = f"{self.base_url}/knowledge/documents/"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RAG ingest text: {title}, content length: {len(content)}")

        try:
            resp = await self._client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()

            if logger.isEnabledFor(logging.DEBUG):
                doc_id = result.get("id") or result.get("document_id")
                logger.debug(f"RAG ingest text successful, doc_id: {doc_id}")

            return result
        except httpx.HTTPStatusError as e:
            error_msg = f"Ingest text error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during text ingest: {str(e)}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e

    async def reprocess_document(self, doc_id: str) -> Dict[str, Any]:
        """
        Reprocess a document in the RAG system (e.g., re-index after content update).

        Args:
            doc_id: Document ID to reprocess

        Returns:
            Dictionary with reprocess result
        """
        url = f"{self.base_url}/knowledge/documents/{doc_id}/reprocess/"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"RAG reprocess document: {doc_id}")

        try:
            resp = await self._client.post(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json() if resp.text else {"status": "ok"}
        except httpx.HTTPStatusError as e:
            error_msg = f"Reprocess error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during reprocess: {str(e)}"
            logger.error(error_msg)
            raise RAGClientError(error_msg) from e

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
