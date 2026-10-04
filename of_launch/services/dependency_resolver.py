"""Dependency resolver: auto-selects related services and runs sequential batch deploys."""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from of_launch.config import clusters, settings
from of_launch.services.artifact_browser import artifact_display_name
from of_launch.services.cron_deployer import deploy_cron
from of_launch.services.eks_deployer import deploy_eks
from of_launch.services.frontend_deployer import deploy_frontend
from of_launch.services.worker_deployer import deploy_worker
from of_launch.utils.db import write_deployment_record
from of_launch.utils.slack import send_batch_notification, send_deploy_notification

logger = logging.getLogger(__name__)

TYPE_ORDER = {"frontend": 0, "eks": 1, "worker": 2, "cron": 3}
_DEPLOYERS = {"frontend": deploy_frontend, "eks": deploy_eks, "worker": deploy_worker, "cron": deploy_cron}
_EMPTY = {"auto_selected": [], "deploy_order": [], "warnings": []}
_batch_store = {}


def _store_dir():
    return Path(settings.BATCH_STORE_DIR)


def _save_batch(batch_id, data):
    _store_dir().mkdir(parents=True, exist_ok=True)
    path = _store_dir() / f"{batch_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, default=str))
    tmp.replace(path)
    _batch_store[batch_id] = data


def _load_batch(batch_id):
    path = _store_dir() / f"{batch_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _available_services(env):
    try:
        groups = clusters.services_for(env)
    except clusters.RegistryError:
        return {}
    return {
        name: {"deploy_type": deploy_type, "display_name": config.get("display_name", name)}
        for deploy_type, services in groups.items()
        for name, config in services.items()
    }


def resolve_dependencies(env, selected_services):
    rules = clusters.dependencies().get("backend_deploy", {})
    if not rules:
        return dict(_EMPTY)

    always = rules.get("always", [])
    worker_envs = rules.get("worker_environments", [])
    cron_envs = rules.get("cron_environments", [])
    available = _available_services(env)
    selected = set(selected_services)

    bundle = set(always)
    if env in worker_envs:
        bundle |= {name for name, info in available.items() if info["deploy_type"] == "worker"}
    if env in cron_envs:
        bundle |= {name for name, info in available.items() if info["deploy_type"] == "cron"}
    if not (selected & bundle):
        return dict(_EMPTY)

    auto_selected = []

    def _add(name, reason):
        if name in selected or name not in available or any(a["name"] == name for a in auto_selected):
            return
        auto_selected.append(
            {
                "name": name,
                "deploy_type": available[name]["deploy_type"],
                "display_name": available[name]["display_name"],
                "reason": reason,
            }
        )

    for name in always:
        _add(name, "Backend code dependency: same codebase")
    if env in worker_envs:
        for name, info in available.items():
            if info["deploy_type"] == "worker":
                _add(name, f"Worker EC2 required for {env}")
    if env in cron_envs:
        for name, info in available.items():
            if info["deploy_type"] == "cron":
                _add(name, f"Cron jobs required for {env}")

    all_types = {available[name]["deploy_type"] for name in selected if name in available}
    all_types |= {entry["deploy_type"] for entry in auto_selected}
    deploy_order = sorted(all_types, key=lambda t: TYPE_ORDER.get(t, 99))

    logger.info(
        f"[DEPENDENCY] Resolved {len(auto_selected)} auto-selected services for {env}. "
        f"Deploy order: {deploy_order}"
    )
    return {"auto_selected": auto_selected, "deploy_order": deploy_order, "warnings": []}


def sort_by_deploy_order(services_with_types):
    return sorted(services_with_types, key=lambda x: TYPE_ORDER.get(x.get("deploy_type", ""), 99))


def _cluster_name(env):
    try:
        return clusters.cluster_for(env)
    except clusters.RegistryError:
        return ""


def orchestrate_deploy(env, services, user="system"):
    batch_id = f"batch-{str(uuid.uuid4())[:8]}"
    timestamp = datetime.utcnow().isoformat() + "Z"
    initial = {
        "batch_id": batch_id,
        "environment": env,
        "cluster": _cluster_name(env),
        "user": user,
        "timestamp": timestamp,
        "results": [],
        "summary": {"total": len(services), "succeeded": 0, "failed": 0},
        "status": "in_progress",
        "deploy_order": list(dict.fromkeys(s.get("deploy_type", "") for s in services)),
        "mock": False,
    }
    _save_batch(batch_id, initial)
    threading.Thread(
        target=_orchestrate_thread_target, args=(batch_id, env, services, user, timestamp), daemon=True
    ).start()
    logger.info(f"[ORCHESTRATE] Batch {batch_id} dispatched; deploy running in background thread")
    return initial


def _orchestrate_thread_target(batch_id, env, services, user, timestamp):
    try:
        _run_orchestrate_deploy_impl(batch_id, env, services, user, timestamp)
    except Exception as exc:
        logger.exception(f"[ORCHESTRATE] {batch_id}: thread crashed")
        crash_state = _load_batch(batch_id) or {"batch_id": batch_id}
        crash_state["status"] = "failed"
        crash_state["error"] = f"Orchestration crashed: {exc}"
        _save_batch(batch_id, crash_state)


def _deploy_one(batch_id, env, svc, user):
    name = svc.get("name")
    deploy_type = svc.get("deploy_type")
    version = svc.get("version", "")
    source = svc.get("source", "user")
    entry = {"service": name, "deploy_type": deploy_type, "source": source}

    deployer = _DEPLOYERS.get(deploy_type)
    try:
        if deployer is None:
            result = {"status": "skipped", "message": f"Unknown type: {deploy_type}"}
        else:
            result = deployer(env, name, version, user=user)
    except Exception as exc:
        logger.error(f"[ORCHESTRATE] {batch_id}: {name} ({deploy_type}) FAILED: {exc}")
        return {**entry, "status": "failed", "result": {"status": "failed", "error": str(exc)}}

    svc_status = result.get("status", "completed")
    write_deployment_record(
        user=user,
        environment=env,
        service_name=name,
        artifact_version=artifact_display_name(version),
        deployment_type=deploy_type,
        status=svc_status,
    )
    send_deploy_notification(
        env=env,
        service_name=name,
        deploy_type=deploy_type,
        version=version,
        user=user,
        status=svc_status,
        extra={"deployment_id": result.get("deployment_id", ""), "commit_sha": result.get("git_commit", "")},
    )
    logger.info(f"[ORCHESTRATE] {batch_id}: {name} ({deploy_type}) -> {svc_status}")
    return {**entry, "status": svc_status, "result": result}


def _batch_state(batch_id, env, user, timestamp, results, deploy_order, status, error=None):
    succeeded = sum(1 for r in results if r["status"] != "failed")
    failed = len(results) - succeeded
    state = {
        "batch_id": batch_id,
        "environment": env,
        "cluster": _cluster_name(env),
        "user": user,
        "timestamp": timestamp,
        "results": results,
        "summary": {"total": len(results), "succeeded": succeeded, "failed": failed},
        "status": status,
        "deploy_order": deploy_order,
        "mock": any(r.get("result", {}).get("mock", False) for r in results),
    }
    if error:
        state["error"] = error
    return state


def _run_orchestrate_deploy_impl(batch_id, env, services, user, timestamp):
    ordered = sort_by_deploy_order(services)
    results = []
    logger.info(
        f"[ORCHESTRATE] Batch {batch_id}: deploying {len(ordered)} services to {env} "
        f"(order: {[s['deploy_type'] for s in ordered]})"
    )

    first_name = clusters.dependencies().get("backend_deploy", {}).get("deploy_first")
    first = next((s for s in ordered if first_name and s.get("name") == first_name), None)
    if first is not None:
        ordered.remove(first)
        send_deploy_notification(
            env=env,
            service_name=first_name,
            deploy_type=first.get("deploy_type", ""),
            version=first.get("version", ""),
            user=user,
            status="in_progress",
        )
        logger.info(f"[ORCHESTRATE] {batch_id}: {first_name} first, then a settle window")
        results.append(_deploy_one(batch_id, env, first, user))
        if results[-1]["status"] == "failed":
            logger.error(f"[ORCHESTRATE] {batch_id}: {first_name} FAILED, aborting {len(ordered)} services")
            state = _batch_state(
                batch_id, env, user, timestamp, results, [first.get("deploy_type", "")], "failed",
                error=f"{first_name} deploy failed; remaining services not started",
            )
            send_batch_notification(
                env=env, user=user, batch_id=batch_id, results=results, summary=state["summary"], status="failed"
            )
            _save_batch(batch_id, state)
            return state
        time.sleep(settings.DEPLOY_FIRST_SETTLE_SECONDS)

    for svc in ordered:
        results.append(_deploy_one(batch_id, env, svc, user))

    failed = sum(1 for r in results if r["status"] == "failed")
    if failed == 0:
        batch_status = "completed"
    elif failed == len(results):
        batch_status = "failed"
    else:
        batch_status = "partial_failure"

    deploy_order = list(dict.fromkeys(r["deploy_type"] for r in results))
    state = _batch_state(batch_id, env, user, timestamp, results, deploy_order, batch_status)
    _save_batch(batch_id, state)
    logger.info(f"[ORCHESTRATE] Batch {batch_id} complete: {state['summary']}, status={batch_status}")

    if len(results) > 1:
        send_batch_notification(
            env=env, user=user, batch_id=batch_id, results=results, summary=state["summary"], status=batch_status
        )
    return state


def get_batch_status(batch_id):
    batch = _load_batch(batch_id) or _batch_store.get(batch_id)
    if not batch:
        return {"error": f"Batch {batch_id} not found"}
    return batch


def list_batch_deployments():
    seen = {}
    if _store_dir().exists():
        for path in _store_dir().glob("batch-*.json"):
            try:
                seen[path.stem] = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
    for batch_id, batch in _batch_store.items():
        seen.setdefault(batch_id, batch)
    return [
        {
            "batch_id": batch_id,
            "environment": batch.get("environment"),
            "cluster": batch.get("cluster", ""),
            "status": batch.get("status"),
            "summary": batch.get("summary"),
            "timestamp": batch.get("timestamp"),
        }
        for batch_id, batch in seen.items()
    ]
