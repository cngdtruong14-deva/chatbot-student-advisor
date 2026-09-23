from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from app.database import connection_kwargs

parameters = connection_kwargs()
url = URL.create("postgresql+psycopg", username=parameters["user"],
                 password=parameters["password"], host=parameters["host"],
                 database=parameters["dbname"])
with create_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=None, version_table_schema="app")
    with context.begin_transaction():
        context.run_migrations()
