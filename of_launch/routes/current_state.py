"""Current-state page: what runs in each environment."""

from flask import Blueprint, jsonify, render_template, request

from of_launch.config import clusters
from of_launch.utils.auth import login_required
from of_launch.utils.aws import get_ecs_state

current = Blueprint("current", __name__)


@current.route("/current-state")
@login_required
def current_state():
    available_environments = clusters.environments()
    environment = request.args.get("environment")

    if request.headers.get("Content-Type") == "application/json" or request.args.get("ajax") == "1":
        if not environment:
            return jsonify({"error": "Environment parameter is required"}), 400
        try:
            result, status_code = get_ecs_state(environment)
            if status_code != 200:
                return jsonify({"error": "Failed to fetch ECS state"}), status_code
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({"error": f"Internal server error: {exc}"}), 500

    return render_template(
        "current_state.html", available_environments=available_environments, current_deployments={}
    )
