from prometheus_client import Counter, Gauge

# Counter for the total number of messages received
messages_received = Counter(
    'telegram_bot_messages_received_total',
    'Total number of messages received by the bot'
)

# Counter for commands, labeled by command name
commands_processed = Counter(
    'telegram_bot_commands_processed_total',
    'Total number of commands processed by the bot',
    ['command']
)

# Counter for callback queries, labeled by callback data prefix
callbacks_processed = Counter(
    'telegram_bot_callbacks_processed_total',
    'Total number of callback queries processed',
    ['prefix']
)

# Counter for errors, labeled by the handler where the error occurred
errors_total = Counter(
    'telegram_bot_errors_total',
    'Total number of errors encountered in handlers',
    ['handler']
)

# Gauge for active users (e.g., users who sent a message in the last 24 hours)
# This would require a separate mechanism to track and decrement.
# For now, we can use a gauge for active chat sessions if the bot has a session concept.
# Let's stick to counters for now as they are simpler to implement without a session manager.

# Counter for new users
new_users_total = Counter(
    'telegram_bot_new_users_total',
    'Total number of new users interacting with the bot'
)

# Counter for messages sent by the bot
messages_sent_total = Counter(
    'telegram_bot_messages_sent_total',
    'Total number of messages sent by the bot'
)

# Gauge for active users in the last 24 hours
active_users_24h = Gauge(
    'telegram_bot_active_users_24h',
    'Number of unique users who sent a message in the last 24 hours'
)
