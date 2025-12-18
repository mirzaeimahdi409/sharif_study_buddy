#!/bin/sh

# Apply database migrations
echo "Applying database migrations..."
python3 manage.py migrate

# Start the Django development server
# In production mode, the bot starts automatically via BotConfig.ready()
echo "Starting Django server..."
exec python3 manage.py runserver 0.0.0.0:8014
