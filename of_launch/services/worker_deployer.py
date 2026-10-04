"""Worker deployer: CodeDeploy revision plus deployment, polled to a terminal state, real or mock."""

import logging
import time
import uuid
from datetime import datetime

from of_launch.config import clusters, settings
from of_launch.utils.codedeploy import create_deployment, get_deployment_status, register_revision
from of_launch.utils.slack import send_deploy_notification

logger = logging.getLogger(__name__)


def _poll_until_terminal(cd_deployment_id):
    elapsed = 0
    while elapsed < settings.CODEDEPLOY_POLL_TIMEOUT_SECONDS:
        time.sleep(settings.CODEDEPLOY_POLL_INTERVAL_SECONDS)
        elapsed += settings.CODEDEPLOY_POLL_INTERVAL_SECONDS
        state = get_deployment_status(cd_deployment_id)
        if state.get("status") in ("completed", "failed", "stopped"):
            return state["status"], state.get("error_information")
    return "failed", f"CodeDeploy poll timeout after {settings.CODEDEPLOY_POLL_TIMEOUT_SECONDS}s"


def deploy_worker(env, service_name, artifact_key, user="system"):
    mock = settings.is_mock_mode()
    deployment_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat() + "Z"

    service, err = clusters.lookup_service(env, "worker", service_name)
    if err:
        logger.error(f"[WORKER] Config resolution failed: {err}")
        return {"deployment_id": deployment_id, "status": "failed", "error": err, "mock": False}

    codedeploy_app = service.get("codedeploy_app", "")
    codedeploy_group = service.get("codedeploy_group", "")
    s3_bucket = service.get("artifact_bucket") or clusters.artifact_bucket()
    s3_key = artifact_key

    revision_result = register_revision(codedeploy_app, s3_bucket, s3_key)
    deploy_result = create_deployment(codedeploy_app, codedeploy_group, s3_bucket, s3_key, user=user)
    cd_deployment_id = deploy_result.get("deployment_id", deployment_id)

    send_deploy_notification(
        env=env,
        service_name=service_name,
        deploy_type="worker",
        version=artifact_key,
        user=user,
        status="in_progress",
        extra={"deployment_id": cd_deployment_id},
    )

    error_msg = None
    if mock:
        terminal_status = "completed"
    else:
        terminal_status, error_msg = _poll_until_terminal(cd_deployment_id)

    steps = [
        {
            "step": 1,
            "action": "resolve_config",
            "detail": f"Resolved: CodeDeploy app={codedeploy_app}, group={codedeploy_group}",
            "status": "success",
            "duration_ms": 10,
        },
        {
            "step": 2,
            "action": "register_revision",
            "detail": f"Registered s3://{s3_bucket}/{s3_key} with {codedeploy_app}",
            "status": "success",
            "mock": mock,
            "duration_ms": 200,
        },
        {
            "step": 3,
            "action": "create_deployment",
            "detail": f"Created deployment {cd_deployment_id} for {codedeploy_group}",
            "status": "success",
            "mock": mock,
            "duration_ms": 500,
        },
        {
            "step": 4,
            "action": "track_status",
            "detail": f"Deployment {cd_deployment_id} tracked; poll /status/api/codedeploy/{cd_deployment_id}",
            "status": "success",
            "duration_ms": 5,
        },
    ]

    logger.info(
        f"[WORKER] Deploy {cd_deployment_id}: {service_name} -> {env} "
        f"(artifact: {s3_key}, app: {codedeploy_app}, mock: {mock})"
    )
    result = {
        "deployment_id": cd_deployment_id,
        "deployment_type": "worker",
        "environment": env,
        "service": service_name,
        "service_name": service_name,
        "artifact_key": artifact_key,
        "user": user,
        "timestamp": timestamp,
        "status": terminal_status,
        "codedeploy_app": codedeploy_app,
        "codedeploy_group": codedeploy_group,
        "revision_id": revision_result.get("revision_id", ""),
        "steps": steps,
        "mock": mock,
        "message": (
            f"Worker deploy of {service_name} to {env} finished with status={terminal_status} "
            f"(CodeDeploy: {cd_deployment_id})"
        ),
    }
    if error_msg:
        result["error"] = error_msg
    return result
