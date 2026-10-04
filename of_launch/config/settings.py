"""Runtime settings, every value read from the environment."""

import os


def _env_bool(name, default):
    return os.getenv(name, str(default)).strip().lower() == "true"


def _env_int(name, default):
    return int(os.getenv(name, str(default)))


def _env_list(name, default=None):
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(PACKAGE_DIR)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "deployment_app")
TABLE_NAME_USERS = os.getenv("TABLE_NAME_USERS", "users")
TABLE_NAME_DEPLOYMENTS = os.getenv("TABLE_NAME_DEPLOYMENTS", "deployments")
MAX_RECORDS = _env_int("MAX_RECORDS", 100)
PER_PAGE_DEFAULT = _env_int("PER_PAGE_DEFAULT", 10)

APP_USER = os.getenv("APP_USER")
APP_PASSWORD = os.getenv("APP_PASSWORD")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "local-dev-secret-key-change-in-prod")
FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)

ROLE_ADMIN = "admin"
ROLE_PRODUCTION_EXECUTOR = "production-executor"
ROLE_SHARED_EXECUTOR = "shared-executor"
VALID_ROLES = [ROLE_ADMIN, ROLE_PRODUCTION_EXECUTOR, ROLE_SHARED_EXECUTOR]
DEFAULT_ROLE = os.getenv("APP_USER_ROLE", ROLE_ADMIN)
SHARED_EXECUTOR_ENVIRONMENTS = _env_list("OF_SHARED_EXECUTOR_ENVIRONMENTS")

MOCK_MODE = _env_bool("MOCK_MODE", True)

REGION = os.getenv("OF_REGION", "us-east-1")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("OF_GITHUB_OWNER", "")
SLACK_WEBHOOK_URL = os.getenv("OF_SLACK_WEBHOOK_URL", "")
DISPLAY_TIMEZONE = os.getenv("OF_DISPLAY_TIMEZONE", "Europe/Berlin")

CLUSTERS_CONFIG_PATH = os.getenv(
    "OF_CLUSTERS_CONFIG_PATH", os.path.join(REPO_DIR, "config", "clusters.json")
)
BATCH_STORE_DIR = os.getenv("OF_BATCH_STORE_DIR", "/tmp/of-launch-batches")
CODEDEPLOY_POLL_INTERVAL_SECONDS = _env_int("OF_CODEDEPLOY_POLL_INTERVAL_SECONDS", 20)
CODEDEPLOY_POLL_TIMEOUT_SECONDS = _env_int("OF_CODEDEPLOY_POLL_TIMEOUT_SECONDS", 1800)
DEPLOY_FIRST_SETTLE_SECONDS = _env_int("OF_DEPLOY_FIRST_SETTLE_SECONDS", 60)


def is_mock_mode():
    return MOCK_MODE


def can_deploy_to(role, environment):
    if role != ROLE_SHARED_EXECUTOR:
        return True
    if SHARED_EXECUTOR_ENVIRONMENTS:
        return environment in SHARED_EXECUTOR_ENVIRONMENTS
    return environment != "production"
