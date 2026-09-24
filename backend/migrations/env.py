from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from app.database import connection_kwargs

parameters = connection_kwargs()
url = URL.create("postgresql+psycopg", username=parameters["user"],
                 password=parameters["password"], host=parameters["host"],
                 database=parameters["dbname"])
with create_engine(url).connect() as connection:
    # A pristine managed PostgreSQL database does not run the local Docker
    # bootstrap scripts. Create only the migration prerequisites here so the
    # Alembic version table can be created before revision 0001 executes.
    # The compatibility role is deliberately NOLOGIN; Azure runtime uses the
    # managed server administrator configured by IaC.
    with connection.begin():
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.execute(text("""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'advisor_app') THEN
                CREATE ROLE advisor_app NOLOGIN;
              END IF;
            END
            $$
        """))
    context.configure(connection=connection, target_metadata=None, version_table_schema="app")
    with context.begin_transaction():
        context.run_migrations()
