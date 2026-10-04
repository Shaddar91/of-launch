"""Artifact browser, dependency resolver and deployers in mock mode."""

from of_launch.services import artifact_browser, dependency_resolver
from of_launch.services.eks_deployer import deploy_eks
from of_launch.services.frontend_deployer import deploy_frontend


def test_frontend_artifacts_use_the_registry_prefix_and_root_bucket(registry):
    result = artifact_browser.list_frontend_artifacts("production", "of-web")
    assert result["source"] == "s3://test-artifact-bucket/production/of-web/"
    assert result["mock"] is True and len(result["artifacts"]) == 10
    assert set(result) == {"environment", "service", "artifact_type", "source", "artifacts", "mock"}


def test_unknown_service_is_an_error(registry):
    assert artifact_browser.list_worker_artifacts("production", "nope")["error"].startswith("No worker service")
    assert artifact_browser.list_ecr_images("dev", "of-api")["error"] == "Unknown environment: dev"


def test_list_services_groups_by_deploy_type(registry):
    result = artifact_browser.list_services_for_env("production")
    assert set(result["services"]) == {"frontend", "eks"}
    assert result["cluster"] == "of"


def test_dependencies_resolve_from_the_registry(registry):
    result = dependency_resolver.resolve_dependencies("production", ["of-api"])
    assert result["auto_selected"] == []
    assert result["deploy_order"] == ["eks"]
    assert dependency_resolver.resolve_dependencies("production", ["of-web"]) == {
        "auto_selected": [],
        "deploy_order": [],
        "warnings": [],
    }


def test_eks_deploy_routes_to_the_environment_cluster(registry):
    result = deploy_eks("production", "of-api", "master-abc12345", user="tester")
    assert result["status"] == "completed"
    assert result["cluster"] == "of"
    assert result["argocd_app"] == "of-api"
    assert result["values_file"] == "charts/of-api/values.yaml"
    assert result["mock"] is True
    assert set(result) >= {"deployment_id", "deployment_type", "environment", "cluster", "service", "image_tag"}


def test_eks_deploy_on_the_second_cluster(two_cluster_registry):
    result = deploy_eks("staging", "of-api", "develop-abc12345")
    assert result["cluster"] == "lab"
    assert result["argocd_app"] == "of-api-staging"


def test_frontend_deploy_mock(registry):
    result = deploy_frontend("production", "of-web", "production/of-web/build_abc.tar.gz")
    assert result["status"] == "completed" and result["mock"] is True
    assert result["steps"][1]["detail"].startswith("Sync extracted build to")


def test_deployers_fail_cleanly_on_unknown_service(registry):
    assert deploy_eks("production", "nope", "tag")["status"] == "failed"
    assert deploy_frontend("dev", "of-web", "key")["error"] == "Unknown environment: dev"
