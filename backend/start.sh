#!/bin/bash
# Production startup script for Render

echo "🚀 Starting Mail Bot Backend..."

# Initialize database
echo "📊 Initializing database..."
python init_db.py

# Start the application
echo "🔥 Starting Flask application..."
exec gunicorn --bind 0.0.0.0:$PORT app:app --timeout 120 --workers 2 --access-logfile - --error-logfile -