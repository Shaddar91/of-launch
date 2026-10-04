"""Login guard for pages and JSON endpoints."""

from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for


def _is_api_request():
    if request.path.startswith("/api/") or "/api/" in request.path:
        return True
    if request.headers.get("Accept", "").startswith("application/json"):
        return True
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if _is_api_request():
                return jsonify({"error": "Authentication required"}), 401
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))
        if "role" not in session:
            session.clear()
            if _is_api_request():
                return jsonify({"error": "Session expired"}), 401
            flash("Session expired. Please log in again.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function
