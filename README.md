# Sharif University Intelligent Student Assistant

An intelligent Telegram bot designed to help students at Sharif University of Technology. The bot leverages advanced AI technologies including LangGraph, LangChain, RAG (Retrieval Augmented Generation), and OpenRouter to provide accurate, document-based answers to student queries.

## Features

- 🤖 **Telegram Bot**: Simple and user-friendly interface for students
- 🧠 **Advanced AI**: Powered by LangGraph and LangChain for intelligent processing
- 📚 **RAG (Retrieval Augmented Generation)**: Retrieves information from university documents
- 🔍 **Smart Search**: Uses RAG microservice to find relevant information
- 👥 **Access Management**: Separate admin and regular user access levels
- ⚡ **Background Processing**: Uses Celery and Redis for heavy operations
- 📊 **Admin Panel**: Content and document management through Django Admin
- 📡 **Channel Monitoring**: Automatic ingestion of messages from monitored Telegram channels

## Architecture

The project follows a clean, modular architecture:

```
shrif-bot/
├── core/                           # Core application
│   ├── models.py                   # Data models (UserProfile, ChatSession, ChatMessage, KnowledgeDocument)
│   ├── admin.py                    # Django admin panel configuration
│   ├── config.py                   # Centralized configuration management
│   ├── exceptions.py               # Custom exception classes
│   ├── logging_config.py           # Unified logging configuration
│   ├── messages.py                 # Message templates and constants
│   ├── services/                   # AI services
│   │   ├── langgraph_pipeline.py   # Main LangGraph pipeline
│   │   ├── openrouter.py           # OpenRouter LLM client
│   │   └── rag_client.py           # RAG microservice client
│   ├── tasks.py                    # Celery tasks for background processing
│   ├── signals.py                  # Django signal handlers
│   └── tests/                      # Test suite
│       ├── conftest.py             # Pytest fixtures
│       └── test_models.py          # Model tests
├── bot/                            # Telegram bot application
│   ├── app.py                      # Main bot application class
│   ├── constants.py                # Bot constants
│   ├── keyboards.py                # Keyboard markup definitions
│   ├── utils.py                    # Utility functions
│   ├── handlers/                   # Bot handlers (modular structure)
│   │   ├── admin_handlers.py       # Admin command handlers
│   │   ├── user_handlers.py        # Regular user handlers
│   │   └── callback_handlers.py    # Callback query handlers
│   └── management/commands/
│       └── start_bot.py            # Django management command to start bot
├── monitoring/                     # Channel monitoring application
│   ├── models.py                   # MonitoredChannel, IngestedTelegramMessage
│   ├── tasks.py                    # Celery task for harvesting channels
│   ├── signals.py                  # Signal handlers for cleanup
│   └── admin.py                    # Admin interface
└── sharif_assistant/               # Django project settings
    ├── settings.py                 # Django settings
    ├── celery.py                   # Celery configuration
    └── urls.py                     # URL configuration
```

## Key Design Principles

- **Modular Structure**: Handlers, services, and utilities are separated into focused modules
- **Unified Configuration**: All configuration accessed through `core/config.py`
- **Consistent Error Handling**: Custom exceptions in `core/exceptions.py`
- **Centralized Logging**: Unified logging setup via `core/logging_config.py`
- **Type Hints**: Full type annotations for better code clarity
- **Documentation**: Comprehensive docstrings throughout the codebase

## Prerequisites

- Python 3.12+
- PostgreSQL
- Redis
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- OpenRouter API Key
- Access to RAG microservice
- Telegram API credentials (for channel monitoring)

## Installation and Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd shrif-bot
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Django
SECRET_KEY=your-secret-key-here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_API_ID=your-telegram-api-id
TELEGRAM_API_HASH=your-telegram-api-hash
ADMIN_TELEGRAM_IDS=123456789,987654321  # Comma-separated admin Telegram IDs
TELEGRAM_DEDUP_BY_CONTENT=False  # Enable content-based deduplication

# AI Services
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openrouter/auto  # Optional, defaults to openrouter/auto
LLM_TEMPERATURE=0.2  # Optional, defaults to 0.2

# RAG Service
RAG_API_URL=http://45.67.139.109:8033/api
RAG_API_KEY=your-rag-api-key  # Optional
RAG_USER_ID=5  # Optional, defaults to 5
RAG_MICROSERVICE=telegram_bot  # Optional, defaults to telegram_bot

# Chat Configuration
CHAT_MAX_HISTORY=8  # Optional, defaults to 8
RAG_TOP_K=5  # Optional, defaults to 5

# Database
POSTGRES_DB=sharif_assistant_db
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=  # Optional

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Production (for webhook mode)
WEBHOOK_DOMAIN=your-domain.com  # Required for production webhook mode
DJANGO_ENV=development  # Set to 'production' for webhook mode
```

### 5. Setup Database

```bash
python manage.py migrate
```

### 6. Create Admin User

```bash
python manage.py createsuperuser
```

### 7. Setup Telegram Session (for Channel Monitoring)

If you want to enable channel monitoring, create a Telegram session:

```bash
python create_telegram_session.py
```

Follow the prompts to authenticate with your Telegram account. The session file will be saved in the `sessions/` directory.

### 8. Start Redis

```bash
redis-server
```

Or using Docker:

```bash
docker run -d -p 6379:6379 redis:latest
```

### 9. Start Celery Worker

For background task processing (document ingestion, reprocessing):

```bash
celery -A sharif_assistant worker --loglevel=info
```

### 10. Start Celery Beat (for Scheduled Tasks)

For periodic channel harvesting:

```bash
celery -A sharif_assistant beat --loglevel=info
```

### 11. Start the Telegram Bot

**Development Mode (Polling):**

```bash
python manage.py start_bot
```

**Production Mode (Webhook):**

Set `DJANGO_ENV=production` and `WEBHOOK_DOMAIN` in your `.env` file, then:

```bash
python manage.py start_bot
```

The bot will automatically use webhook mode in production.

## Usage

### For Regular Users

1. Find the bot on Telegram
2. Send `/start` command
3. Ask your question
4. Receive an answer based on university documents

**Available Commands:**

- `/start` - Start a conversation
- `/help` - Show help message
- `/reset` - Start a new conversation (clears context)

### For Admins

Admins can access the bot through two interfaces:

#### Telegram Bot Admin Panel

1. Send `/admin` command to the bot
2. Use the interactive menu to:
   - Manage knowledge documents (add, list, delete)
   - Manage monitored channels
   - View bot statistics
   - Push documents to RAG
   - Reprocess documents

#### Django Admin Panel

1. Navigate to `/admin` in your browser
2. Log in with your superuser credentials
3. Manage:
   - **Knowledge Documents**: Add, edit, delete documents
   - **User Profiles**: View user information
   - **Chat Sessions**: View conversation history
   - **Chat Messages**: View individual messages
   - **Monitored Channels**: Manage channels for automatic ingestion
   - **Ingested Messages**: View ingested Telegram messages

## Advanced Configuration

### Environment Variables

| Variable                    | Description                                | Default           |
| --------------------------- | ------------------------------------------ | ----------------- |
| `CHAT_MAX_HISTORY`          | Maximum number of messages in chat history | `8`               |
| `RAG_TOP_K`                 | Number of RAG results to retrieve          | `5`               |
| `LLM_TEMPERATURE`           | LLM temperature (creativity)               | `0.2`             |
| `OPENROUTER_MODEL`          | OpenRouter model to use                    | `openrouter/auto` |
| `RETRIEVAL_SCORE_THRESHOLD` | Minimum score for RAG results              | `0.25`            |
| `RAG_TIMEOUT`               | RAG API timeout in seconds                 | `30`              |
| `TELEGRAM_DEDUP_BY_CONTENT` | Enable content-based deduplication         | `False`           |

### RAG Service Configuration

The RAG microservice must be accessible at the URL specified in `RAG_API_URL`. The API should support the following endpoints:

- `POST /knowledge/search/` - Search for documents
- `POST /knowledge/documents/` - Ingest text document
- `POST /knowledge/documents/ingest-url/` - Ingest document from URL
- `POST /knowledge/documents/ingest-channel-message/` - Ingest Telegram channel message
- `POST /knowledge/documents/{id}/reprocess/` - Reprocess a document
- `DELETE /knowledge/documents/{id}/` - Delete a document

## Development

### Code Structure

- **Services**: AI and RAG logic in `core/services/`
- **Models**: Data models in `core/models.py`
- **Admin**: Admin configuration in `core/admin.py` and `monitoring/admin.py`
- **Tasks**: Celery tasks in `core/tasks.py` and `monitoring/tasks.py`
- **Bot Handlers**: Modular handlers in `bot/handlers/`
- **Configuration**: Centralized config in `core/config.py`
- **Exceptions**: Custom exceptions in `core/exceptions.py`
- **Logging**: Logging setup in `core/logging_config.py`

### Adding New Features

1. **Add a new model:**

   - Define the model in `core/models.py` or appropriate app
   - Create migration: `python manage.py makemigrations`
   - Apply migration: `python manage.py migrate`

2. **Add a new bot command:**

   - Create handler in `bot/handlers/user_handlers.py` or `bot/handlers/admin_handlers.py`
   - Register in `bot/app.py` `setup_handlers()` method

3. **Add a new Celery task:**

   - Add task function in `core/tasks.py` or appropriate app's `tasks.py`
   - Use `@shared_task` decorator
   - Task will be auto-discovered by Celery

4. **Add a new service:**
   - Create service class in `core/services/`
   - Use `core/config.py` for configuration
   - Use `core/exceptions.py` for error handling

### Running Tests

```bash
pytest
```

Or with coverage:

```bash
pytest --cov=core --cov=bot --cov=monitoring
```

### Code Quality

The project follows Python best practices:

- Type hints throughout
- Comprehensive docstrings
- Modular architecture
- Separation of concerns
- Consistent error handling

## Docker Deployment

### Using Docker Compose

```bash
docker-compose up -d
```

This will start:

- Application container (Django + Bot)
- Celery worker container
- Celery beat container

Make sure to set all required environment variables in your `.env` file.

## Troubleshooting

### Bot Not Starting

- Verify `TELEGRAM_BOT_TOKEN` is correctly set
- Check logs for error messages
- Ensure the bot process is running
- For webhook mode, verify `WEBHOOK_DOMAIN` is set

### RAG Service Errors

- Verify `RAG_API_URL` is correct and accessible
- Check that the RAG microservice is running
- Review Celery worker logs for background task errors
- Verify `RAG_API_KEY` if authentication is required

### LLM Errors

- Verify `OPENROUTER_API_KEY` is correct
- Check OpenRouter account balance
- Review logs for detailed error messages
- Verify model name in `OPENROUTER_MODEL` is valid

### Channel Monitoring Not Working

- Ensure Telegram session is created (`create_telegram_session.py`)
- Verify `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are set
- Check Celery beat is running for scheduled harvesting
- Review Celery worker logs for task execution errors

### Database Issues

- Verify PostgreSQL is running
- Check database connection settings
- Run migrations: `python manage.py migrate`
- Check database logs for connection errors

## Project Status

This project is actively maintained and follows modern Python development practices. The codebase is modular, well-documented, and designed for maintainability.

## License

This project is developed for use at Sharif University of Technology.

## Support

For questions and issues, please create an issue in the repository or contact the development team.
