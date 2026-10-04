"""Deployment status dashboard: ArgoCD and CodeDeploy state, real or mock."""

from flask import Blueprint, jsonify, render_template, request, session

from of_launch.config import clusters, settings
from of_launch.services.dependency_resolver import get_batch_status, list_batch_deployments
from of_launch.utils.argocd import get_app_status, get_cronjob_status, get_resource_tree
from of_launch.utils.argocd import get_deployment_status as get_argocd_deployment_status
from of_launch.utils.argocd import list_active_deployments as list_active_argocd_deployments
from of_launch.utils.auth import login_required
from of_launch.utils.codedeploy import get_deployment_status as get_codedeploy_status
from of_launch.utils.codedeploy import list_active_deployments as list_active_codedeploy_deployments
from of_launch.utils.codedeploy import list_deployment_history

status = Blueprint("status", __name__, url_prefix="/status")


@status.route("/")
@login_required
def status_dashboard():
    return render_template(
        "status.html",
        mock_mode=settings.MOCK_MODE,
        role=session.get("role", settings.ROLE_SHARED_EXECUTOR),
        environments=clusters.environments(),
    )


@status.route("/api/active")
@login_required
def get_active_deployments():
    active = list_active_argocd_deployments() + list_active_codedeploy_deployments()
    return jsonify({"deployments": active, "count": len(active)})


@status.route("/api/deployment/<deployment_id>")
@login_required
def get_single_deployment(deployment_id):
    return jsonify(get_argocd_deployment_status(deployment_id))


@status.route("/api/codedeploy/<deployment_id>")
@login_required
def get_codedeploy_deployment(deployment_id):
    return jsonify(get_codedeploy_status(deployment_id))


@status.route("/api/codedeploy-active")
@login_required
def get_codedeploy_active():
    active = list_active_codedeploy_deployments()
    return jsonify({"deployments": active, "count": len(active)})


@status.route("/api/argocd/<app_name>")
@login_required
def get_argocd_status(app_name):
    cluster = request.args.get("cluster")
    if not cluster:
        try:
            cluster = clusters.cluster_for_app(app_name)
        except clusters.RegistryError as exc:
            return jsonify({"error": str(exc)}), 404
    return jsonify(
        {
            "cluster": cluster,
            "status": get_app_status(app_name, cluster=cluster),
            "resources": get_resource_tree(app_name, cluster=cluster),
        }
    )


@status.route("/api/argocd-apps")
@login_required
def get_argocd_apps():
    names = request.args.getlist("apps")
    if names:
        try:
            entries = [{"app": name, "cluster": clusters.cluster_for_app(name)} for name in names]
        except clusters.RegistryError as exc:
            return jsonify({"error": str(exc)}), 404
    else:
        entries = clusters.argocd_apps()

    apps = []
    for entry in entries:
        app_status = get_app_status(entry["app"], cluster=entry["cluster"])
        app_status["cluster"] = entry["cluster"]
        app_status["environment"] = entry.get("environment", "")
        apps.append(app_status)
    return jsonify({"apps": apps})


@status.route("/api/cronjobs/<env>")
@login_required
def get_cronjob_env_status(env):
    return jsonify(get_cronjob_status(env))


@status.route("/api/codedeploy-history")
@login_required
def get_codedeploy_history():
    app_name = request.args.get("app")
    deploy_group = request.args.get("group")
    if not app_name:
        return jsonify({"error": "app parameter required"}), 400
    max_results = int(request.args.get("limit", 25))
    deployments = list_deployment_history(app_name, deploy_group, max_results=max_results)
    return jsonify(
        {"app_name": app_name, "deploy_group": deploy_group, "deployments": deployments, "count": len(deployments)}
    )


@status.route("/api/batch/<batch_id>")
@login_required
def get_batch(batch_id):
    return jsonify(get_batch_status(batch_id))


@status.route("/api/batches")
@login_required
def get_batches():
    batches = list_batch_deployments()
    return jsonify({"batches": batches, "count": len(batches)})
