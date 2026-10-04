"""Login and logout through the real routes, with the user store stubbed."""

import importlib

import pytest

auth_routes = importlib.import_module("of_launch.routes.auth")


@pytest.fixture
def demo_user(monkeypatch):
    def verify_user(username, password):
        if (username, password) == ("demo", "demo"):
            return True, "admin"
        return False, "Invalid username or password"

    monkeypatch.setattr(auth_routes, "verify_user", verify_user)


def test_valid_login_sets_the_session_and_redirects_home(client, demo_user):
    resp = client.post("/login", data={"username": "demo", "password": "demo"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    with client.session_transaction() as session:
        assert (session["logged_in"], session["username"], session["role"]) == (True, "demo", "admin")


def test_login_lands_on_the_deploy_dashboard(client, demo_user):
    resp = client.post("/login", data={"username": "demo", "password": "demo"}, follow_redirects=True)
    assert resp.status_code == 200
    assert resp.request.path == "/deploy"
    assert b'href="/logout"' in resp.data


def test_wrong_password_stays_on_the_login_page(client, demo_user):
    resp = client.post("/login", data={"username": "demo", "password": "wrong"})
    assert resp.status_code == 200
    assert b"Login failed: Invalid username or password" in resp.data
    with client.session_transaction() as session:
        assert "logged_in" not in session


def test_missing_password_never_reaches_the_user_store(client, monkeypatch):
    def verify_user(*_args):
        raise AssertionError("verify_user called without a password")

    monkeypatch.setattr(auth_routes, "verify_user", verify_user)
    resp = client.post("/login", data={"username": "demo"})
    assert resp.status_code == 200
    assert b"Please enter both username and password." in resp.data


def test_login_page_redirects_a_logged_in_user_home(logged_in_client):
    resp = logged_in_client.get("/login")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_home_sends_a_logged_in_user_to_the_deploy_page(logged_in_client):
    resp = logged_in_client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/deploy"


def test_deploy_page_shows_the_user_and_logout(logged_in_client):
    resp = logged_in_client.get("/deploy")
    assert resp.status_code == 200
    assert b"tester" in resp.data
    assert b'href="/logout"' in resp.data


def test_logout_clears_the_session(logged_in_client):
    resp = logged_in_client.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"
    assert logged_in_client.get("/deploy").headers["Location"] == "/login"
