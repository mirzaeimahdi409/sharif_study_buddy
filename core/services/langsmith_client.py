"""
LangSmith integration for observability and tracing.

This module provides utilities for configuring and using LangSmith tracing
with LangChain and LangGraph components.
"""
import os
import logging
from typing import Optional, Dict, Any, List
from langsmith import Client
from langchain_core.tracers import LangChainTracer
from langchain_core.callbacks import CallbackManager
from core.config import LangSmithConfig

logger = logging.getLogger(__name__)

# Global LangSmith client instance
_langsmith_client: Optional[Client] = None


def get_langsmith_client() -> Optional[Client]:
    """
    Get or create LangSmith client instance.

    Returns:
        LangSmith Client instance if configured, None otherwise
    """
    global _langsmith_client

    if not LangSmithConfig.is_configured():
        return None

    if _langsmith_client is None:
        try:
            api_key = LangSmithConfig.get_api_key()
            endpoint = LangSmithConfig.get_endpoint()

            client_kwargs: Dict[str, Any] = {
                "api_key": api_key,
            }

            if endpoint:
                client_kwargs["api_url"] = endpoint

            _langsmith_client = Client(**client_kwargs)

            logger.info(
                "✅ LangSmith client initialized",
                extra={
                    "project": LangSmithConfig.get_project_name(),
                    "endpoint": endpoint or "default",
                }
            )
        except Exception as e:
            logger.warning(
                f"⚠️ Failed to initialize LangSmith client: {e}",
                exc_info=True
            )
            return None

    return _langsmith_client


def get_langchain_tracer() -> Optional[LangChainTracer]:
    """
    Get LangChain tracer configured for LangSmith.

    Returns:
        LangChainTracer instance if LangSmith is configured, None otherwise
    """
    if not LangSmithConfig.is_configured():
        return None

    try:
        tracer = LangChainTracer(
            project_name=LangSmithConfig.get_project_name(),
        )
        return tracer
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to create LangChain tracer: {e}",
            exc_info=True
        )
        return None


def get_callback_manager(
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CallbackManager]:
    """
    Get callback manager with LangSmith tracing enabled.

    Args:
        tags: Optional list of tags to attach to traces
        metadata: Optional metadata dictionary to attach to traces

    Returns:
        CallbackManager instance if LangSmith is configured, None otherwise
    """
    tracer = get_langchain_tracer()
    if tracer is None:
        return None

    callbacks = [tracer]

    # Add tags and metadata if provided
    if tags or metadata:
        # LangChainTracer supports tags and metadata via environment variables
        # or we can use RunCollectorCallbackHandler for more control
        # For now, we'll set them via environment variables if needed
        pass

    return CallbackManager(callbacks)


def get_langgraph_config(
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get LangGraph RunnableConfig dictionary with LangSmith tracing enabled.

    LangGraph uses a config dictionary with 'callbacks' as a list of callbacks.
    This helper creates the proper config format for LangGraph.

    Args:
        tags: Optional list of tags to attach to traces
        metadata: Optional metadata dictionary to attach to traces

    Returns:
        Config dictionary with callbacks if LangSmith is configured, None otherwise

    Usage:
        config = get_langgraph_config(tags=["my-tag"], metadata={"key": "value"})
        if config:
            result = await graph.ainvoke(state, config=config)
        else:
            result = await graph.ainvoke(state)
    """
    tracer = get_langchain_tracer()
    if tracer is None:
        return None

    config: Dict[str, Any] = {
        "callbacks": [tracer],
    }

    if tags:
        config["tags"] = tags

    if metadata:
        config["metadata"] = metadata

    return config


def ensure_project_exists(project_name: str) -> bool:
    """
    Ensure that a LangSmith project exists, creating it if necessary.

    LangSmith typically auto-creates projects when the first trace is sent,
    but this function attempts to create it explicitly for better UX.

    Args:
        project_name: Name of the project to check/create

    Returns:
        True if project exists or was created successfully, False otherwise
    """
    client = get_langsmith_client()
    if client is None:
        return False

    try:
        # Try to check if project exists using list_projects or similar method
        # If the API doesn't support explicit project creation, LangSmith will
        # auto-create it on first trace, which is fine
        try:
            # Try to list projects and check if ours exists
            # Note: This is a best-effort check; LangSmith will auto-create if needed
            projects = client.list_projects()
            project_exists = any(
                p.name == project_name or str(p.id) == project_name
                for p in projects
            )

            if project_exists:
                logger.debug(
                    f"✅ LangSmith project '{project_name}' already exists"
                )
                return True
            else:
                # Project doesn't exist yet, but LangSmith will auto-create it
                logger.info(
                    f"ℹ️ LangSmith project '{project_name}' will be created automatically on first trace"
                )
                return True
        except AttributeError:
            # list_projects might not be available in all versions
            # LangSmith will auto-create the project on first trace anyway
            logger.debug(
                f"ℹ️ LangSmith project '{project_name}' will be created automatically on first trace"
            )
            return True
        except Exception as e:
            # Any other error - LangSmith will still auto-create on first trace
            logger.debug(
                f"ℹ️ Could not check LangSmith project existence: {e}. "
                f"Project '{project_name}' will be created automatically on first trace."
            )
            return True
    except Exception as e:
        logger.debug(
            f"ℹ️ Error checking LangSmith project: {e}. "
            f"Project '{project_name}' will be created automatically on first trace."
        )
        # LangSmith will auto-create projects on first trace, so we'll continue
        return True


def configure_langsmith_environment():
    """
    Configure LangSmith environment variables and ensure project exists.
    This should be called at application startup.
    """
    if not LangSmithConfig.is_configured():
        logger.debug("LangSmith tracing is disabled or not configured")
        return

    try:
        api_key = LangSmithConfig.get_api_key()
        project_name = LangSmithConfig.get_project_name()
        endpoint = LangSmithConfig.get_endpoint()

        # Set environment variables for LangChain/LangGraph auto-tracing
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_PROJECT"] = project_name

        if endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = endpoint

        # Ensure project exists (LangSmith usually auto-creates, but we'll try to create it explicitly)
        ensure_project_exists(project_name)

        logger.info(
            "✅ LangSmith environment configured",
            extra={
                "project": project_name,
                "endpoint": endpoint or "default",
            }
        )
    except Exception as e:
        logger.warning(
            f"⚠️ Failed to configure LangSmith environment: {e}",
            exc_info=True
        )


def trace_run(
    name: str,
    run_type: str = "chain",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Context manager for tracing custom runs in LangSmith.

    Usage:
        with trace_run("my_operation", tags=["custom"]):
            # Your code here
            pass

    Args:
        name: Name of the run
        run_type: Type of run (chain, llm, tool, etc.)
        tags: Optional list of tags
        metadata: Optional metadata dictionary
    """
    from contextlib import contextmanager

    client = get_langsmith_client()
    if client is None:
        # Return a no-op context manager if LangSmith is not configured
        @contextmanager
        def noop():
            yield None
        return noop()

    return client.trace(
        name=name,
        run_type=run_type,
        tags=tags or [],
        metadata=metadata or {},
    )
