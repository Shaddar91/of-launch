"""CodeDeploy API client: revisions, deployments and their status, real or mock."""

import logging
import random
import uuid
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from of_launch.config import settings

logger = logging.getLogger(__name__)

_mock_deployments = {}
_codedeploy_client = None


def _get_codedeploy_client():
    global _codedeploy_client
    if _codedeploy_client is None:
        _codedeploy_client = boto3.client("codedeploy", region_name=settings.REGION)
    return _codedeploy_client


def _normalize_aws_status(aws_status):
    status_map = {
        "Created": "created",
        "Queued": "queued",
        "InProgress": "in_progress",
        "Baking": "baking",
        "Succeeded": "completed",
        "Failed": "failed",
        "Stopped": "stopped",
        "Ready": "ready",
    }
    return status_map.get(aws_status, aws_status.lower() if aws_status else "unknown")


def _format_lifecycle_events(aws_events):
    events = []
    for ev in aws_events or []:
        start = ev.get("startTime")
        end = ev.get("endTime")
        events.append(
            {
                "event": ev.get("lifecycleEventName", ""),
                "status": _normalize_aws_status(ev.get("status", "")),
                "started_at": start.isoformat() if start else None,
                "ended_at": end.isoformat() if end else None,
                "duration_ms": int((end - start).total_seconds() * 1000) if start and end else None,
            }
        )
    return events


def _format_deployment_info(info):
    create_time = info.get("createTime")
    start_time = info.get("startTime")
    complete_time = info.get("completeTime")
    s3_loc = info.get("revision", {}).get("s3Location", {})
    overview = info.get("deploymentOverview", {})
    result = {
        "deployment_id": info.get("deploymentId", ""),
        "app_name": info.get("applicationName", ""),
        "deploy_group": info.get("deploymentGroupName", ""),
        "status": _normalize_aws_status(info.get("status", "")),
        "deployment_type": "codedeploy",
        "s3_location": {"bucket": s3_loc.get("bucket", ""), "key": s3_loc.get("key", "")} if s3_loc else {},
        "started_at": start_time.isoformat() if start_time else (create_time.isoformat() if create_time else ""),
        "lifecycle_events": _format_lifecycle_events(info.get("deploymentStatusMessages", [])),
        "instances": [],
        "overview": {
            "pending": overview.get("Pending", 0),
            "in_progress": overview.get("InProgress", 0),
            "succeeded": overview.get("Succeeded", 0),
            "failed": overview.get("Failed", 0),
            "skipped": overview.get("Skipped", 0),
        },
        "mock": False,
    }
    if complete_time:
        result["completed_at"] = complete_time.isoformat()
    return result


def _s3_revision(s3_bucket, s3_key):
    return {"revisionType": "S3", "s3Location": {"bucket": s3_bucket, "key": s3_key, "bundleType": "tgz"}}


def register_revision(app_name, s3_bucket, s3_key):
    location = {"bucket": s3_bucket, "key": s3_key, "bundle_type": "tgz"}
    if settings.is_mock_mode():
        logger.info(f"[MOCK CODEDEPLOY] register_revision({app_name}): s3://{s3_bucket}/{s3_key}")
        return {
            "app_name": app_name,
            "revision_id": uuid.uuid4().hex[:8],
            "s3_location": location,
            "registered_at": datetime.utcnow().isoformat() + "Z",
            "mock": True,
        }
    try:
        _get_codedeploy_client().register_application_revision(
            applicationName=app_name, revision=_s3_revision(s3_bucket, s3_key)
        )
        logger.info(f"[CODEDEPLOY] register_revision({app_name}): s3://{s3_bucket}/{s3_key}")
        return {
            "app_name": app_name,
            "revision_id": s3_key,
            "s3_location": location,
            "registered_at": datetime.utcnow().isoformat() + "Z",
            "mock": False,
        }
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[CODEDEPLOY] register_revision failed: {exc}")
        return {"app_name": app_name, "error": str(exc), "mock": False}


def _mock_event(name, status, started_at=None, ended_at=None, duration_ms=None):
    return {
        "event": name,
        "status": status,
        "started_at": started_at.isoformat() + "Z" if started_at else None,
        "ended_at": ended_at.isoformat() + "Z" if ended_at else None,
        "duration_ms": duration_ms,
    }


def create_deployment(app_name, deploy_group, s3_bucket, s3_key, deployment_type="worker", user="system"):
    if settings.is_mock_mode():
        deployment_id = f"cd-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()
        s = lambda seconds: now + timedelta(seconds=seconds)  # noqa: E731
        _mock_deployments[deployment_id] = {
            "deployment_id": deployment_id,
            "app_name": app_name,
            "deploy_group": deploy_group,
            "status": "in_progress",
            "deployment_type": deployment_type,
            "s3_location": {"bucket": s3_bucket, "key": s3_key},
            "started_at": now.isoformat() + "Z",
            "lifecycle_events": [
                _mock_event("ApplicationStop", "completed", now, s(5), 5000),
                _mock_event("DownloadBundle", "completed", s(5), s(12), 7000),
                _mock_event("BeforeInstall", "completed", s(12), s(15), 3000),
                _mock_event("Install", "in_progress", s(15)),
                _mock_event("AfterInstall", "pending"),
                _mock_event("ApplicationStart", "pending"),
                _mock_event("ValidateService", "pending"),
            ],
            "instances": [
                {"instance_id": f"i-{uuid.uuid4().hex[:12]}", "status": "in_progress", "current_event": "Install"},
                {"instance_id": f"i-{uuid.uuid4().hex[:12]}", "status": "pending",
                 "current_event": "ApplicationStop"},
            ],
            "mock": True,
        }
        logger.info(
            f"[MOCK CODEDEPLOY] create_deployment({app_name}/{deploy_group}): {deployment_id} -> s3://{s3_bucket}/{s3_key}"
        )
        return _mock_deployments[deployment_id]

    try:
        resp = _get_codedeploy_client().create_deployment(
            applicationName=app_name,
            deploymentGroupName=deploy_group,
            revision=_s3_revision(s3_bucket, s3_key),
            description=f"of-launch deploy by {user}",
        )
        real_deployment_id = resp["deploymentId"]
        logger.info(
            f"[CODEDEPLOY] create_deployment({app_name}/{deploy_group}): {real_deployment_id} -> s3://{s3_bucket}/{s3_key}"
        )
        return {
            "deployment_id": real_deployment_id,
            "app_name": app_name,
            "deploy_group": deploy_group,
            "status": "in_progress",
            "deployment_type": deployment_type,
            "s3_location": {"bucket": s3_bucket, "key": s3_key},
            "started_at": datetime.utcnow().isoformat() + "Z",
            "mock": False,
        }
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[CODEDEPLOY] create_deployment failed: {exc}")
        return {
            "deployment_id": f"cd-failed-{uuid.uuid4().hex[:8]}",
            "app_name": app_name,
            "deploy_group": deploy_group,
            "status": "failed",
            "error": str(exc),
            "mock": False,
        }


def _advance_mock_deployment(dep):
    now = datetime.utcnow()
    in_progress = [e for e in dep["lifecycle_events"] if e["status"] == "in_progress"]
    if not in_progress:
        return dep
    current = in_progress[0]
    current["status"] = "completed"
    current["ended_at"] = now.isoformat() + "Z"
    current["duration_ms"] = random.randint(2000, 8000)
    pending = [e for e in dep["lifecycle_events"] if e["status"] == "pending"]
    if pending:
        pending[0]["status"] = "in_progress"
        pending[0]["started_at"] = now.isoformat() + "Z"
        for inst in dep["instances"]:
            if inst["status"] == "in_progress":
                inst["current_event"] = pending[0]["event"]
    else:
        dep["status"] = "completed"
        dep["completed_at"] = now.isoformat() + "Z"
        for inst in dep["instances"]:
            inst["status"] = "completed"
            inst["current_event"] = "ValidateService"
    return dep


def get_deployment_status(deployment_id):
    if settings.is_mock_mode():
        if deployment_id not in _mock_deployments:
            return {"error": f"Deployment {deployment_id} not found"}
        return _advance_mock_deployment(_mock_deployments[deployment_id])
    try:
        resp = _get_codedeploy_client().get_deployment(deploymentId=deployment_id)
        return _format_deployment_info(resp.get("deploymentInfo", {}))
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[CODEDEPLOY] Failed to get deployment {deployment_id}: {exc}")
        return {"deployment_id": deployment_id, "status": "unknown", "error": str(exc), "mock": False}


def _list_real_deployments(params, max_results):
    client = _get_codedeploy_client()
    dep_ids = client.list_deployments(**params).get("deployments", [])[:max_results]
    if not dep_ids:
        return []
    batch_resp = client.batch_get_deployments(deploymentIds=dep_ids)
    deployments = [_format_deployment_info(info) for info in batch_resp.get("deploymentsInfo", [])]
    deployments.sort(key=lambda d: d.get("started_at", ""), reverse=True)
    return deployments


def list_deployment_history(app_name, deploy_group=None, max_results=25):
    if settings.is_mock_mode():
        return [d for d in _mock_deployments.values() if d.get("app_name") == app_name]
    if not deploy_group:
        logger.warning(f"[CODEDEPLOY] deploy_group required for real API, returning empty for {app_name}")
        return []
    try:
        logger.info(f"[CODEDEPLOY] Listing deployment history: {app_name}/{deploy_group}")
        return _list_real_deployments({"applicationName": app_name, "deploymentGroupName": deploy_group}, max_results)
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[CODEDEPLOY] Failed to list deployments for {app_name}: {exc}")
        return []


def list_active_deployments():
    if settings.is_mock_mode():
        return [d for d in _mock_deployments.values() if d["status"] == "in_progress"]
    try:
        active = _list_real_deployments(
            {"includeOnlyStatuses": ["Created", "Queued", "InProgress", "Baking", "Ready"]}, 20
        )
        logger.info(f"[CODEDEPLOY] Found {len(active)} active real deployments")
        return active
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[CODEDEPLOY] Failed to list active deployments: {exc}")
        return []
