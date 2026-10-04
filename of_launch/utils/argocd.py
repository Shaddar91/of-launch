"""ArgoCD API client: app status, sync and resource trees per registry cluster, real or mock."""

import logging
import random
import uuid
from datetime import datetime, timedelta

import requests

from of_launch.config import clusters, settings

logger = logging.getLogger(__name__)

_mock_deployments = {}
_sessions = {}


def _get_argocd_session(cluster):
    if cluster not in _sessions:
        session = requests.Session()
        session.headers.update(
            {"Authorization": f"Bearer {clusters.argocd_for(cluster)['token']}", "Content-Type": "application/json"}
        )
        session.verify = True
        _sessions[cluster] = session
    return _sessions[cluster]


def _app_url(cluster, app_name, suffix=""):
    base_url = clusters.argocd_for(cluster)["url"].rstrip("/")
    return f"{base_url}/api/v1/applications/{app_name}{suffix}"


def _get_json(cluster, url, timeout=15):
    resp = _get_argocd_session(cluster).get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _get_real_app_status(app_name, cluster):
    data = _get_json(cluster, _app_url(cluster, app_name))
    sync = data.get("status", {}).get("sync", {})
    health = data.get("status", {}).get("health", {})
    op_state = data.get("status", {}).get("operationState", {})
    source = data.get("spec", {}).get("source", {})
    return {
        "app_name": app_name,
        "sync_status": sync.get("status", "Unknown"),
        "health_status": health.get("status", "Unknown"),
        "revision": sync.get("revision", "")[:8] if sync.get("revision") else "",
        "last_synced": op_state.get("finishedAt") or op_state.get("startedAt"),
        "source": {
            "repo_url": source.get("repoURL", ""),
            "target_revision": source.get("targetRevision", ""),
            "path": source.get("path", ""),
        },
        "mock": False,
    }


def _node_field(node, field):
    ref = node.get("resourceRef", {})
    return node.get(field, ref.get(field, ""))


def _node_info(node):
    return {i.get("name", ""): i.get("value", "") for i in node.get("info", [])}


def _extract_pod_info(node):
    info = _node_info(node)
    restart_str = info.get("Restart Count", "0") or "0"
    return {
        "name": _node_field(node, "name"),
        "namespace": _node_field(node, "namespace"),
        "status": info.get("Status Reason", node.get("health", {}).get("status", "Unknown")),
        "ready": info.get("Containers", "0/0"),
        "restarts": int(restart_str) if restart_str.isdigit() else 0,
        "age": node.get("createdAt", ""),
    }


def _get_real_resource_tree(app_name, cluster):
    nodes = _get_json(cluster, _app_url(cluster, app_name, "/resource-tree")).get("nodes", [])
    pods = [_extract_pod_info(node) for node in nodes if _node_field(node, "kind") == "Pod"]
    running_count = sum(1 for p in pods if p["status"] in ("Running", "Healthy"))
    total_count = len(pods) if pods else 1
    return {
        "app_name": app_name,
        "pods": pods,
        "deployment": {
            "replicas": len(pods),
            "ready_replicas": running_count,
            "updated_replicas": len(pods),
            "strategy": "RollingUpdate",
        },
        "service": {"type": "ClusterIP", "ports": [{"port": 80, "target_port": 8080}]},
        "overall_health": "Healthy" if running_count == total_count else "Progressing",
        "mock": False,
    }


def _cronjob_from_node(node):
    info = _node_info(node)
    active_str = info.get("Active", "0") or "0"
    return {
        "name": _node_field(node, "name"),
        "namespace": _node_field(node, "namespace"),
        "schedule": info.get("Schedule", ""),
        "suspend": info.get("Suspended", "false").lower() == "true",
        "active_jobs": int(active_str) if active_str.isdigit() else 0,
        "last_schedule": info.get("Last Scheduled", ""),
        "last_successful": "",
        "created": node.get("createdAt", ""),
        "image": "",
        "status": node.get("health", {}).get("status", "Unknown"),
        "mock": False,
    }


def _get_real_cronjob_status(env, cluster):
    apps = [entry["app"] for entry in clusters.argocd_apps() if entry["environment"] == env]
    if not apps:
        return {"environment": env, "cronjobs": [], "total": 0, "mock": False,
                "message": f"No ArgoCD app registered for {env}"}
    cronjobs = []
    for app_name in apps:
        nodes = _get_json(cluster, _app_url(cluster, app_name, "/resource-tree")).get("nodes", [])
        cronjobs.extend(_cronjob_from_node(node) for node in nodes if _node_field(node, "kind") == "CronJob")
    return {"environment": env, "cronjobs": cronjobs, "total": len(cronjobs), "mock": False}


def _generate_mock_pods(service_name, count=3):
    statuses = ["Running", "Running", "Running", "Pending", "Running"]
    return [
        {
            "name": f"{service_name}-{uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:5]}",
            "status": random.choice(statuses),
            "ready": "1/1",
            "restarts": random.randint(0, 2),
            "age": f"{random.randint(1, 72)}h",
        }
        for _ in range(count)
    ]


def _mock_cronjobs(env):
    now = datetime.utcnow()
    try:
        names = list(clusters.services_for(env)["eks"]) or ["app"]
    except clusters.RegistryError:
        names = ["app"]
    shapes = (("scheduler", "* * * * *", 1), ("queue-worker", "*/5 * * * *", 0), ("cleanup", "0 2 * * *", 0))
    cronjobs = []
    for index, (suffix, schedule, max_active) in enumerate(shapes):
        base = names[index % len(names)]
        cronjobs.append(
            {
                "name": f"{base}-{suffix}",
                "namespace": f"{env}-{base}",
                "schedule": schedule,
                "suspend": False,
                "active_jobs": random.randint(0, max_active),
                "last_schedule": (now - timedelta(minutes=random.randint(0, 10))).isoformat() + "Z",
                "last_successful": (now - timedelta(minutes=random.randint(1, 15))).isoformat() + "Z",
                "created": (now - timedelta(days=random.randint(5, 30))).isoformat() + "Z",
                "image": f"{base}:master-{uuid.uuid4().hex[:8]}",
                "status": "Active",
            }
        )
    return cronjobs


def _error_result(base, exc):
    return {**base, "error": str(exc), "mock": False}


def get_app_status(app_name, cluster):
    if settings.is_mock_mode():
        status = {
            "app_name": app_name,
            "sync_status": random.choice(["Synced", "OutOfSync", "Synced", "Synced"]),
            "health_status": random.choice(["Healthy", "Progressing", "Healthy", "Healthy"]),
            "revision": uuid.uuid4().hex[:8],
            "last_synced": (datetime.utcnow() - timedelta(minutes=random.randint(1, 120))).isoformat() + "Z",
            "source": {
                "repo_url": f"https://github.com/{settings.GITHUB_OWNER or 'example'}/of-helm",
                "target_revision": "master",
                "path": f"charts/{app_name}",
            },
            "mock": True,
        }
        logger.info(f"[MOCK ARGOCD] get_app_status({app_name}): {status['sync_status']}/{status['health_status']}")
        return status

    base = {"app_name": app_name, "sync_status": "Unknown", "health_status": "Unknown"}
    try:
        result = _get_real_app_status(app_name, cluster)
        logger.info(f"[ARGOCD:{cluster}] get_app_status({app_name}): {result['sync_status']}/{result['health_status']}")
        return result
    except Exception as exc:
        logger.error(f"[ARGOCD:{cluster}] Failed get_app_status({app_name}): {exc}")
        return _error_result(base, exc)


def sync_app(app_name, cluster):
    if settings.is_mock_mode():
        sync_id = uuid.uuid4().hex[:8]
        logger.info(f"[MOCK ARGOCD] sync_app({app_name}): sync_id={sync_id}")
        return {
            "app_name": app_name,
            "cluster": cluster,
            "sync_id": sync_id,
            "status": "SyncStarted",
            "message": f"Sync triggered for {app_name}",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "mock": True,
        }
    try:
        resp = _get_argocd_session(cluster).post(_app_url(cluster, app_name, "/sync"), json={}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        op_state = data.get("status", {}).get("operationState", {})
        sync = data.get("status", {}).get("sync", {})
        logger.info(
            f"[ARGOCD:{cluster}] sync_app({app_name}): sync triggered, revision={sync.get('revision', '')[:8]}"
        )
        return {
            "app_name": app_name,
            "cluster": cluster,
            "sync_id": sync.get("revision", "")[:8],
            "status": op_state.get("phase", "Running"),
            "message": op_state.get("message", f"Sync triggered for {app_name}"),
            "started_at": op_state.get("startedAt", datetime.utcnow().isoformat() + "Z"),
            "mock": False,
        }
    except Exception as exc:
        logger.error(f"[ARGOCD:{cluster}] Failed sync_app({app_name}): {exc}")
        return _error_result({"app_name": app_name, "cluster": cluster, "status": "failed"}, exc)


def get_resource_tree(app_name, cluster):
    if settings.is_mock_mode():
        pods = _generate_mock_pods(app_name)
        running = sum(1 for p in pods if p["status"] == "Running")
        tree = {
            "app_name": app_name,
            "pods": pods,
            "deployment": {
                "replicas": len(pods),
                "ready_replicas": running,
                "updated_replicas": len(pods),
                "strategy": "RollingUpdate",
            },
            "service": {"type": "ClusterIP", "ports": [{"port": 80, "target_port": 8080}]},
            "overall_health": "Healthy" if running == len(pods) else "Progressing",
            "mock": True,
        }
        logger.info(f"[MOCK ARGOCD] get_resource_tree({app_name}): {len(pods)} pods, health={tree['overall_health']}")
        return tree
    try:
        result = _get_real_resource_tree(app_name, cluster)
        logger.info(
            f"[ARGOCD:{cluster}] get_resource_tree({app_name}): {len(result['pods'])} pods, "
            f"health={result['overall_health']}"
        )
        return result
    except Exception as exc:
        logger.error(f"[ARGOCD:{cluster}] Failed get_resource_tree({app_name}): {exc}")
        return _error_result({"app_name": app_name, "pods": [], "overall_health": "Unknown"}, exc)


def track_deployment(deployment_id, app_name, image_tag):
    _mock_deployments[deployment_id] = {
        "deployment_id": deployment_id,
        "app_name": app_name,
        "image_tag": image_tag,
        "status": "in_progress",
        "started_at": datetime.utcnow().isoformat() + "Z",
        "steps": [
            {"step": 1, "action": "git_update", "status": "completed"},
            {"step": 2, "action": "git_push", "status": "completed"},
            {"step": 3, "action": "argocd_sync", "status": "in_progress"},
            {"step": 4, "action": "pod_rollout", "status": "pending"},
        ],
    }
    return _mock_deployments[deployment_id]


def get_deployment_status(deployment_id):
    if deployment_id not in _mock_deployments:
        return {"error": f"Deployment {deployment_id} not found"}
    dep = _mock_deployments[deployment_id]
    pending = [s for s in dep["steps"] if s["status"] == "in_progress"]
    if pending:
        pending[0]["status"] = "completed"
        next_pending = [s for s in dep["steps"] if s["status"] == "pending"]
        if next_pending:
            next_pending[0]["status"] = "in_progress"
        else:
            dep["status"] = "completed"
            dep["completed_at"] = datetime.utcnow().isoformat() + "Z"
    return dep


def list_active_deployments():
    return [d for d in _mock_deployments.values() if d["status"] == "in_progress"]


def get_cronjob_status(env):
    base = {"environment": env, "cronjobs": [], "total": 0}
    try:
        cluster = clusters.cluster_for(env)
    except clusters.RegistryError as exc:
        return _error_result(base, exc)
    if settings.is_mock_mode():
        cronjobs = _mock_cronjobs(env)
        logger.info(f"[MOCK ARGOCD] get_cronjob_status({env}): {len(cronjobs)} cronjobs")
        return {"environment": env, "cronjobs": cronjobs, "total": len(cronjobs), "mock": True}
    try:
        result = _get_real_cronjob_status(env, cluster)
        logger.info(f"[ARGOCD:{cluster}] get_cronjob_status({env}): {result['total']} cronjobs")
        return result
    except Exception as exc:
        logger.error(f"[ARGOCD:{cluster}] Failed get_cronjob_status({env}): {exc}")
        return _error_result(base, exc)
