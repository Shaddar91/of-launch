"""Admin routes: user management, admin role only."""

from flask import Blueprint, jsonify, render_template, request, session

from of_launch.config import settings
from of_launch.utils.auth import login_required
from of_launch.utils.db import create_user, delete_user, list_users, update_user_password, update_user_role

admin = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    if session.get("role") != settings.ROLE_ADMIN:
        return jsonify({"error": "Admin access required"}), 403
    return None


def _invalid_role(role):
    return jsonify({"error": f'Invalid role. Must be one of: {", ".join(settings.VALID_ROLES)}'}), 400


@admin.route("/users")
@login_required
def users_page():
    denied = _require_admin()
    if denied:
        return denied
    return render_template(
        "admin_users.html",
        username=session.get("username"),
        role=session.get("role"),
        valid_roles=settings.VALID_ROLES,
    )


@admin.route("/api/users")
@login_required
def api_list_users():
    denied = _require_admin()
    if denied:
        return denied
    ok, users, msg = list_users()
    if not ok:
        return jsonify({"error": msg}), 500
    for user in users:
        user["created_at"] = str(user["created_at"]) if user["created_at"] else None
        user["last_login"] = str(user["last_login"]) if user["last_login"] else None
    return jsonify({"users": users})


@admin.route("/api/users", methods=["POST"])
@login_required
def api_create_user():
    denied = _require_admin()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", settings.ROLE_SHARED_EXECUTOR)
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if role not in settings.VALID_ROLES:
        return _invalid_role(role)
    ok, msg = create_user(username, password, role=role)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})


@admin.route("/api/users/<username>", methods=["DELETE"])
@login_required
def api_delete_user(username):
    denied = _require_admin()
    if denied:
        return denied
    if username == session.get("username"):
        return jsonify({"error": "Cannot delete your own account"}), 400
    ok, msg = delete_user(username)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})


@admin.route("/api/users/<username>/password", methods=["PUT"])
@login_required
def api_reset_password(username):
    denied = _require_admin()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not data or not data.get("password"):
        return jsonify({"error": "Password required"}), 400
    ok, msg = update_user_password(username, data["password"])
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})


@admin.route("/api/users/<username>/role", methods=["PUT"])
@login_required
def api_change_role(username):
    denied = _require_admin()
    if denied:
        return denied
    data = request.get_json(silent=True)
    if not data or not data.get("role"):
        return jsonify({"error": "Role required"}), 400
    new_role = data["role"]
    if new_role not in settings.VALID_ROLES:
        return _invalid_role(new_role)
    ok, msg = update_user_role(username, new_role)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg})
