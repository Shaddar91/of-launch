"""Shared fixtures: mock mode, a temp batch store, the registries, a throwaway MySQL database when DB_HOST is set."""

import json
import os
import tempfile
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = REPO_DIR / "config" / "clusters.json"
TEST_DB_NAME = "of_launch_test"

os.environ["MOCK_MODE"] = "true"
os.environ["APP_SECRET_KEY"] = "test-secret"
os.environ["OF_CLUSTERS_CONFIG_PATH"] = str(DEFAULT_REGISTRY)
os.environ["OF_BATCH_STORE_DIR"] = tempfile.mkdtemp(prefix="of-launch-tests-")
os.environ["OF_ARTIFACT_BUCKET"] = "test-artifact-bucket"

from of_launch import create_app  # noqa: E402
from of_launch.config import clusters, settings  # noqa: E402
from of_launch.utils import db  # noqa: E402


def write_registry(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run_sql(*statements):
    connection = db._connect()
    try:
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
        connection.commit()
        cursor.close()
    finally:
        connection.close()


@pytest.fixture(scope="session")
def mysql_database():
    if not os.getenv("DB_HOST"):
        pytest.skip("DB_HOST is not set: the MySQL tests need a server")
    patch = pytest.MonkeyPatch()
    patch.setattr(settings, "DB_NAME", TEST_DB_NAME)
    patch.setattr(db, "_pool", None)
    _run_sql(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
    ok, message = db.setup_database()
    assert ok, message
    yield TEST_DB_NAME
    _run_sql(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}")
    patch.undo()


@pytest.fixture
def mysql_db(mysql_database):
    _run_sql(
        f"DELETE FROM {mysql_database}.{settings.TABLE_NAME_DEPLOYMENTS}",
        f"DELETE FROM {mysql_database}.{settings.TABLE_NAME_USERS}",
    )
    return mysql_database


@pytest.fixture
def registry():
    clusters.reload(str(DEFAULT_REGISTRY))
    yield clusters.registry()
    clusters.reload(str(DEFAULT_REGISTRY))


@pytest.fixture
def two_cluster_registry(tmp_path):
    data = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    data["clusters"]["lab"] = {
        "display_name": "Lab cluster",
        "argocd_url_env": "ARGOCD_LAB_URL",
        "argocd_token_env": "ARGOCD_LAB_TOKEN",
        "environments": ["staging"],
        "services": {
            "eks": {
                "of-api": {
                    "display_name": "OF API (Flask)",
                    "ecr_repo": "of-api",
                    "helm_repo": "of-helm",
                    "helm_branch": "develop",
                    "values_file": "charts/of-api/values-{environment}.yaml",
                    "argocd_app": "of-api-{environment}",
                }
            }
        },
    }
    path = write_registry(tmp_path / "clusters.json", data)
    clusters.reload(str(path))
    yield data
    clusters.reload(str(DEFAULT_REGISTRY))


@pytest.fixture
def app(registry):
    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["username"] = "tester"
        session["role"] = "admin"
    return client
