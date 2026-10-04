"""Artifact browser: S3 and ECR artifact lists, real or mock."""

import hashlib
import logging
import random
import re
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from of_launch.config import clusters, settings

logger = logging.getLogger(__name__)

_s3_client = None
_ecr_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=settings.REGION)
    return _s3_client


def _get_ecr_client():
    global _ecr_client
    if _ecr_client is None:
        _ecr_client = boto3.client("ecr", region_name=settings.REGION)
    return _ecr_client


def artifact_display_name(key):
    basename = key.rsplit("/", 1)[-1]
    return re.sub(r"\.(tar\.gz|tar\.bz2|tgz|zip)$", "", basename)


def _format_size(size_bytes):
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.1f} KB"
    return f"{size_bytes} B"


def _list_real_s3_artifacts(bucket, prefix, max_results=50):
    client = _get_s3_client()
    artifacts = []
    paginator = client.get_paginator("list_objects_v2")
    page_iter = paginator.paginate(Bucket=bucket, Prefix=prefix if prefix.endswith("/") else prefix + "/")
    for page in page_iter:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            size = obj.get("Size", 0)
            last_mod = obj.get("LastModified")
            artifacts.append(
                {
                    "key": key,
                    "version_hash": artifact_display_name(key),
                    "last_modified": last_mod.isoformat() if last_mod else "",
                    "size_bytes": size,
                    "size_display": _format_size(size),
                }
            )
    artifacts.sort(key=lambda a: a["last_modified"], reverse=True)
    return artifacts[:max_results]


def _generate_mock_hash():
    return hashlib.sha1(str(random.random()).encode()).hexdigest()[:8]


def _mock_artifacts(prefix, count=10):
    now = datetime.utcnow()
    artifacts = []
    for i in range(count):
        git_hash = _generate_mock_hash()
        ts = now - timedelta(hours=i * 6 + random.randint(0, 5))
        artifacts.append(
            {
                "key": f"{prefix}/build_{git_hash}.tar.gz",
                "version_hash": git_hash,
                "last_modified": ts.isoformat() + "Z",
                "size_bytes": random.randint(5_000_000, 50_000_000),
                "size_display": f"{random.randint(5, 50)}.{random.randint(0, 9)} MB",
            }
        )
    return artifacts


def _mock_ecr_images(repo_name, count=10):
    now = datetime.utcnow()
    images = []
    branches = ["master", "develop", "feature-auth", "fix-deploy"]
    for i in range(count):
        git_hash = _generate_mock_hash()
        branch = branches[i % len(branches)]
        ts = now - timedelta(hours=i * 4 + random.randint(0, 3))
        images.append(
            {
                "image_tag": f"{branch}-{git_hash}",
                "pushed_at": ts.isoformat() + "Z",
                "digest": f"sha256:{hashlib.sha256(str(random.random()).encode()).hexdigest()[:12]}",
                "size_bytes": random.randint(100_000_000, 500_000_000),
                "size_display": f"{random.randint(100, 500)} MB",
            }
        )
    return images


def _list_real_ecr_images(repo_name, max_results=50):
    client = _get_ecr_client()
    images = []
    paginator = client.get_paginator("describe_images")
    page_iter = paginator.paginate(repositoryName=repo_name, filter={"tagStatus": "TAGGED"})
    for page in page_iter:
        for detail in page.get("imageDetails", []):
            tags = detail.get("imageTags", [])
            if not tags:
                continue
            pushed = detail.get("imagePushedAt")
            size = detail.get("imageSizeInBytes", 0)
            digest = detail.get("imageDigest", "")
            for tag in tags:
                images.append(
                    {
                        "image_tag": tag,
                        "pushed_at": pushed.isoformat() if pushed else "",
                        "digest": digest,
                        "size_bytes": size,
                        "size_display": _format_size(size),
                    }
                )
    images.sort(key=lambda i: i["pushed_at"], reverse=True)
    return images[:max_results]


def _s3_listing(env, deploy_type, service_name):
    service, err = clusters.lookup_service(env, deploy_type, service_name)
    if err:
        return {"error": err, "artifacts": []}

    prefix = service.get("artifact_prefix", "")
    bucket = service.get("artifact_bucket") or clusters.artifact_bucket()
    result = {
        "environment": env,
        "service": service_name,
        "artifact_type": deploy_type,
        "source": f"s3://{bucket}/{prefix}/",
    }
    if settings.is_mock_mode():
        return {**result, "artifacts": _mock_artifacts(prefix), "mock": True}

    try:
        logger.info(f"[S3] Listing {deploy_type} artifacts: s3://{bucket}/{prefix}/")
        return {**result, "artifacts": _list_real_s3_artifacts(bucket, prefix), "mock": False}
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[S3] Failed to list {deploy_type} artifacts for {prefix}: {exc}")
        return {**result, "artifacts": [], "error": str(exc), "mock": False}


def list_frontend_artifacts(env, app_name):
    return _s3_listing(env, "frontend", app_name)


def list_worker_artifacts(env, service_name):
    return _s3_listing(env, "worker", service_name)


def list_cron_artifacts(env, service_name):
    return _s3_listing(env, "cron", service_name)


def list_ecr_images(env, service_name):
    service, err = clusters.lookup_service(env, "eks", service_name)
    if err:
        return {"error": err, "images": []}

    repo_name = service.get("ecr_repo", "")
    result = {"environment": env, "service": service_name, "artifact_type": "ecr", "repository": repo_name}
    if settings.is_mock_mode():
        return {**result, "images": _mock_ecr_images(repo_name), "mock": True}

    try:
        logger.info(f"[ECR] Listing images from repository: {repo_name}")
        return {**result, "images": _list_real_ecr_images(repo_name), "mock": False}
    except (ClientError, NoCredentialsError) as exc:
        logger.error(f"[ECR] Failed to list images for {repo_name}: {exc}")
        return {**result, "images": [], "error": str(exc), "mock": False}


def list_services_for_env(env):
    try:
        groups = clusters.services_for(env)
    except clusters.RegistryError as exc:
        return {"error": str(exc)}

    result = {}
    for deploy_type, services in groups.items():
        type_list = [
            {"name": name, "display_name": config.get("display_name", name), "deploy_type": deploy_type}
            for name, config in services.items()
        ]
        if type_list:
            result[deploy_type] = type_list
    return {"environment": env, "cluster": clusters.cluster_for(env), "services": result}
