"""Frontend deployer: S3 sync plus CloudFront invalidation, real or mock."""

import logging
import mimetypes
import os
import tarfile
import tempfile
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from of_launch.config import clusters, settings

logger = logging.getLogger(__name__)

_s3_client = None
_cf_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=settings.REGION)
    return _s3_client


def _get_cloudfront_client():
    global _cf_client
    if _cf_client is None:
        _cf_client = boto3.client("cloudfront", region_name=settings.REGION)
    return _cf_client


def _download_and_extract_artifact(s3_client, bucket, key, temp_dir):
    tar_path = os.path.join(temp_dir, "artifact.tar.gz")
    s3_client.download_file(bucket, key, tar_path)

    extract_dir = os.path.join(temp_dir, "build")
    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)

    entries = os.listdir(extract_dir)
    if len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
        return os.path.join(extract_dir, entries[0])
    return extract_dir


def _sync_to_deploy_bucket(s3_client, local_dir, deploy_bucket):
    uploaded_keys = set()
    for root, _dirs, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            s3_key = os.path.relpath(local_path, local_dir).replace(os.sep, "/")
            extra_args = {"ContentType": mimetypes.guess_type(filename)[0] or "application/octet-stream"}
            if "/assets/" in s3_key or s3_key.startswith("assets/"):
                extra_args["CacheControl"] = "public, max-age=31536000, immutable"
            elif filename == "index.html":
                extra_args["CacheControl"] = "no-cache, no-store, must-revalidate"
            s3_client.upload_file(local_path, deploy_bucket, s3_key, ExtraArgs=extra_args)
            uploaded_keys.add(s3_key)

    delete_count = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=deploy_bucket):
        for obj in page.get("Contents", []):
            if obj["Key"] not in uploaded_keys:
                s3_client.delete_object(Bucket=deploy_bucket, Key=obj["Key"])
                delete_count += 1

    logger.info(f"[S3] Synced {len(uploaded_keys)} files to {deploy_bucket}, deleted {delete_count} orphaned files")
    return len(uploaded_keys), delete_count


def _read_cloudfront_ids(s3_client, bucket, key):
    resp = s3_client.get_object(Bucket=bucket, Key=key)
    content = resp["Body"].read().decode("utf-8")
    ids = [line.strip() for line in content.splitlines() if line.strip()]
    logger.info(f"[CLOUDFRONT] Read {len(ids)} distribution IDs from s3://{bucket}/{key}")
    return ids


def _invalidate_cloudfront_distributions(cf_client, distribution_ids):
    results = []
    for cf_id in distribution_ids:
        try:
            resp = cf_client.create_invalidation(
                DistributionId=cf_id,
                InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": str(uuid.uuid4())},
            )
            inv_id = resp["Invalidation"]["Id"]
            inv_status = resp["Invalidation"]["Status"]
            logger.info(f"[CLOUDFRONT] Invalidation {inv_id} created for {cf_id} (status: {inv_status})")
            results.append({"distribution_id": cf_id, "invalidation_id": inv_id, "status": inv_status, "mock": False})
        except ClientError as exc:
            logger.error(f"[CLOUDFRONT] Failed to invalidate {cf_id}: {exc}")
            results.append(
                {
                    "distribution_id": cf_id,
                    "invalidation_id": None,
                    "status": "failed",
                    "error": str(exc),
                    "mock": False,
                }
            )
    return results


def _mock_result(deployment_id, env, app_name, artifact_key, user, timestamp, config):
    artifact_bucket = config["artifact_bucket"]
    cloudfront_id = config["cloudfront_id"]
    cf_detail = (
        f"Use CloudFront ID {cloudfront_id}"
        if cloudfront_id
        else f"Read CloudFront IDs from s3://{artifact_bucket}/{config['cloudfront_key']}"
    )
    steps = [
        {
            "step": 1,
            "action": "download_artifact",
            "detail": f"Download s3://{artifact_bucket}/{artifact_key}",
            "status": "success",
            "mock": True,
            "duration_ms": 1200,
        },
        {
            "step": 2,
            "action": "sync_to_deploy_bucket",
            "detail": f"Sync extracted build to {config['deploy_bucket']} (sync-then-delete)",
            "status": "success",
            "mock": True,
            "duration_ms": 3400,
        },
        {"step": 3, "action": "read_cloudfront_ids", "detail": cf_detail, "status": "success", "mock": True,
         "duration_ms": 200},
        {
            "step": 4,
            "action": "invalidate_cloudfront",
            "detail": "Create CloudFront invalidation for /* on all distributions",
            "status": "success",
            "mock": True,
            "duration_ms": 800,
        },
    ]
    logger.info(f"[MOCK DEPLOY] Frontend deployment {deployment_id}: {app_name} -> {env} (artifact: {artifact_key})")
    for step in steps:
        logger.info(f"  Step {step['step']}: {step['action']} - {step['detail']}")
    return {
        "deployment_id": deployment_id,
        "deployment_type": "frontend",
        "environment": env,
        "service": app_name,
        "artifact_key": artifact_key,
        "user": user,
        "timestamp": timestamp,
        "status": "completed",
        "steps": steps,
        "mock": True,
        "message": f"Frontend deploy of {app_name} to {env} completed successfully",
    }


def deploy_frontend(env, app_name, artifact_key, user="system"):
    deployment_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat() + "Z"

    service, err = clusters.lookup_service(env, "frontend", app_name)
    if err:
        logger.error(f"[FRONTEND] Config resolution failed: {err}")
        return {"deployment_id": deployment_id, "status": "failed", "error": err, "mock": True}

    config = {
        "artifact_bucket": service.get("artifact_bucket") or clusters.artifact_bucket(),
        "deploy_bucket": service.get("deploy_bucket", ""),
        "cloudfront_id": service.get("cloudfront_id", ""),
        "cloudfront_key": service.get("cloudfront_key", ""),
    }
    if settings.is_mock_mode():
        return _mock_result(deployment_id, env, app_name, artifact_key, user, timestamp, config)

    artifact_bucket = config["artifact_bucket"]
    deploy_bucket = config["deploy_bucket"]
    try:
        s3_client = _get_s3_client()
        steps = []

        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"[S3] Downloading s3://{artifact_bucket}/{artifact_key}")
            build_dir = _download_and_extract_artifact(s3_client, artifact_bucket, artifact_key, temp_dir)
            steps.append(
                {"step": 1, "action": "download_artifact", "detail": f"Downloaded s3://{artifact_bucket}/{artifact_key}",
                 "status": "success", "duration_ms": 0}
            )
            logger.info(f"[S3] Syncing to {deploy_bucket}")
            upload_count, delete_count = _sync_to_deploy_bucket(s3_client, build_dir, deploy_bucket)
            steps.append(
                {"step": 2, "action": "sync_to_deploy_bucket",
                 "detail": f"Synced {upload_count} files to {deploy_bucket}, deleted {delete_count} orphaned files",
                 "status": "success", "duration_ms": 0}
            )

        cf_ids = []
        cf_source = ""
        if config["cloudfront_id"]:
            cf_ids = [config["cloudfront_id"]]
            cf_source = f"direct config ({config['cloudfront_id']})"
        elif config["cloudfront_key"]:
            try:
                cf_ids = _read_cloudfront_ids(s3_client, artifact_bucket, config["cloudfront_key"])
                cf_source = f"s3://{artifact_bucket}/{config['cloudfront_key']}"
            except ClientError as exc:
                logger.error(f"[CLOUDFRONT] Failed to read IDs from {config['cloudfront_key']}: {exc}")
        steps.append(
            {"step": 3, "action": "read_cloudfront_ids",
             "detail": f"Resolved {len(cf_ids)} CloudFront distribution ID(s) from {cf_source}"
             if cf_ids else "No CloudFront config found",
             "status": "success" if cf_ids else "warning", "duration_ms": 0}
        )

        invalidations = _invalidate_cloudfront_distributions(_get_cloudfront_client(), cf_ids) if cf_ids else []
        steps.append(
            {"step": 4, "action": "invalidate_cloudfront",
             "detail": f"Invalidated {len(invalidations)} CloudFront distributions"
             if invalidations else "No CloudFront distributions to invalidate",
             "status": "success", "duration_ms": 0}
        )

        logger.info(
            f"[FRONTEND] Deploy {deployment_id}: {app_name} -> {env} "
            f"(artifact: {artifact_key}, bucket: {deploy_bucket}, cf_distributions: {len(cf_ids)})"
        )
        return {
            "deployment_id": deployment_id,
            "deployment_type": "frontend",
            "environment": env,
            "service": app_name,
            "artifact_key": artifact_key,
            "user": user,
            "timestamp": timestamp,
            "status": "completed",
            "deploy_bucket": deploy_bucket,
            "files_uploaded": upload_count,
            "files_deleted": delete_count,
            "cloudfront_invalidations": invalidations,
            "steps": steps,
            "mock": False,
            "message": (
                f"Frontend deploy of {app_name} to {env} completed: "
                f"{upload_count} files synced, {len(invalidations)} CF distributions invalidated"
            ),
        }
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[S3] Real frontend deploy failed: {exc}")
        return {
            "deployment_id": deployment_id,
            "deployment_type": "frontend",
            "environment": env,
            "service": app_name,
            "status": "failed",
            "error": str(exc),
            "mock": False,
        }
