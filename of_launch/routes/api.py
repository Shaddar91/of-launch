"""AJAX API for the deploy dashboard: environments, services, artifacts, deploys, batches."""

import logging

from flask import Blueprint, jsonify, request, session

from of_launch.config import clusters, settings
from of_launch.services.artifact_browser import (
    artifact_display_name,
    list_cron_artifacts,
    list_ecr_images,
    list_frontend_artifacts,
    list_services_for_env,
    list_worker_artifacts,
)
from of_launch.services.cron_deployer import deploy_cron
from of_launch.services.dependency_resolver import get_batch_status, orchestrate_deploy, resolve_dependencies
from of_launch.services.eks_deployer import deploy_eks
from of_launch.services.frontend_deployer import deploy_frontend
from of_launch.services.worker_deployer import deploy_worker
from of_launch.utils.auth import login_required
from of_launch.utils.db import write_deployment_record
from of_launch.utils.slack import send_deploy_notification

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")


@api.after_request
def _no_cache_artifacts(response):
    if request.path.startswith("/api/artifacts/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def _check_deploy_permission(env):
    role = session.get("role", settings.ROLE_SHARED_EXECUTOR)
    if not settings.can_deploy_to(role, env):
        return jsonify({"error": f'Role "{role}" is not allowed to deploy to "{env}".'}), 403
    return None


def _record_and_notify(env, service_name, version, deploy_type, user, result):
    status = result.get("status", "completed")
    write_deployment_record(
        user=user,
        environment=env,
        service_name=service_name,
        artifact_version=version,
        deployment_type=deploy_type,
        status=status,
    )
    send_deploy_notification(
        env=env,
        service_name=service_name,
        deploy_type=deploy_type,
        version=version,
        user=user,
        status=status,
        extra={"deployment_id": result.get("deployment_id", ""), "commit_sha": result.get("git_commit", "")},
    )


@api.route("/environments")
@login_required
def get_environments():
    role = session.get("role", settings.ROLE_SHARED_EXECUTOR)
    envs = {}
    for env in clusters.environments():
        if settings.can_deploy_to(role, env):
            envs[env] = {"cluster": clusters.cluster_for(env)}
    return jsonify(envs)


@api.route("/services")
@login_required
def get_services():
    env = request.args.get("env")
    if not env:
        return jsonify({"error": "env parameter required"}), 400
    result = list_services_for_env(env)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


def _artifact_listing(lister, name_param):
    env = request.args.get("env")
    name = request.args.get(name_param)
    if not env or not name:
        return jsonify({"error": f"env and {name_param} parameters required"}), 400
    return jsonify(lister(env, name))


@api.route("/artifacts/frontend")
@login_required
def get_frontend_artifacts():
    return _artifact_listing(list_frontend_artifacts, "app")


@api.route("/artifacts/ecr")
@login_required
def get_ecr_artifacts():
    return _artifact_listing(list_ecr_images, "service")


@api.route("/artifacts/worker")
@login_required
def get_worker_artifacts():
    return _artifact_listing(list_worker_artifacts, "service")


@api.route("/artifacts/cron")
@login_required
def get_cron_artifacts():
    return _artifact_listing(list_cron_artifacts, "service")


def _single_deploy(deployer, name_key, version_key, deploy_type):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    env = data.get("env")
    name = data.get(name_key)
    version = data.get(version_key)
    if not all([env, name, version]):
        return jsonify({"error": f"env, {name_key}, and {version_key} required"}), 400

    denied = _check_deploy_permission(env)
    if denied:
        return denied

    user = session.get("username", "system")
    result = deployer(env, name, version, user=user)
    shown = version if deploy_type == "eks" else artifact_display_name(version)
    _record_and_notify(env, name, shown, deploy_type, user, result)
    return jsonify(result)


@api.route("/deploy/frontend", methods=["POST"])
@login_required
def trigger_frontend_deploy():
    return _single_deploy(deploy_frontend, "app", "artifact_key", "frontend")


@api.route("/deploy/worker", methods=["POST"])
@login_required
def trigger_worker_deploy():
    return _single_deploy(deploy_worker, "service", "artifact_key", "worker")


@api.route("/deploy/eks", methods=["POST"])
@login_required
def trigger_eks_deploy():
    return _single_deploy(deploy_eks, "service", "image_tag", "eks")


@api.route("/deploy/cron", methods=["POST"])
@login_required
def trigger_cron_deploy():
    return _single_deploy(deploy_cron, "service", "artifact_key", "cron")


@api.route("/dependencies")
@login_required
def get_dependencies():
    env = request.args.get("env")
    services_param = request.args.get("services", "")
    if not env or not services_param:
        return jsonify({"auto_selected": [], "deploy_order": [], "warnings": []})
    selected = [item.strip() for item in services_param.split(",") if item.strip()]
    return jsonify(resolve_dependencies(env, selected))


def _flatten_batch(batch_result):
    summary = batch_result.get("summary", {})
    results = []
    for entry in batch_result.get("results", []):
        inner = dict(entry.get("result", {}))
        inner["deployment_type"] = entry.get("deploy_type", "")
        inner["service_name"] = entry.get("service", "")
        results.append(inner)
    return {
        "batch_status": batch_result.get("status", "in_progress"),
        "batch_id": batch_result.get("batch_id", ""),
        "environment": batch_result.get("environment", ""),
        "cluster": batch_result.get("cluster", ""),
        "total": summary.get("total", 0),
        "succeeded": summary.get("succeeded", 0),
        "failed": summary.get("failed", 0),
        "skipped": 0,
        "deploy_order": batch_result.get("deploy_order", []),
        "results": results,
        "mock": batch_result.get("mock", False),
        "error": batch_result.get("error"),
    }


@api.route("/deploy/batch", methods=["POST"])
@login_required
def trigger_batch_deploy():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    env = data.get("env")
    services = data.get("services", [])
    if not env or not services:
        return jsonify({"error": "env and services list required"}), 400

    denied = _check_deploy_permission(env)
    if denied:
        return denied

    user = session.get("username", "system")
    return jsonify(_flatten_batch(orchestrate_deploy(env, services, user=user))), 202


@api.route("/deploy/status")
@login_required
def get_deploy_status():
    batch_id = request.args.get("batch_id")
    if not batch_id:
        return jsonify({"error": "batch_id query param required"}), 400
    batch_result = get_batch_status(batch_id)
    if "not found" in batch_result.get("error", ""):
        return jsonify({"error": batch_result["error"]}), 404
    return jsonify(_flatten_batch(batch_result))
