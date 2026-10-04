"""Gunicorn entry point: gunicorn --bind 0.0.0.0:5000 wsgi:app."""

from of_launch import create_app
from of_launch.config import settings

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=settings.FLASK_DEBUG)
