#!/bin/sh

# Apply database migrations
echo "Applying database migrations..."
python3 manage.py migrate

# Start the Telegram bot in the background (logs go to container stdout/stderr)
echo "Starting Telegram bot in the background..."
python3 manage.py start_bot &

# Start the Django development server
echo "Starting Django server..."
exec python3 manage.py runserver 0.0.0.0:8014
