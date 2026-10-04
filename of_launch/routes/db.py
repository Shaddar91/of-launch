"""Database status endpoint."""

from datetime import datetime

from flask import Blueprint, jsonify

from of_launch.utils.db import check_db_connection

db = Blueprint("db-status", __name__)


@db.route("/db-status")
def db_status():
    is_connected, message = check_db_connection()
    return jsonify(
        {"connected": is_connected, "message": message, "timestamp": datetime.now().isoformat()}
    ), (200 if is_connected else 500)
