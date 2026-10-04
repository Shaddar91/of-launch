"""OF Launch: the deployment dashboard for the OF cluster."""

from flask import Flask

from of_launch.config import settings
from of_launch.routes import all_blueprints


def create_app(config=None):
    app = Flask(__name__)
    app.secret_key = settings.APP_SECRET_KEY
    if config:
        app.config.update(config)
    for blueprint in all_blueprints:
        app.register_blueprint(blueprint)
    return app
