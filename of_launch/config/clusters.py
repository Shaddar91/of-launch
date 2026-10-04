"""Cluster registry: config/clusters.json, one entry per cluster."""

import json
import os
import re

from of_launch.config import settings

DEPLOY_TYPES = ("frontend", "eks", "worker", "cron")
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")
_registry = None


class RegistryError(ValueError):
    pass


def _resolve(value):
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item) for item in value]
    return value


def _fill(value, environment):
    if isinstance(value, str):
        return value.replace("{environment}", environment)
    if isinstance(value, dict):
        return {key: _fill(item, environment) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, environment) for item in value]
    return value


def _validate(data):
    entries = data.get("clusters")
    if not isinstance(entries, dict) or not entries:
        raise RegistryError("registry needs a non-empty 'clusters' object")
    owners = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise RegistryError(f"cluster '{name}' must be an object")
        for key in ("argocd_url_env", "argocd_token_env"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise RegistryError(f"cluster '{name}' needs '{key}'")
        environments = entry.get("environments")
        if not isinstance(environments, list) or not environments:
            raise RegistryError(f"cluster '{name}' needs a non-empty 'environments' list")
        for environment in environments:
            if environment in owners:
                raise RegistryError(
                    f"environment '{environment}' is listed by clusters '{owners[environment]}' and '{name}'"
                )
            owners[environment] = name
        if not isinstance(entry.get("services", {}), dict):
            raise RegistryError(f"cluster '{name}' 'services' must be an object")
    return data


def load(path):
    with open(path, encoding="utf-8") as handle:
        return _validate(_resolve(json.load(handle)))


def registry():
    global _registry
    if _registry is None:
        _registry = load(settings.CLUSTERS_CONFIG_PATH)
    return _registry


def reload(path=None):
    global _registry
    _registry = load(path or settings.CLUSTERS_CONFIG_PATH)
    return _registry


def clusters():
    return list(registry()["clusters"])


def cluster(name):
    try:
        return registry()["clusters"][name]
    except KeyError:
        raise RegistryError(f"unknown cluster: {name}") from None


def environments():
    return [env for entry in registry()["clusters"].values() for env in entry["environments"]]


def cluster_for(environment):
    for name, entry in registry()["clusters"].items():
        if environment in entry["environments"]:
            return name
    raise RegistryError(f"unknown environment: {environment}")


def argocd_for(cluster_name):
    entry = cluster(cluster_name)
    return {
        "url": os.getenv(entry["argocd_url_env"], ""),
        "token": os.getenv(entry["argocd_token_env"], ""),
    }


def services_for(environment):
    entry = cluster(cluster_for(environment))
    services = entry.get("services", {})
    return {
        deploy_type: _fill(services.get(deploy_type, {}), environment) for deploy_type in DEPLOY_TYPES
    }


def lookup_service(environment, deploy_type, name):
    try:
        cluster_name = cluster_for(environment)
    except RegistryError:
        return None, f"Unknown environment: {environment}"
    config = services_for(environment).get(deploy_type, {}).get(name)
    if config is None:
        return None, f"No {deploy_type} service '{name}' in {environment} (cluster {cluster_name})"
    return config, None


def service_names():
    names = []
    for entry in registry()["clusters"].values():
        for group in entry.get("services", {}).values():
            for name in group:
                if name not in names:
                    names.append(name)
    return names


def argocd_apps():
    apps = []
    for environment in environments():
        cluster_name = cluster_for(environment)
        for service in services_for(environment)["eks"].values():
            app = service.get("argocd_app")
            entry = {"app": app, "cluster": cluster_name, "environment": environment}
            if app and entry not in apps:
                apps.append(entry)
    return apps


def cluster_for_app(app_name):
    for entry in argocd_apps():
        if entry["app"] == app_name:
            return entry["cluster"]
    raise RegistryError(f"no cluster runs ArgoCD app: {app_name}")


def dependencies():
    return registry().get("dependencies", {})


def artifact_bucket():
    return registry().get("artifact_bucket", "")
