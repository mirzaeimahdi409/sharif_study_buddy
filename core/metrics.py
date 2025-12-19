from prometheus_client import Counter, Histogram

# Metrics for the entire AI pipeline (e.g., LangGraph)
ai_pipeline_requests_total = Counter(
    'ai_pipeline_requests_total',
    'Total number of requests to the AI pipeline',
    ['pipeline_name']
)

ai_pipeline_errors_total = Counter(
    'ai_pipeline_errors_total',
    'Total number of errors in the AI pipeline',
    ['pipeline_name']
)

ai_pipeline_duration_seconds = Histogram(
    'ai_pipeline_duration_seconds',
    'Histogram of AI pipeline processing time in seconds',
    ['pipeline_name']
)

# Metrics for the RAG (Retrieval-Augmented Generation) service
rag_requests_total = Counter(
    'rag_requests_total',
    'Total number of requests to the RAG service',
    ['endpoint']
)

rag_errors_total = Counter(
    'rag_errors_total',
    'Total number of errors from the RAG service',
    ['endpoint']
)

rag_duration_seconds = Histogram(
    'rag_duration_seconds',
    'Histogram of RAG service response time in seconds',
    ['endpoint']
)

# Metrics for the Language Model (LLM) service (e.g., OpenRouter)
llm_requests_total = Counter(
    'llm_requests_total',
    'Total number of requests to the LLM',
    ['model_name']
)

llm_errors_total = Counter(
    'llm_errors_total',
    'Total number of errors from the LLM',
    ['model_name']
)

llm_duration_seconds = Histogram(
    'llm_duration_seconds',
    'Histogram of LLM response time in seconds',
    ['model_name']
)

# Metric to count how many LLM invocations used RAG context
llm_rag_usage_total = Counter(
    'llm_rag_usage_total',
    'Counts LLM invocations with and without RAG context',
    ['status']  # 'rag_used' or 'no_rag'
)

# Metric to track if LLM cited RAG sources in its answer
llm_rag_context_usage_total = Counter(
    'llm_rag_context_usage_total',
    'Counts if the LLM answer cited/used the RAG context provided',
    ['status']  # 'cited' or 'not_cited'
)
