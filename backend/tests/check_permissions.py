"""Integration test executed inside API with runtime credentials."""
import psycopg
from app.database import connection_kwargs

with psycopg.connect(**connection_kwargs()) as conn:
    flags = conn.execute("SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
    assert flags == (False, False, False), flags
    assert conn.execute("SELECT version_num FROM app.alembic_version").fetchone()
    for statement in (
        "CREATE TABLE app._permission_probe (id integer)",
        "CREATE TABLE public._permission_probe (id integer)",
        "CREATE SCHEMA _permission_probe",
        "UPDATE app.alembic_version SET version_num=version_num",
    ):
        try:
            with conn.transaction():
                conn.execute(statement)
                raise AssertionError("Runtime unexpectedly allowed DDL or migration mutation")
        except psycopg.errors.InsufficientPrivilege:
            pass
print("PASS: runtime can read migration metadata; cannot perform DDL or change migration version")
