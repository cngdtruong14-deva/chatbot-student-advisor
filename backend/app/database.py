import os
import psycopg


def connection_kwargs():
    return {
        "host": os.environ.get("DB_HOST", "db"),
        "dbname": os.environ.get("DB_NAME", "student_advisor"),
        "user": os.environ.get("DB_USER", "advisor_app"),
        "password": os.environ["DB_PASSWORD"],
        "connect_timeout": 3,
        "options": "-c statement_timeout=3000",
    }


def check_database():
    with psycopg.connect(**connection_kwargs()) as connection:
        row = connection.execute("SELECT version_num FROM app.alembic_version").fetchone()
        if row is None:
            raise RuntimeError("Database migration missing")
        return row[0]
