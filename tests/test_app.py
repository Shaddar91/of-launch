"""The Flask app: login page, auth guard and the registry-backed API."""


def test_login_page_renders(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"password" in resp.data.lower()


def test_root_redirects_to_login_when_logged_out(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_api_requires_login(client):
    resp = client.get("/api/environments")
    assert resp.status_code == 401


def test_api_environments_names_the_cluster(logged_in_client):
    resp = logged_in_client.get("/api/environments")
    assert resp.status_code == 200
    assert resp.get_json() == {"production": {"cluster": "of"}}


def test_api_services_lists_registry_services(logged_in_client):
    resp = logged_in_client.get("/api/services?env=production")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["cluster"] == "of"
    assert [s["name"] for s in data["services"]["eks"]] == ["of-api"]
    assert [s["name"] for s in data["services"]["frontend"]] == ["of-web"]
    assert set(data["services"]["eks"][0]) == {"name", "display_name", "deploy_type"}


def test_api_services_rejects_unknown_environment(logged_in_client):
    resp = logged_in_client.get("/api/services?env=dev")
    assert resp.status_code == 400
    assert "unknown environment" in resp.get_json()["error"]


def test_api_ecr_artifacts_are_mocked(logged_in_client):
    resp = logged_in_client.get("/api/artifacts/ecr?env=production&service=of-api")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["mock"] is True and data["repository"] == "of-api" and len(data["images"]) > 0
    assert resp.headers["Cache-Control"].startswith("no-cache")


def test_status_page_lists_registry_argocd_apps(logged_in_client):
    resp = logged_in_client.get("/status/api/argocd-apps")
    apps = resp.get_json()["apps"]
    assert [(a["app_name"], a["cluster"], a["environment"]) for a in apps] == [("of-api", "of", "production")]


def test_shared_executor_cannot_deploy_to_production(client):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["username"] = "shared"
        session["role"] = "shared-executor"
    resp = client.post(
        "/api/deploy/eks", json={"env": "production", "service": "of-api", "image_tag": "master-abc12345"}
    )
    assert resp.status_code == 403
