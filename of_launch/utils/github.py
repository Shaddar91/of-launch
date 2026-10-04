"""GitHub Contents API: byte-preserving Helm values updates with conflict retry."""

import base64
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import requests

from of_launch.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
MAX_CONFLICT_RETRIES = 2


@dataclass(frozen=True, slots=True)
class FileUpdateSuccess:
    commit_sha: str
    source_sha: str
    attempts: int


@dataclass(frozen=True, slots=True)
class FileUpdateRetryableFailure:
    error: str
    status_code: int | None
    attempts: int


@dataclass(frozen=True, slots=True)
class FileUpdatePermanentFailure:
    error: str
    status_code: int | None
    attempts: int


FileUpdateResult = FileUpdateSuccess | FileUpdateRetryableFailure | FileUpdatePermanentFailure


def _github_headers():
    return {"Authorization": f"token {settings.GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def _contents_url(repo, file_path):
    return f"{GITHUB_API}/repos/{settings.GITHUB_OWNER}/{repo}/contents/{file_path}"


def _read_file_from_github(repo, branch, file_path):
    response = requests.get(_contents_url(repo, file_path), headers=_github_headers(), params={"ref": branch},
                            timeout=30)
    response.raise_for_status()
    data = response.json()
    try:
        content = base64.b64decode(data["content"])
        sha = data["sha"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid GitHub Contents response") from exc
    if not isinstance(sha, str) or not sha:
        raise ValueError("invalid GitHub Contents response")
    return content, sha


def _write_file_to_github(repo, branch, file_path, content, sha, commit_message):
    response = requests.put(
        _contents_url(repo, file_path),
        headers=_github_headers(),
        json={
            "message": commit_message,
            "content": base64.b64encode(content).decode("ascii"),
            "sha": sha,
            "branch": branch,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _request_failure(error, attempts):
    response = error.response
    status_code = response.status_code if response is not None else None
    retryable = (
        isinstance(error, (requests.ConnectionError, requests.Timeout))
        or status_code in {408, 409, 425, 429}
        or status_code is None
        or status_code >= 500
    )
    label = status_code if status_code is not None else type(error).__name__
    failure_type = FileUpdateRetryableFailure if retryable else FileUpdatePermanentFailure
    return failure_type(error=f"GitHub transport failure: {label}", status_code=status_code, attempts=attempts)


def _permanent(error, attempt):
    return FileUpdatePermanentFailure(error=error, status_code=None, attempts=attempt)


def _commit_with_conflict_retry(repository, branch, path, transform, message):
    for attempt in range(1, MAX_CONFLICT_RETRIES + 2):
        try:
            content, source_sha = _read_file_from_github(repository, branch, path)
        except requests.RequestException as exc:
            return _request_failure(exc, attempt)
        except (TypeError, ValueError):
            return _permanent("Invalid GitHub Contents response", attempt)

        try:
            updated_content = transform(content)
        except Exception as exc:
            return _permanent(f"Transform failed: {type(exc).__name__}", attempt)
        if not isinstance(updated_content, bytes):
            return _permanent("Transform must return bytes", attempt)

        try:
            result = _write_file_to_github(repository, branch, path, updated_content, source_sha, message)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 409 and attempt <= MAX_CONFLICT_RETRIES:
                logger.warning("[GITHUB] 409 Conflict on attempt %s, refetching file", attempt)
                continue
            return _request_failure(exc, attempt)
        except requests.RequestException as exc:
            return _request_failure(exc, attempt)

        try:
            commit_sha = result["commit"]["sha"]
        except (KeyError, TypeError):
            return _permanent("Invalid GitHub commit response", attempt)
        if not isinstance(commit_sha, str) or not commit_sha:
            return _permanent("Invalid GitHub commit response", attempt)
        return FileUpdateSuccess(commit_sha=commit_sha, source_sha=source_sha, attempts=attempt)

    raise RuntimeError("unreachable conflict retry state")


def update_file(
    repository: str, branch: str, path: str, transform: Callable[[bytes], bytes], message: str
) -> FileUpdateResult:
    return _commit_with_conflict_retry(repository, branch, path, transform, message)


def _update_tag_in_content(content, new_tag, tag_key):
    updated, count = re.subn(rf'(\b{re.escape(tag_key)}:\s*)"[^"]*"', f'\\1"{new_tag}"', content)
    if count == 0:
        raise ValueError(f"{tag_key} pattern not found in file content")
    return re.sub(r'(deploymentVersion:\s*)"[^"]*"', '\\1"1"', updated)


def _extract_current_tag(content, tag_key):
    match = re.search(rf'\b{re.escape(tag_key)}:\s*"([^"]*)"', content)
    return match.group(1) if match else "unknown"


def update_image_tag(helm_repo, helm_branch, values_file, new_tag, service_name="", tag_key="imageTag"):
    if settings.is_mock_mode():
        return _mock_update_image_tag(helm_repo, helm_branch, values_file, new_tag, service_name)

    commit_msg = f"deploy: {service_name} -> {new_tag}"
    started_at = time.time()
    timings = {}
    state = {}

    def transform(content):
        transform_started_at = time.time()
        text = content.decode("utf-8")
        if "old_tag" not in state:
            timings["read_ms"] = int((transform_started_at - started_at) * 1000)
            state["old_tag"] = _extract_current_tag(text, tag_key)
            logger.info("[GITHUB] Current %s: %s", tag_key, state["old_tag"])
        updated = _update_tag_in_content(text, new_tag, tag_key).encode("utf-8")
        timings["update_ms"] = int((time.time() - transform_started_at) * 1000)
        return updated

    logger.info("[GITHUB] Reading %s from %s/%s@%s", values_file, settings.GITHUB_OWNER, helm_repo, helm_branch)
    result = update_file(repository=helm_repo, branch=helm_branch, path=values_file, transform=transform,
                         message=commit_msg)
    if not isinstance(result, FileUpdateSuccess):
        logger.error("[GITHUB] %s updating %s", result.error, values_file)
        return {"status": "failed", "error": result.error, "mock": False}

    total_ms = int((time.time() - started_at) * 1000)
    read_ms = timings.get("read_ms", 0)
    update_ms = timings.get("update_ms", 0)
    commit_sha = result.commit_sha[:8]
    old_tag = state["old_tag"]
    logger.info("[GITHUB] Committed %s: %s", commit_sha, commit_msg)
    return {
        "helm_repo": helm_repo,
        "helm_branch": helm_branch,
        "values_file": values_file,
        "old_tag": old_tag,
        "new_tag": new_tag,
        "commit_sha": commit_sha,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "steps": [
            {
                "step": 1,
                "action": "read_file",
                "detail": f"Read {values_file} from {helm_repo}/{helm_branch} (sha: {result.source_sha[:8]})",
                "status": "success",
                "duration_ms": read_ms,
            },
            {
                "step": 2,
                "action": "update_values",
                "detail": f'Set {tag_key}="{new_tag}" (was "{old_tag}")',
                "status": "success",
                "duration_ms": update_ms,
            },
            {
                "step": 3,
                "action": "git_commit",
                "detail": f'Committed: "{commit_msg}" (sha: {commit_sha})',
                "status": "success",
                "duration_ms": max(0, total_ms - read_ms - update_ms),
            },
        ],
        "status": "success",
        "mock": False,
    }


def _mock_update_image_tag(helm_repo, helm_branch, values_file, new_tag, service_name=""):
    commit_sha = uuid.uuid4().hex[:8]
    steps = [
        {"step": 1, "action": "git_pull", "detail": f"Pull {helm_repo} branch {helm_branch}", "status": "success",
         "mock": True, "duration_ms": 800},
        {"step": 2, "action": "update_values", "detail": f"Set image tag {new_tag} in {values_file}",
         "status": "success", "mock": True, "duration_ms": 50},
        {"step": 3, "action": "git_commit", "detail": f'Commit: "deploy: {service_name} -> {new_tag}"',
         "status": "success", "mock": True, "duration_ms": 100},
        {"step": 4, "action": "git_push", "detail": f"Push to {helm_repo}/{helm_branch}", "status": "success",
         "mock": True, "duration_ms": 1200},
    ]
    logger.info(f"[MOCK GIT] update_image_tag: {helm_repo}/{values_file} -> {new_tag} (service: {service_name})")
    for step in steps:
        logger.info(f"  Step {step['step']}: {step['action']} - {step['detail']}")
    return {
        "helm_repo": helm_repo,
        "helm_branch": helm_branch,
        "values_file": values_file,
        "old_tag": f"master-{uuid.uuid4().hex[:8]}",
        "new_tag": new_tag,
        "commit_sha": commit_sha,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "steps": steps,
        "status": "success",
        "mock": True,
        "message": f"Update {values_file} in {helm_repo} with tag {new_tag}",
    }
