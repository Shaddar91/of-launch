"""MySQL access: query building always; users, deployments and the pages that read them when DB_HOST is set."""

from datetime import datetime

from of_launch.config import settings
from of_launch.utils import db


def test_query_filter_keeps_only_known_fields():
    query, params = db.build_query_filter(
        "SELECT * FROM deployments", {"environment": "production", "environment = 1 OR 1": "x"}
    )
    assert query == "SELECT * FROM deployments WHERE environment = %s ORDER BY deployment_time DESC"
    assert params == ["production"]


def test_query_filter_matches_tags_by_substring_and_time_by_range():
    start, end = datetime(2026, 9, 1), datetime(2026, 9, 30)
    query, params = db.build_query_filter(
        "SELECT COUNT(*) FROM deployments",
        {"image_tag": "abc", "deployment_time_start": start, "deployment_time_end": end},
        count_query=True,
    )
    assert query == (
        "SELECT COUNT(*) FROM deployments "
        "WHERE image_tag LIKE %s AND deployment_time >= %s AND deployment_time <= %s"
    )
    assert params == ["%abc%", start, end]


def test_initialize_creates_the_first_admin_once(mysql_db, monkeypatch):
    monkeypatch.setattr(settings, "APP_USER", "demo")
    monkeypatch.setattr(settings, "APP_PASSWORD", "demo")
    assert db.initialize_app_database() == (True, "Database initialized and admin user 'demo' created")
    assert db.initialize_app_database() == (True, "Database ready with 1 existing users")
    assert db.verify_user("demo", "demo") == (True, "admin")


def test_verify_user_checks_the_password_and_records_the_login(mysql_db):
    db.create_user("ops", "s3cret", role="production-executor")
    assert db.verify_user("ops", "wrong") == (False, "Invalid username or password")
    assert db.verify_user("nobody", "s3cret") == (False, "Invalid username or password")
    assert db.verify_user("ops", "s3cret") == (True, "production-executor")
    _ok, users, _message = db.list_users()
    assert [(user["username"], user["last_login"] is not None) for user in users] == [("ops", True)]


def test_failed_writes_hand_their_connections_back(mysql_db):
    db.create_user("demo", "demo")
    for _ in range(10):
        assert db.create_user("demo", "demo") == (False, "Username 'demo' already exists")
        assert db.write_deployment_record("ghost", "production", "of-api", "v1")[0] is False
    assert db.verify_user("demo", "demo") == (True, "admin")


def test_user_changes_report_unknown_users_only(mysql_db):
    db.create_user("demo", "demo")
    assert db.update_user_role("demo", "admin") == (True, 'Role for "demo" set to "admin"')
    assert db.update_user_role("demo", "shared-executor") == (True, 'Role for "demo" set to "shared-executor"')
    assert db.update_user_password("demo", "new-pass") == (True, 'Password updated for "demo"')
    assert db.verify_user("demo", "new-pass") == (True, "shared-executor")
    assert db.update_user_password("nobody", "x") == (False, 'User "nobody" not found')
    assert db.delete_user("nobody") == (False, 'User "nobody" not found')
    assert db.delete_user("demo") == (True, 'User "demo" deleted')
    assert db.list_users()[1] == []


def test_deployment_records_filter_and_page(mysql_db):
    db.create_user("demo", "demo")
    for tag in ("master-aaa", "master-bbb", "master-ccc"):
        db.write_deployment_record("demo", "production", "of-api", tag, deployment_type="eks", status="completed")
    db.write_deployment_record("demo", "production", "of-web", "production/of-web/build_1.tar.gz")

    ok, records, total, pages, _message = db.read_deployment_records({"service_name": "of-api"}, page=1, per_page=2)
    assert (ok, total, pages, len(records)) == (True, 3, 2, 2)
    assert {record["deployment_type"] for record in records} == {"eks"}

    ok, records, total, pages, _message = db.read_deployment_records(page=2, per_page=3)
    assert (ok, total, pages, len(records)) == (True, 4, 2, 1)


def test_deleting_a_user_keeps_their_deployments(mysql_db):
    db.create_user("demo", "demo")
    db.write_deployment_record("demo", "production", "of-api", "master-aaa", deployment_type="eks")
    db.delete_user("demo")
    _ok, records, total, _pages, _message = db.read_deployment_records()
    assert total == 1
    assert records[0]["user"] is None


def test_login_against_mysql_reaches_the_dashboard(mysql_db, client):
    db.create_user("demo", "demo")
    resp = client.post("/login", data={"username": "demo", "password": "demo"}, follow_redirects=True)
    assert resp.request.path == "/deploy"
    assert b'href="/logout"' in resp.data


def test_history_page_lists_deployments_including_deleted_users(mysql_db, logged_in_client):
    db.create_user("tester", "pw")
    db.create_user("gone", "pw")
    db.write_deployment_record("tester", "production", "of-api", "master-aaa", deployment_type="eks")
    db.write_deployment_record("gone", "production", "of-web", "production/of-web/build_1.tar.gz")
    db.delete_user("gone")
    resp = logged_in_client.get("/deployment-history")
    assert resp.status_code == 200
    assert b"master-aaa" in resp.data
    assert b"build_1.tar.gz" in resp.data


def test_db_status_reports_the_connection(mysql_db, client):
    resp = client.get("/db-status")
    assert resp.status_code == 200
    assert resp.get_json()["connected"] is True
