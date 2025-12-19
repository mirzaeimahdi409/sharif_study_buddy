"""
Prometheus metrics for the Sharif Bot application.
Comprehensive metrics tracking for messages, users, RAG, LLM, and more.
"""
from prometheus_client import Counter, Histogram, Gauge, Summary
from typing import Optional

# ============================================================================
# Message Metrics
# ============================================================================

# Total messages received from users
messages_received_total = Counter(
    'sharif_bot_messages_received_total',
    'Total number of messages received from users',
    ['message_type']  # 'text', 'command', etc.
)

# Total messages sent to users
messages_sent_total = Counter(
    'sharif_bot_messages_sent_total',
    'Total number of messages sent to users',
    ['message_type']  # 'text', 'error', etc.
)

# Message processing duration
message_processing_duration_seconds = Histogram(
    'sharif_bot_message_processing_duration_seconds',
    'Time spent processing a message from receipt to response',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
)

# ============================================================================
# User Metrics
# ============================================================================

# Total active users (current count)
active_users_total = Gauge(
    'sharif_bot_active_users_total',
    'Current number of active users (users with active sessions)'
)

# New users created
new_users_total = Counter(
    'sharif_bot_new_users_total',
    'Total number of new users created'
)

# Total unique users (all time)
total_users_total = Gauge(
    'sharif_bot_total_users_total',
    'Total number of unique users (all time)'
)

# User sessions created
user_sessions_total = Counter(
    'sharif_bot_user_sessions_total',
    'Total number of user sessions created'
)

# ============================================================================
# Reset Command Metrics
# ============================================================================

# Reset commands executed
reset_commands_total = Counter(
    'sharif_bot_reset_commands_total',
    'Total number of /reset commands executed'
)

# ============================================================================
# RAG (Retrieval) Metrics
# ============================================================================

# RAG search requests
rag_search_requests_total = Counter(
    'sharif_bot_rag_search_requests_total',
    'Total number of RAG search requests',
    ['status']  # 'success', 'error'
)

# RAG search duration
rag_search_duration_seconds = Histogram(
    'sharif_bot_rag_search_duration_seconds',
    'Time spent on RAG search operations',
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# RAG documents retrieved per query
rag_documents_retrieved = Histogram(
    'sharif_bot_rag_documents_retrieved',
    'Number of documents retrieved from RAG per query',
    buckets=[0, 1, 2, 3, 4, 5, 10, 15, 20]
)

# RAG search errors
rag_search_errors_total = Counter(
    'sharif_bot_rag_search_errors_total',
    'Total number of RAG search errors',
    ['error_type']  # 'timeout', 'http_error', 'service_error', etc.
)

# ============================================================================
# LLM (Language Model) Metrics
# ============================================================================

# LLM invocations
llm_invocations_total = Counter(
    'sharif_bot_llm_invocations_total',
    'Total number of LLM invocations',
    ['model', 'status']  # model name, 'success' or 'error'
)

# LLM invocation duration
llm_invocation_duration_seconds = Histogram(
    'sharif_bot_llm_invocation_duration_seconds',
    'Time spent on LLM invocations',
    ['model'],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0]
)

# LLM response tokens (if available)
llm_response_tokens = Histogram(
    'sharif_bot_llm_response_tokens',
    'Number of tokens in LLM responses',
    ['model'],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000]
)

# LLM errors
llm_errors_total = Counter(
    'sharif_bot_llm_errors_total',
    'Total number of LLM errors',
    ['model', 'error_type']  # 'timeout', 'api_error', 'rate_limit', etc.
)

# ============================================================================
# RAG Context Usage Metrics
# ============================================================================

# Messages where RAG context was provided to LLM
rag_context_provided_total = Counter(
    'sharif_bot_rag_context_provided_total',
    'Total number of messages where RAG context was provided to LLM',
    ['has_documents']  # 'true' or 'false'
)

# Messages where LLM used RAG sources (sources referenced in answer)
rag_sources_used_total = Counter(
    'sharif_bot_rag_sources_used_total',
    'Total number of messages where LLM used RAG sources in answer',
    ['used']  # 'true' or 'false'
)

# Messages where RAG context was relevant and used
rag_context_relevant_used_total = Counter(
    'sharif_bot_rag_context_relevant_used_total',
    'Total number of messages where RAG context was relevant and used by LLM',
    ['relevant_used']  # 'true' or 'false'
)

# Messages where RAG context was provided but not used (unrelated)
rag_context_unrelated_total = Counter(
    'sharif_bot_rag_context_unrelated_total',
    'Total number of messages where RAG context was provided but not used (unrelated)',
    ['unrelated']  # 'true' or 'false'
)

# RAG document relevance score distribution
rag_document_scores = Histogram(
    'sharif_bot_rag_document_scores',
    'Relevance scores of retrieved RAG documents',
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

# ============================================================================
# Pipeline Metrics
# ============================================================================

# Complete pipeline executions
pipeline_executions_total = Counter(
    'sharif_bot_pipeline_executions_total',
    'Total number of complete pipeline executions',
    ['status']  # 'success', 'error'
)

# Pipeline execution duration
pipeline_execution_duration_seconds = Histogram(
    'sharif_bot_pipeline_execution_duration_seconds',
    'Time spent on complete pipeline execution (RAG + LLM)',
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0]
)

# Pipeline errors
pipeline_errors_total = Counter(
    'sharif_bot_pipeline_errors_total',
    'Total number of pipeline errors',
    ['error_type']  # 'rag_error', 'llm_error', 'general_error'
)

# ============================================================================
# Command Metrics
# ============================================================================

# Commands executed
commands_total = Counter(
    'sharif_bot_commands_total',
    'Total number of commands executed',
    ['command']  # 'start', 'help', 'reset', 'admin', etc.
)

# ============================================================================
# Error Metrics
# ============================================================================

# General errors
errors_total = Counter(
    'sharif_bot_errors_total',
    'Total number of errors',
    ['error_type', 'component']  # error type, component name
)

# ============================================================================
# Helper Functions
# ============================================================================

def detect_rag_source_usage(answer: str, context: str) -> bool:
    """
    Detect if LLM used RAG sources in the answer.
    
    Checks for:
    - HTML links (<a href=...>)
    - Source references in the answer
    - Citations or source mentions
    
    Args:
        answer: The LLM-generated answer
        context: The RAG context that was provided
        
    Returns:
        True if sources appear to be used, False otherwise
    """
    import re
    
    # Check for HTML links (Telegram format)
    if '<a href=' in answer:
        return True
    
    # Check for source references (Persian/Farsi patterns)
    source_patterns = [
        r'منبع',
        r'سند',
        r'مأخذ',
        r'\[منبع',
        r'منابع',
    ]
    
    for pattern in source_patterns:
        if re.search(pattern, answer, re.IGNORECASE):
            return True
    
    # Check if URLs from context appear in answer
    url_pattern = r'https?://[^\s<>"]+'
    context_urls = set(re.findall(url_pattern, context))
    answer_urls = set(re.findall(url_pattern, answer))
    
    if context_urls and answer_urls:
        # If any context URL appears in answer, likely used
        if context_urls.intersection(answer_urls):
            return True
    
    return False


def detect_rag_context_relevance(context: str, answer: str) -> bool:
    """
    Detect if RAG context was relevant and used.
    
    This is a heuristic: if sources are used AND context was provided,
    we consider it relevant and used.
    
    Args:
        context: The RAG context provided
        answer: The LLM answer
        
    Returns:
        True if context appears relevant and used
    """
    # If no context or empty context, not relevant
    if not context or context.strip() == "":
        return False
    
    # Check if sources were used
    sources_used = detect_rag_source_usage(answer, context)
    
    # If sources were used, context was relevant
    return sources_used

