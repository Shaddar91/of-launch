#!/bin/bash
# Container entry point: config check, database seed, then gunicorn (or the Flask dev server with FLASK_DEBUG=true).
set -e

python -m of_launch.cli check-config
python -m of_launch.cli seed-users || echo "WARN: seeding incomplete, the app will start anyway"

if [ "${FLASK_DEBUG}" = "true" ]; then
    echo "Starting Flask dev server (debug mode)..."
    exec python wsgi.py
fi

WORKERS=${GUNICORN_WORKERS:-2}
echo "Starting gunicorn with ${WORKERS} workers..."
exec gunicorn --bind 0.0.0.0:5000 wsgi:app \
    --workers "${WORKERS}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
