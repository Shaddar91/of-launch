"""Blueprint registry."""

from .admin import admin
from .api import api
from .auth import auth
from .current_state import current
from .db import db
from .history import history
from .main import main
from .status import status

all_blueprints = [auth, history, current, main, db, api, status, admin]
