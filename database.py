"""Database boundary for both SQLite development and PostgreSQL production."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from flask import current_app, g
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url

from models import metadata


_engines: dict[str, Engine] = {}


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()


def database_url_from_config(config) -> str:
    if config.get("TESTING") and config.get("DATABASE"):
        return f"sqlite:///{Path(config['DATABASE']).resolve().as_posix()}"
    configured = config.get("DATABASE_URL")
    if configured:
        return configured
    legacy_path = config.get("DATABASE")
    if legacy_path:
        return f"sqlite:///{Path(legacy_path).resolve().as_posix()}"
    return "sqlite:///database/classexp.db"


def database_backend(url: str) -> str:
    return urlsplit(url).scheme.split("+")[0].lower()


def redact_database_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.password:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    username = f"{parsed.username}:***@" if parsed.username else ""
    return parsed._replace(netloc=f"{username}{host}").geturl()


def validate_production_database(environment: str, url: str) -> None:
    if environment != "production":
        return
    if not url:
        raise RuntimeError("DATABASE_URL est obligatoire pour ClasseXP en production.")
    if database_backend(url) == "sqlite":
        raise RuntimeError("SQLite n'est pas autorisee pour ClasseXP en production.")
    if database_backend(url) != "postgresql":
        raise RuntimeError("PostgreSQL est obligatoire pour ClasseXP en production.")


def _engine(url: str) -> Engine:
    engine = _engines.get(url)
    if engine is None:
        options = {"pool_pre_ping": True, "hide_parameters": True}
        if database_backend(url) == "sqlite":
            sqlite_database = make_url(url).database
            if sqlite_database and sqlite_database != ":memory:":
                Path(sqlite_database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            options["connect_args"] = {"check_same_thread": False}
        engine = create_engine(url, **options)
        if database_backend(url) == "sqlite":
            @event.listens_for(engine, "connect")
            def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()
        _engines[url] = engine
    return engine


class RowAdapter:
    def __init__(self, row):
        self._values = dict(row._mapping)
        self._sequence = list(row)

    @staticmethod
    def _normalise(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    def __getitem__(self, key):
        value = self._sequence[key] if isinstance(key, int) else self._values[key]
        return self._normalise(value)

    def keys(self):
        return self._values.keys()


class ResultAdapter:
    def __init__(self, result):
        self._result = result
        self.rowcount = result.rowcount

    def fetchone(self):
        row = self._result.fetchone()
        return RowAdapter(row) if row is not None else None

    def fetchall(self):
        return [RowAdapter(row) for row in self._result.fetchall()]

    def __iter__(self):
        for row in self._result:
            yield RowAdapter(row)


def _portable_statement(statement: str) -> str:
    stripped = statement.strip()
    if re.match(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+", stripped):
        stripped = re.sub(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", stripped)
        stripped += " ON CONFLICT DO NOTHING"
    return stripped


def _bind_qmarks(statement: str, parameters: Iterable | None):
    if parameters is None or isinstance(parameters, dict):
        return statement, parameters or {}
    values = tuple(parameters)
    chunks = statement.split("?")
    if len(chunks) - 1 != len(values):
        raise ValueError("Le nombre de parametres SQL ne correspond pas aux placeholders.")
    pieces = []
    bound = {}
    for index, chunk in enumerate(chunks[:-1]):
        name = f"p{index}"
        pieces.extend((chunk, f":{name}"))
        bound[name] = values[index]
    pieces.append(chunks[-1])
    return "".join(pieces), bound


class Database:
    def __init__(self, connection: Connection):
        self.connection = connection

    def execute(self, statement: str, parameters=None) -> ResultAdapter:
        statement, bound = _bind_qmarks(_portable_statement(statement), parameters)
        return ResultAdapter(self.connection.execute(text(statement), bound))

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def get_db() -> Database:
    db = getattr(g, "_database", None)
    if db is None:
        url = database_url_from_config(current_app.config)
        db = g._database = Database(_engine(url).connect())
    return db


def close_db(_exception=None):
    db = g.pop("_database", None)
    if db is not None:
        db.close()


def create_schema(config, *, drop=False):
    engine = _engine(database_url_from_config(config))
    if drop:
        metadata.drop_all(engine)
    metadata.create_all(engine)


def schema_exists(config) -> bool:
    return inspect(_engine(database_url_from_config(config))).has_table("utilisateurs")


def database_ping(config) -> bool:
    try:
        with _engine(database_url_from_config(config)).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def migration_version(config) -> str:
    engine = _engine(database_url_from_config(config))
    try:
        if not inspect(engine).has_table("alembic_version"):
            return "unversioned"
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    except Exception:
        return "unavailable"
