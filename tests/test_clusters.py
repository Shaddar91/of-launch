"""The cluster registry: one 'of' cluster by default, one more entry adds a cluster."""

import pytest

from of_launch.config import clusters
from tests.conftest import write_registry


def test_registry_has_only_the_of_cluster(registry):
    assert clusters.clusters() == ["of"]
    assert clusters.environments() == ["production"]


def test_production_belongs_to_of(registry):
    assert clusters.cluster_for("production") == "of"


def test_unknown_environment_raises(registry):
    with pytest.raises(clusters.RegistryError):
        clusters.cluster_for("dev")


def test_argocd_for_reads_the_named_env_vars(registry, monkeypatch):
    monkeypatch.setenv("ARGOCD_OF_URL", "https://argocd.example.test")
    monkeypatch.setenv("ARGOCD_OF_TOKEN", "token-of")
    assert clusters.argocd_for("of") == {"url": "https://argocd.example.test", "token": "token-of"}


def test_services_fill_the_environment_placeholder(registry):
    services = clusters.services_for("production")
    assert services["frontend"]["of-web"]["artifact_prefix"] == "production/of-web"
    assert services["eks"]["of-api"]["ecr_repo"] == "of-api"
    assert services["worker"] == {} and services["cron"] == {}


def test_lookup_service_reports_unknown_names(registry):
    config, err = clusters.lookup_service("production", "eks", "of-api")
    assert err is None and config["argocd_app"] == "of-api"
    assert clusters.lookup_service("production", "eks", "nope")[1].startswith("No eks service 'nope'")
    assert clusters.lookup_service("dev", "eks", "of-api")[1] == "Unknown environment: dev"


def test_registry_values_resolve_environment_placeholders(registry):
    assert clusters.artifact_bucket() == "test-artifact-bucket"


def test_cluster_entry_has_exactly_the_registry_keys(registry):
    assert set(registry["clusters"]["of"]) == {
        "display_name", "argocd_url_env", "argocd_token_env", "environments", "services"
    }
    assert set(registry["clusters"]["of"]["services"]) == set(clusters.DEPLOY_TYPES)


def test_argocd_apps_and_cluster_for_app(registry):
    assert clusters.argocd_apps() == [{"app": "of-api", "cluster": "of", "environment": "production"}]
    assert clusters.cluster_for_app("of-api") == "of"
    with pytest.raises(clusters.RegistryError):
        clusters.cluster_for_app("nope")


def test_one_more_entry_adds_a_cluster(two_cluster_registry, monkeypatch):
    monkeypatch.setenv("ARGOCD_LAB_URL", "https://argocd-lab.example.test")
    monkeypatch.setenv("ARGOCD_LAB_TOKEN", "token-lab")

    assert clusters.clusters() == ["of", "lab"]
    assert clusters.environments() == ["production", "staging"]
    assert clusters.cluster_for("staging") == "lab"
    assert clusters.cluster_for("production") == "of"
    assert clusters.argocd_for("lab") == {"url": "https://argocd-lab.example.test", "token": "token-lab"}

    lab_api = clusters.services_for("staging")["eks"]["of-api"]
    assert lab_api["values_file"] == "charts/of-api/values-staging.yaml"
    assert lab_api["argocd_app"] == "of-api-staging"
    assert clusters.cluster_for_app("of-api-staging") == "lab"
    assert clusters.cluster_for_app("of-api") == "of"


def test_duplicate_environment_across_clusters_is_rejected(tmp_path):
    data = {
        "clusters": {
            "of": {"argocd_url_env": "A", "argocd_token_env": "B", "environments": ["production"], "services": {}},
            "lab": {"argocd_url_env": "C", "argocd_token_env": "D", "environments": ["production"], "services": {}},
        }
    }
    with pytest.raises(clusters.RegistryError, match="listed by clusters"):
        clusters.load(write_registry(tmp_path / "dup.json", data))


def test_cluster_without_argocd_env_names_is_rejected(tmp_path):
    data = {"clusters": {"of": {"environments": ["production"], "services": {}}}}
    with pytest.raises(clusters.RegistryError, match="argocd_url_env"):
        clusters.load(write_registry(tmp_path / "bad.json", data))
