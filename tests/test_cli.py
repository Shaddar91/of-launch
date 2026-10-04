"""The command line the container entry point runs: check-config and seed-users."""

import json

from of_launch import cli
from of_launch.config import settings
from of_launch.utils import db


def test_check_config_prints_the_registry(registry, capsys):
    assert cli.main(["check-config"]) == 0
    assert "cluster of: environments=['production'] argocd_url_env=ARGOCD_OF_URL" in capsys.readouterr().out


def test_seed_users_come_from_the_json_list(monkeypatch):
    monkeypatch.setenv("SEED_USERS", json.dumps([{"username": "ops", "password": "pw", "role": "shared-executor"}]))
    assert cli.load_seed_users() == [("ops", "pw", "shared-executor")]


def test_unusable_seed_json_falls_back_to_the_app_user(monkeypatch, capsys):
    monkeypatch.setenv("SEED_USERS", "not json")
    monkeypatch.setattr(settings, "APP_USER", "demo")
    monkeypatch.setattr(settings, "APP_PASSWORD", "demo")
    monkeypatch.setattr(settings, "DEFAULT_ROLE", "admin")
    assert cli.load_seed_users() == [("demo", "demo", "admin")]
    assert "SEED_USERS not usable" in capsys.readouterr().out


def test_no_seed_users_without_credentials(monkeypatch):
    monkeypatch.delenv("SEED_USERS", raising=False)
    monkeypatch.setattr(settings, "APP_USER", None)
    assert cli.load_seed_users() == []


def test_seed_users_command_is_safe_to_rerun(mysql_db, monkeypatch):
    monkeypatch.setattr(settings, "APP_USER", "demo")
    monkeypatch.setattr(settings, "APP_PASSWORD", "demo")
    monkeypatch.setenv("SEED_USERS", json.dumps([{"username": "ops", "password": "pw", "role": "shared-executor"}]))
    assert cli.main(["seed-users"]) == 0
    assert cli.main(["seed-users"]) == 0
    assert db.verify_user("demo", "demo") == (True, "admin")
    assert db.verify_user("ops", "pw") == (True, "shared-executor")
