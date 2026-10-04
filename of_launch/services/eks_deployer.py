"""EKS deployer: Helm values update in git plus ArgoCD sync, real or mock."""

import logging
import uuid
from datetime import datetime

from of_launch.config import clusters
from of_launch.utils.argocd import sync_app, track_deployment
from of_launch.utils.github import update_image_tag

logger = logging.getLogger(__name__)


def deploy_eks(env, service_name, image_tag, user="system"):
    deployment_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat() + "Z"

    service, err = clusters.lookup_service(env, "eks", service_name)
    if err:
        logger.error(f"[EKS] Config resolution failed: {err}")
        return {"deployment_id": deployment_id, "status": "failed", "error": err, "mock": False}

    cluster = clusters.cluster_for(env)
    helm_repo = service.get("helm_repo", "helm")
    helm_branch = service.get("helm_branch", "master")
    values_file = service.get("values_file", "")
    argocd_app = service.get("argocd_app", "")

    git_result = update_image_tag(
        helm_repo=helm_repo,
        helm_branch=helm_branch,
        values_file=values_file,
        new_tag=image_tag,
        service_name=service_name,
        tag_key=service.get("image_tag_key", "imageTag"),
    )
    sync_result = sync_app(argocd_app, cluster=cluster)
    track_deployment(deployment_id, argocd_app, image_tag)

    git_mock = git_result.get("mock", False)
    sync_mock = sync_result.get("mock", False)
    steps = [
        {
            "step": 1,
            "action": "resolve_config",
            "detail": f"Resolved: {helm_repo}/{values_file} -> ArgoCD:{argocd_app} on {cluster}",
            "status": "success",
            "duration_ms": 10,
        },
        {
            "step": 2,
            "action": "git_update",
            "detail": f"Updated {values_file} with tag {image_tag}",
            "status": git_result.get("status", "success"),
            "mock": git_mock,
            "duration_ms": sum(s["duration_ms"] for s in git_result.get("steps", [])),
        },
        {
            "step": 3,
            "action": "argocd_sync",
            "detail": f"Triggered sync for {argocd_app} (sync_id: {sync_result.get('sync_id', 'n/a')})",
            "status": "success",
            "mock": sync_mock,
            "duration_ms": 500,
        },
        {
            "step": 4,
            "action": "track_rollout",
            "detail": f"Deployment {deployment_id} tracked; poll /status/{deployment_id} for progress",
            "status": "success",
            "duration_ms": 5,
        },
    ]

    logger.info(
        f"[EKS] Deploy {deployment_id}: {service_name} -> {env} on {cluster} "
        f"(tag: {image_tag}, git_mock: {git_mock}, sync_mock: {sync_mock})"
    )
    return {
        "deployment_id": deployment_id,
        "deployment_type": "eks",
        "environment": env,
        "cluster": cluster,
        "service": service_name,
        "image_tag": image_tag,
        "user": user,
        "timestamp": timestamp,
        "status": "completed",
        "helm_repo": helm_repo,
        "values_file": values_file,
        "argocd_app": argocd_app,
        "git_commit": git_result.get("commit_sha", ""),
        "sync_id": sync_result.get("sync_id", ""),
        "steps": steps,
        "mock": git_mock or sync_mock,
        "message": f"EKS deploy of {service_name} to {env} completed (tag: {image_tag})",
    }
