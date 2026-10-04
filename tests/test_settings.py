"""Role-to-environment policy and the image tag rewrite used for Helm values."""

import pytest

from of_launch.config import settings
from of_launch.utils.github import _update_tag_in_content


@pytest.mark.parametrize(
    ("role", "environment", "allowed"),
    [
        ("admin", "production", True),
        ("production-executor", "production", True),
        ("shared-executor", "production", False),
        ("shared-executor", "staging", True),
    ],
)
def test_can_deploy_to(monkeypatch, role, environment, allowed):
    monkeypatch.setattr(settings, "SHARED_EXECUTOR_ENVIRONMENTS", [])
    assert settings.can_deploy_to(role, environment) is allowed


def test_shared_executor_environments_from_env(monkeypatch):
    monkeypatch.setattr(settings, "SHARED_EXECUTOR_ENVIRONMENTS", ["production"])
    assert settings.can_deploy_to("shared-executor", "production") is True


def test_image_tag_key_matches_the_helm_chart_shape():
    content = 'image:\n  repository: of-api\n  tag: ""\nimageTag: "keep"\n'
    updated = _update_tag_in_content(content, "master-abc", "tag")
    assert 'tag: "master-abc"' in updated
    assert 'imageTag: "keep"' in updated
    with pytest.raises(ValueError):
        _update_tag_in_content("nothing: here\n", "x", "tag")
