"""MySQL access: schema setup, users and deployment records."""

import math
from contextlib import contextmanager
from pathlib import Path

import bcrypt
import mysql.connector
from mysql.connector import Error
from mysql.connector.constants import ClientFlag
from mysql.connector.pooling import MySQLConnectionPool

from of_launch.config import settings

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
_FILTER_FIELDS = (
    "environment",
    "user",
    "service_name",
    "image_tag",
    "deployment_type",
    "status",
    "deployment_time_start",
    "deployment_time_end",
)
_pool = None


def _connect(database=None):
    return mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=database,
        connect_timeout=5,
    )


def _get_connection():
    global _pool
    if _pool is None:
        _pool = MySQLConnectionPool(
            pool_name="of_launch",
            pool_size=5,
            pool_reset_session=True,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            connect_timeout=5,
            client_flags=[ClientFlag.FOUND_ROWS],
        )
    return _pool.get_connection()


@contextmanager
def _pooled_cursor(dictionary=False):
    connection = _get_connection()
    try:
        cursor = connection.cursor(dictionary=dictionary)
        try:
            yield connection, cursor
        finally:
            cursor.close()
    finally:
        connection.close()


def _schema(name):
    template = (_SQL_DIR / name).read_text(encoding="utf-8")
    return template.format(users=settings.TABLE_NAME_USERS, deployments=settings.TABLE_NAME_DEPLOYMENTS)


def check_db_connection():
    try:
        connection = _connect()
        if connection.is_connected():
            connection.close()
            return True, "Database connection successful"
    except Error as exc:
        return False, f"Connection failed: {exc}"
    except Exception as exc:
        return False, f"Error: {exc}"
    return False, "Unknown connection error"


def setup_database():
    try:
        connection = _connect()
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {settings.DB_NAME}")
        cursor.execute(f"USE {settings.DB_NAME}")
        cursor.execute(_schema("users.sql"))
        cursor.execute(_schema("deployments.sql"))
        cursor.close()
        connection.close()
        return True, (
            f"Database '{settings.DB_NAME}' and tables "
            f"'{settings.TABLE_NAME_USERS}', '{settings.TABLE_NAME_DEPLOYMENTS}' ready"
        )
    except Error as exc:
        return False, f"Database setup failed: {exc}"
    except Exception as exc:
        return False, f"Setup error: {exc}"


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, hashed_password):
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def _execute(query, params, on_success, not_found=None):
    try:
        with _pooled_cursor() as (connection, cursor):
            cursor.execute(query, params)
            connection.commit()
            affected = cursor.rowcount
        if affected or not_found is None:
            return True, on_success
        return False, not_found
    except Error as exc:
        return False, f"Database error: {exc}"


def create_user(username, password, role=None):
    if role is None:
        role = settings.DEFAULT_ROLE
    try:
        with _pooled_cursor() as (connection, cursor):
            cursor.execute(
                f"INSERT INTO {settings.TABLE_NAME_USERS} (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, hash_password(password), role),
            )
            connection.commit()
        return True, f"User '{username}' created with role '{role}'"
    except mysql.connector.IntegrityError:
        return False, f"Username '{username}' already exists"
    except Error as exc:
        return False, f"Failed to create user: {exc}"
    except Exception as exc:
        return False, f"User creation error: {exc}"


def list_users():
    try:
        with _pooled_cursor(dictionary=True) as (_connection, cursor):
            cursor.execute(
                f"SELECT id, username, role, created_at, last_login FROM {settings.TABLE_NAME_USERS} ORDER BY id"
            )
            users = cursor.fetchall()
        return True, users, f"{len(users)} users found"
    except Error as exc:
        return False, [], f"Failed to list users: {exc}"


def delete_user(username):
    return _execute(
        f"DELETE FROM {settings.TABLE_NAME_USERS} WHERE username = %s",
        (username,),
        f'User "{username}" deleted',
        not_found=f'User "{username}" not found',
    )


def update_user_password(username, new_password):
    return _execute(
        f"UPDATE {settings.TABLE_NAME_USERS} SET password_hash = %s WHERE username = %s",
        (hash_password(new_password), username),
        f'Password updated for "{username}"',
        not_found=f'User "{username}" not found',
    )


def update_user_role(username, new_role):
    return _execute(
        f"UPDATE {settings.TABLE_NAME_USERS} SET role = %s WHERE username = %s",
        (new_role, username),
        f'Role for "{username}" set to "{new_role}"',
        not_found=f'User "{username}" not found',
    )


def verify_user(username, password):
    try:
        with _pooled_cursor() as (connection, cursor):
            cursor.execute(
                f"SELECT id, password_hash, role FROM {settings.TABLE_NAME_USERS} WHERE username = %s", (username,)
            )
            result = cursor.fetchone()
            if result and verify_password(password, result[1]):
                role = result[2] or settings.ROLE_ADMIN
                cursor.execute(
                    f"UPDATE {settings.TABLE_NAME_USERS} SET last_login = NOW() WHERE username = %s", (username,)
                )
                connection.commit()
                return True, role
        return False, "Invalid username or password"
    except Error as exc:
        return False, f"Login verification failed: {exc}"
    except Exception as exc:
        return False, f"Login error: {exc}"


def initialize_app_database():
    success, message = setup_database()
    if not success:
        return False, message
    try:
        connection = _connect(settings.DB_NAME)
        cursor = connection.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {settings.TABLE_NAME_USERS}")
        user_count = cursor.fetchone()[0]
        cursor.close()
        connection.close()
    except Error as exc:
        return False, f"Database initialization check failed: {exc}"
    except Exception as exc:
        return False, f"Initialization error: {exc}"

    if user_count:
        return True, f"Database ready with {user_count} existing users"
    if not (settings.APP_USER and settings.APP_PASSWORD):
        return True, "Database ready, no users yet (set APP_USER and APP_PASSWORD or SEED_USERS)"
    admin_success, admin_message = create_user(settings.APP_USER, settings.APP_PASSWORD, role=settings.ROLE_ADMIN)
    if admin_success:
        return True, f"Database initialized and admin user '{settings.APP_USER}' created"
    return False, f"Database setup OK, but failed to create admin: {admin_message}"


def write_deployment_record(user, environment, service_name, artifact_version, deployment_type="frontend",
                            status="triggered"):
    query = f"""
    INSERT INTO {settings.TABLE_NAME_DEPLOYMENTS}
        (user, environment, service_name, image_tag, artifact_version, deployment_type, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    return _execute(
        query,
        (user, environment, service_name, artifact_version, artifact_version, deployment_type, status),
        f"Deployment record written for {service_name}",
    )


def build_query_filter(query, filters, count_query=False):
    params = []
    where_clauses = []
    for field, value in filters.items():
        if field not in _FILTER_FIELDS:
            continue
        if field == "image_tag":
            where_clauses.append("image_tag LIKE %s")
            params.append(f"%{value}%")
        elif field == "deployment_time_start":
            where_clauses.append("deployment_time >= %s")
            params.append(value)
        elif field == "deployment_time_end":
            where_clauses.append("deployment_time <= %s")
            params.append(value)
        else:
            where_clauses.append(f"{field} = %s")
            params.append(value)
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    if not count_query:
        query += " ORDER BY deployment_time DESC"
    return query, params


def get_total_records_count(filters=None, max_records=None):
    max_records = max_records or settings.MAX_RECORDS
    try:
        if filters:
            filtered_query, params = build_query_filter(f"SELECT * FROM {settings.TABLE_NAME_DEPLOYMENTS}", filters)
            query = f"SELECT COUNT(*) FROM ({filtered_query} LIMIT {max_records}) AS limited_results"
        else:
            query = (
                f"SELECT COUNT(*) FROM (SELECT * FROM {settings.TABLE_NAME_DEPLOYMENTS} "
                f"ORDER BY deployment_time DESC LIMIT {max_records}) AS limited_results"
            )
            params = []
        with _pooled_cursor() as (_connection, cursor):
            cursor.execute(query, params)
            count = cursor.fetchone()[0]
        return True, count, f"Record count fetched successfully (limited to {max_records} latest records)"
    except Error as exc:
        return False, 0, f"Failed to get record count: {exc}"
    except Exception as exc:
        return False, 0, f"Count error: {exc}"


def read_deployment_records(filters=None, page=1, per_page=10, max_records=1000):
    try:
        count_success, total_count, count_message = get_total_records_count(filters, max_records)
        if not count_success:
            return False, [], 0, 0, count_message

        total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1
        offset = (page - 1) * per_page
        if not filters and offset >= max_records:
            return True, [], total_count, total_pages, "No more records available (beyond limit)"

        if filters:
            filtered_query, params = build_query_filter(f"SELECT * FROM {settings.TABLE_NAME_DEPLOYMENTS}", filters)
            query = (
                f"SELECT * FROM ({filtered_query} LIMIT {max_records}) AS limited_results "
                f"ORDER BY deployment_time DESC LIMIT {per_page} OFFSET {offset}"
            )
        else:
            query = (
                f"SELECT * FROM {settings.TABLE_NAME_DEPLOYMENTS} "
                f"ORDER BY deployment_time DESC LIMIT {per_page} OFFSET {offset}"
            )
            params = []
        with _pooled_cursor(dictionary=True) as (_connection, cursor):
            cursor.execute(query, params)
            records = cursor.fetchall()
        message = f"Deployment records fetched successfully (limited to {max_records} latest records)"
        return True, records, total_count, total_pages, message
    except Error as exc:
        return False, [], 0, 0, f"Failed to read deployment records: {exc}"
    except Exception as exc:
        return False, [], 0, 0, f"Read error: {exc}"
