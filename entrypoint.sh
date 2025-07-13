#!/bin/sh

echo "⏳ Waiting for DB to be ready..."
sleep 2

echo "⚙️ Running Alembic migrations..."
alembic upgrade head

echo "🚀 Starting Gunicorn server..."
exec gunicorn src.main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
