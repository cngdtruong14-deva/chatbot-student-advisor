"""Transactional persistence. Schema creation is exclusively Alembic's responsibility."""
from contextlib import contextmanager
from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from app.database import connection_kwargs


@lru_cache
def engine():
    c = connection_kwargs()
    return create_engine(URL.create("postgresql+psycopg", username=c["user"], password=c["password"],
                         host=c["host"], database=c["dbname"]), pool_pre_ping=True,
                         connect_args={"options": "-c statement_timeout=5000"})


@contextmanager
def transaction():
    with engine().begin() as db:
        yield db


def rows(db, query, **params):
    return [dict(r) for r in db.execute(text(query), params).mappings()]


def one(db, query, **params):
    result = rows(db, query, **params)
    return result[0] if result else None


def run(db, query, **params):
    return db.execute(text(query), params)
