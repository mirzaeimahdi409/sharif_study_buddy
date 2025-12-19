import os
import logging
import time
import asyncio
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse
import httpx
from core.exceptions import RAGServiceError
from core.config import RAGConfig
from core.services import metrics

logger = logging.getLogger(__name__)

# Backward compatibility alias
RAGClientError = RAGServiceError


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
        # Use RAGConfig for configuration
        self.base_url = (base_url or RAGConfig.get_api_url()).rstrip("/")

        self.api_key = api_key or RAGConfig.get_api_key()
        # Default identifiers / knobs for RAG
        # Always prefer Django's RAG_USER_ID; fall back to envs only if missing.
        # This ensures the same user_id is used consistently for ingest + search.
        self.default_user_id = str(RAGConfig.get_user_id())
        # Use Django settings first, then env, then default
        # This ensures consistency with monitoring/tasks.py ingest
        self.microservice = RAGConfig.get_microservice()
        # Default retrieval score threshold (can be overridden via env)
        self.score_threshold = float(
            os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.25")
        )

        self.timeout = timeout or float(os.getenv("RAG_TIMEOUT", "30"))
        
        # Create httpx client with detailed configuration
        client_timeout = httpx.Timeout(
            connect=float(os.getenv("RAG_CONNECT_TIMEOUT", str(self.timeout))),
            read=float(os.getenv("RAG_READ_TIMEOUT", str(self.timeout))),
            write=float(os.getenv("RAG_WRITE_TIMEOUT", str(self.timeout))),
            pool=float(os.getenv("RAG_POOL_TIMEOUT", str(self.timeout))),
        )
        
        # Configure limits for connection pool
        limits = httpx.Limits(
            max_keepalive_connections=int(os.getenv("RAG_MAX_KEEPALIVE", "5")),
            max_connections=int(os.getenv("RAG_MAX_CONNECTIONS", "10")),
        )
        
        self._client = httpx.AsyncClient(
            timeout=client_timeout,
            limits=limits,
            follow_redirects=True,
        )

        logger.info(
            "🔧 RAGClient initialized",
            extra={
                "base_url": self.base_url,
                "timeout": self.timeout,
                "connect_timeout": client_timeout.connect,
                "read_timeout": client_timeout.read,
                "max_connections": limits.max_connections,
                "max_keepalive": limits.max_keepalive_connections,
                "has_api_key": bool(self.api_key),
                "user_id": self.default_user_id,
                "microservice": self.microservice,
            }
        )

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

        # Track RAG search request
        search_start_time = time.time()
        try:
            resp = await self._client.post(
                url,
                params=params,
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            result = resp.json()
            
            # Calculate duration
            search_duration = time.time() - search_start_time
            metrics.rag_search_duration_seconds.observe(search_duration)
            
            # Get result count
            items = result.get("results") or result.get("data") or []
            result_count = len(items)
            
            # Track metrics
            metrics.rag_search_requests_total.labels(status='success').inc()
            metrics.rag_documents_retrieved.observe(result_count)
            
            # Track document scores if available
            for item in items:
                score = item.get("score") or (item.get("metadata") or {}).get("score")
                if score is not None:
                    try:
                        metrics.rag_document_scores.observe(float(score))
                    except (ValueError, TypeError):
                        pass

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"RAG search returned {result_count} results")

            return result
        except httpx.HTTPStatusError as e:
            search_duration = time.time() - search_start_time
            metrics.rag_search_duration_seconds.observe(search_duration)
            metrics.rag_search_requests_total.labels(status='error').inc()
            metrics.rag_search_errors_total.labels(error_type='http_error').inc()
            error_msg = f"Search error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e
        except httpx.RequestError as e:
            search_duration = time.time() - search_start_time
            metrics.rag_search_duration_seconds.observe(search_duration)
            metrics.rag_search_requests_total.labels(status='error').inc()
            error_type = 'timeout' if isinstance(e, httpx.TimeoutException) else 'request_error'
            metrics.rag_search_errors_total.labels(error_type=error_type).inc()
            error_msg = f"Request error during search: {str(e)}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e

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
            raise RAGServiceError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during URL ingest: {str(e)}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e

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
            raise RAGServiceError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during text ingest: {str(e)}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e

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
            raise RAGServiceError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during reprocess: {str(e)}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e

    async def ingest_channel_message(
        self,
        title: str,
        text_content: str,
        published_at: str,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a Telegram channel message into the RAG system.

        Args:
            title: Title for the message document
            text_content: The full text content of the message
            published_at: The original publication timestamp (ISO 8601 format)
            source_url: A direct URL to the original message for citation
            metadata: Optional metadata (e.g., channel, message_id)
            user_id: Optional user ID (defaults to self.default_user_id)

        Returns:
            Dictionary with ingestion result (may include document ID)
        """
        payload: Dict[str, Any] = {
            "title": title,
            "text_content": text_content,
            "published_at": published_at,
            "source_url": source_url,
        }
        final_user_id = user_id or self.default_user_id
        if final_user_id:
            payload["user_id"] = str(final_user_id)
        if self.microservice:
            payload["microservice"] = self.microservice
        if metadata:
            payload["metadata"] = metadata

        url = f"{self.base_url}/knowledge/documents/ingest-channel-message/"

        # Parse URL for diagnostics
        parsed_url = urlparse(url)
        host = parsed_url.hostname
        port = parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)
        scheme = parsed_url.scheme

        # Detailed logging before request
        logger.info(
            "🔵 RAG ingest channel message - Starting request",
            extra={
                "url": url,
                "base_url": self.base_url,
                "host": host,
                "port": port,
                "scheme": scheme,
                "timeout": self.timeout,
                "title": title[:100] if title else None,
                "text_content_length": len(text_content) if text_content else 0,
                "source_url": source_url,
                "user_id": final_user_id,
                "microservice": self.microservice,
            }
        )
        
        # Log payload size for debugging
        import json
        try:
            payload_size = len(json.dumps(payload, ensure_ascii=False))
            logger.debug(f"Request payload size: {payload_size} bytes")
        except Exception:
            pass

        # Retry logic for connection errors
        max_retries = int(os.getenv("RAG_MAX_RETRIES", "3"))
        retry_delay = float(os.getenv("RAG_RETRY_DELAY", "1.0"))
        last_exception = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    f"Making POST request to: {url} (attempt {attempt}/{max_retries})",
                    extra={
                        "attempt": attempt,
                        "max_retries": max_retries,
                        "host": host,
                        "port": port,
                        "scheme": scheme,
                    }
                )
                logger.debug(f"Client timeout: {self._client.timeout}")
                logger.debug(f"Client base_url: {self._client.base_url}")
                
                resp = await self._client.post(url, json=payload, headers=self._headers())
                
                logger.info(
                    f"✅ RAG ingest channel message - Response received: {resp.status_code}",
                    extra={"status_code": resp.status_code, "url": url}
                )
                
                resp.raise_for_status()
                result = resp.json()

                doc_id = result.get("id") or result.get("document_id")
                logger.info(
                    f"✅ RAG ingest channel message successful, doc_id: {doc_id} (attempt {attempt})",
                    extra={"doc_id": doc_id, "url": url, "attempt": attempt}
                )

                return result
            except (httpx.ConnectError, httpx.NetworkError) as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logger.warning(
                        f"⚠️ Connection error on attempt {attempt}/{max_retries}, retrying in {wait_time:.1f}s",
                        extra={
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "wait_time": wait_time,
                            "host": host,
                            "port": port,
                            "scheme": scheme,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        }
                    )
                    await asyncio.sleep(wait_time)
                else:
                    # Last attempt failed
                    error_msg = f"Connection error during channel message ingest after {max_retries} attempts: {str(e)}"
                    logger.error(
                        f"🔴 RAG ingest channel message - Connection error (all {max_retries} attempts failed): {error_msg}",
                        extra={
                            "url": url,
                            "base_url": self.base_url,
                            "host": host,
                            "port": port,
                            "scheme": scheme,
                            "timeout": self.timeout,
                            "attempts": max_retries,
                            "exception_type": type(e).__name__,
                            "exception_args": str(e.args) if hasattr(e, 'args') else None,
                            "exception_repr": repr(e),
                        },
                        exc_info=True
                    )
                    raise RAGServiceError(error_msg) from e
            except httpx.HTTPStatusError as e:
                # HTTP errors are not retried (4xx, 5xx)
                error_msg = f"Ingest channel message error {e.response.status_code}: {e.response.text[:200]}"
                logger.error(
                    f"❌ RAG ingest channel message - HTTP error: {error_msg}",
                    extra={
                        "status_code": e.response.status_code,
                        "url": url,
                        "base_url": self.base_url,
                        "host": host,
                        "port": port,
                        "response_text": e.response.text[:500] if e.response.text else None,
                        "headers": dict(e.response.headers) if hasattr(e.response, 'headers') else None,
                    },
                    exc_info=True
                )
                raise RAGServiceError(error_msg) from e
            except httpx.TimeoutException as e:
                # Timeout errors are retried
                last_exception = e
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"⏱️ Timeout on attempt {attempt}/{max_retries}, retrying in {wait_time:.1f}s",
                        extra={
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "wait_time": wait_time,
                            "timeout": self.timeout,
                            "host": host,
                            "port": port,
                        }
                    )
                    await asyncio.sleep(wait_time)
                else:
                    error_msg = f"Timeout during channel message ingest after {max_retries} attempts (timeout={self.timeout}s): {str(e)}"
                    logger.error(
                        f"⏱️ RAG ingest channel message - Timeout (all {max_retries} attempts failed): {error_msg}",
                        extra={
                            "url": url,
                            "base_url": self.base_url,
                            "host": host,
                            "port": port,
                            "timeout": self.timeout,
                            "attempts": max_retries,
                            "exception_type": type(e).__name__,
                        },
                        exc_info=True
                    )
                    raise RAGServiceError(error_msg) from e
                except httpx.RequestError as e:
                # Other request errors - retry if it's a network issue
                if isinstance(e, (httpx.ConnectError, httpx.NetworkError)):
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = retry_delay * (2 ** (attempt - 1))
                        logger.warning(
                            f"⚠️ Request error on attempt {attempt}/{max_retries}, retrying in {wait_time:.1f}s",
                            extra={
                                "attempt": attempt,
                                "max_retries": max_retries,
                                "wait_time": wait_time,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            }
                        )
                        await asyncio.sleep(wait_time)
                        continue
                
                # Non-retryable request error or last attempt
                error_msg = f"Request error during channel message ingest: {str(e)}"
                logger.error(
                    f"❌ RAG ingest channel message - Request error: {error_msg}",
                    extra={
                        "url": url,
                        "base_url": self.base_url,
                        "host": host,
                        "port": port,
                        "timeout": self.timeout,
                        "attempt": attempt,
                        "exception_type": type(e).__name__,
                        "exception_args": str(e.args) if hasattr(e, 'args') else None,
                        "request_url": str(e.request.url) if hasattr(e, 'request') and e.request else None,
                    },
                    exc_info=True
                )
                raise RAGServiceError(error_msg) from e
                except Exception as e:
                # Unexpected errors are not retried
                error_msg = f"Unexpected error during channel message ingest: {str(e)}"
                logger.error(
                    f"💥 RAG ingest channel message - Unexpected error: {error_msg}",
                    extra={
                        "url": url,
                        "base_url": self.base_url,
                        "host": host,
                        "port": port,
                        "attempt": attempt,
                        "exception_type": type(e).__name__,
                    },
                    exc_info=True
                )
                raise RAGServiceError(error_msg) from e
        
        # This should never be reached, but just in case
        if last_exception:
            raise RAGServiceError(f"All {max_retries} connection attempts failed") from last_exception

    async def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """
        Delete a document from the RAG system.

        Args:
            doc_id: Document ID to delete (usually external_id from RAG)

        Returns:
            Dictionary with delete result
        """
        url = f"{self.base_url}/knowledge/documents/{doc_id}/"

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"RAG delete document: {doc_id}")

        try:
            resp = await self._client.delete(url, headers=self._headers())
            # Treat 404 as a successful "already deleted" case
            if resp.status_code == 404:
                logger.info(
                    "RAG delete document: doc_id=%s already missing (404). Treating as success.",
                    doc_id,
                )
                return {"status": "ok", "detail": "not_found_already_deleted"}

            resp.raise_for_status()
            return resp.json() if resp.text else {"status": "ok"}
        except httpx.HTTPStatusError as e:
            error_msg = f"Delete error {e.response.status_code}: {e.response.text[:200]}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e
        except httpx.RequestError as e:
            error_msg = f"Request error during delete: {str(e)}"
            logger.error(error_msg)
            raise RAGServiceError(error_msg) from e

    # Sync wrapper methods for use in Celery tasks and sync contexts
    def search_sync(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for search method."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_in_thread():
            # Create a new event loop in this thread to avoid conflicts
            # with Celery's fork-based workers and anyio initialization issues
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.search(query, top_k, filters, metadata_filter, user_id)
                )
            finally:
                loop.close()
        
        # Use a thread pool executor to isolate the async code
        # This prevents anyio/httpx issues in Celery fork workers
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    def ingest_url_sync(
        self,
        url_to_fetch: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for ingest_url method."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.ingest_url(url_to_fetch, metadata, user_id)
                )
            finally:
                loop.close()
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    def ingest_text_sync(
        self,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for ingest_text method."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    self.ingest_text(title, content, metadata, user_id)
                )
            finally:
                loop.close()
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    def ingest_channel_message_sync(
        self,
        title: str,
        text_content: str,
        published_at: str,
        source_url: str,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for ingest_channel_message method."""
        import asyncio
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        
        main_thread_id = threading.current_thread().ident
        logger.info(
            "🔄 Starting sync wrapper for ingest_channel_message",
            extra={
                "main_thread_id": main_thread_id,
                "title": title[:100] if title else None,
                "source_url": source_url,
                "base_url": self.base_url,
            }
        )
        
        start_time = time.time()
        
        def run_in_thread():
            thread_id = threading.current_thread().ident
            logger.debug(
                f"📌 Async execution started in thread {thread_id}",
                extra={"thread_id": thread_id, "main_thread_id": main_thread_id}
            )
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logger.debug(f"Event loop created in thread {thread_id}")
                result = loop.run_until_complete(
                    self.ingest_channel_message(
                        title, text_content, published_at, source_url, metadata, user_id
                    )
                )
                logger.debug(f"Async execution completed in thread {thread_id}")
                return result
            except Exception as e:
                logger.error(
                    f"❌ Exception in async thread {thread_id}: {type(e).__name__}: {str(e)}",
                    extra={"thread_id": thread_id, "exception_type": type(e).__name__},
                    exc_info=True
                )
                raise
            finally:
                loop.close()
                logger.debug(f"Event loop closed in thread {thread_id}")
        
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                logger.debug("ThreadPoolExecutor created, submitting task")
                future = executor.submit(run_in_thread)
                logger.debug("Task submitted, waiting for result")
                result = future.result()
                
                duration = time.time() - start_time
                logger.info(
                    f"✅ Sync wrapper completed successfully in {duration:.2f}s",
                    extra={"duration": duration, "main_thread_id": main_thread_id}
                )
                return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"❌ Sync wrapper failed after {duration:.2f}s: {type(e).__name__}: {str(e)}",
                extra={
                    "duration": duration,
                    "main_thread_id": main_thread_id,
                    "exception_type": type(e).__name__,
                },
                exc_info=True
            )
            raise

    def reprocess_document_sync(self, doc_id: str) -> Dict[str, Any]:
        """Synchronous wrapper for reprocess_document method."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.reprocess_document(doc_id))
            finally:
                loop.close()
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    def delete_document_sync(self, doc_id: str) -> Dict[str, Any]:
        """Synchronous wrapper for delete_document method."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.delete_document(doc_id))
            finally:
                loop.close()
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_thread)
            return future.result()

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
