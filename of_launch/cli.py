"""OF Launch command line: check-config, seed-users, users add|list|delete|reset-password|set-role."""

import argparse
import json
import os
import sys

from of_launch.config import clusters, settings
from of_launch.utils import db


def load_seed_users():
    raw = os.getenv("SEED_USERS", "").strip()
    if raw:
        try:
            return [(user["username"], user["password"], user["role"]) for user in json.loads(raw)]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"WARN: SEED_USERS not usable: {exc}")
    if settings.APP_USER and settings.APP_PASSWORD:
        return [(settings.APP_USER, settings.APP_PASSWORD, settings.DEFAULT_ROLE)]
    return []


def cmd_check_config(_args):
    registry = clusters.registry()
    print("=== OF Launch config ===")
    print(f"MOCK_MODE: {settings.MOCK_MODE}")
    print(f"registry: {settings.CLUSTERS_CONFIG_PATH}")
    for name, entry in registry["clusters"].items():
        print(f"cluster {name}: environments={entry['environments']} argocd_url_env={entry['argocd_url_env']}")
    return 0


def cmd_seed_users(_args):
    ok, message = db.initialize_app_database()
    print(message)
    if not ok:
        return 1
    users = load_seed_users()
    if not users:
        print("No seed users configured")
        return 0
    print(f"Seeding {len(users)} users")
    for username, password, role in users:
        _ok, message = db.create_user(username, password, role=role)
        print(f"  {message}")
    return 0


def cmd_users_add(args):
    ok, message = db.create_user(args.username, args.password, role=args.role)
    print(message)
    return 0 if ok else 1


def cmd_users_list(_args):
    ok, users, message = db.list_users()
    if not ok:
        print(message)
        return 1
    if not users:
        print("No users found.")
        return 0
    print(f'{"ID":<5} {"Username":<20} {"Role":<25} {"Created":<22} {"Last Login":<22}')
    print("-" * 95)
    for user in users:
        created = str(user["created_at"] or "")[:19]
        login = str(user["last_login"] or "never")[:19]
        print(f'{user["id"]:<5} {user["username"]:<20} {user["role"]:<25} {created:<22} {login:<22}')
    return 0


def cmd_users_delete(args):
    ok, message = db.delete_user(args.username)
    print(message)
    return 0 if ok else 1


def cmd_users_reset_password(args):
    ok, message = db.update_user_password(args.username, args.password)
    print(message)
    return 0 if ok else 1


def cmd_users_set_role(args):
    ok, message = db.update_user_role(args.username, args.role)
    print(message)
    return 0 if ok else 1


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m of_launch.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config").set_defaults(func=cmd_check_config)
    commands.add_parser("seed-users").set_defaults(func=cmd_seed_users)

    users = commands.add_parser("users").add_subparsers(dest="users_command", required=True)
    add = users.add_parser("add")
    add.add_argument("username")
    add.add_argument("password")
    add.add_argument("--role", default=settings.DEFAULT_ROLE, choices=settings.VALID_ROLES)
    add.set_defaults(func=cmd_users_add)
    users.add_parser("list").set_defaults(func=cmd_users_list)
    delete = users.add_parser("delete")
    delete.add_argument("username")
    delete.set_defaults(func=cmd_users_delete)
    reset = users.add_parser("reset-password")
    reset.add_argument("username")
    reset.add_argument("password")
    reset.set_defaults(func=cmd_users_reset_password)
    set_role = users.add_parser("set-role")
    set_role.add_argument("username")
    set_role.add_argument("role", choices=settings.VALID_ROLES)
    set_role.set_defaults(func=cmd_users_set_role)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
