"""Slack notifications for deployment events."""

import logging

import requests

from of_launch.config import settings

logger = logging.getLogger(__name__)


def _is_enabled():
    return bool(settings.SLACK_WEBHOOK_URL)


def _env_emoji(env):
    if env == "production":
        return ":rotating_light:"
    if env == "stage":
        return ":large_yellow_circle:"
    return ":large_green_circle:"


def _status_emoji(status):
    if status in ("completed", "success"):
        return ":white_check_mark:"
    if status == "failed":
        return ":x:"
    if status == "partial_failure":
        return ":warning:"
    return ":hourglass_flowing_sand:"


def _type_label(deploy_type):
    labels = {
        "frontend": "Frontend (S3/CloudFront)",
        "eks": "EKS (ArgoCD)",
        "worker": "Worker (CodeDeploy)",
        "cron": "Cron (CodeDeploy)",
    }
    return labels.get(deploy_type, deploy_type)


def send_deploy_notification(env, service_name, deploy_type, version, user, status, extra=None):
    if not _is_enabled():
        return
    extra = extra or {}
    ver_short = version if len(version) <= 40 else f"{version[:37]}..."
    text = (
        f"{_status_emoji(status)} *{status.upper()}* — {_type_label(deploy_type)}\n"
        f"{_env_emoji(env)} *{env}* — `{service_name}`\n"
        f"Version: `{ver_short}`\n"
        f"By: {user}"
    )
    if extra.get("commit_sha"):
        text += f"\nCommit: `{extra['commit_sha']}`"
    if extra.get("deployment_id"):
        text += f"\nDeploy ID: `{extra['deployment_id']}`"
    _post(text)


def send_batch_notification(env, user, batch_id, results, summary, status):
    if not _is_enabled():
        return
    lines = [
        f"{_status_emoji(status)} *Batch Deploy {status.upper()}* — `{batch_id}`",
        f"{_env_emoji(env)} *{env}* — by {user}",
        f"Total: {summary['total']} | Succeeded: {summary['succeeded']} | Failed: {summary['failed']}",
        "",
    ]
    for entry in results:
        svc_status = entry.get("status", "unknown")
        lines.append(
            f"  {_status_emoji(svc_status)} `{entry['service']}` ({_type_label(entry.get('deploy_type', ''))})"
            f" — {svc_status}"
        )
    _post("\n".join(lines))


def _post(text):
    try:
        resp = requests.post(settings.SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[SLACK] Webhook returned {resp.status_code}: {resp.text}")
        else:
            logger.info("[SLACK] Notification sent")
    except Exception as exc:
        logger.warning(f"[SLACK] Failed to send notification: {exc}")
