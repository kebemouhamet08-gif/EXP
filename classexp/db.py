"""Accès SQLite et commandes de gestion de la base."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import Flask, current_app, g
from flask.cli import with_appcontext


def get_db() -> sqlite3.Connection:
    """Retourne une connexion propre au contexte de requête courant."""
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    """Ferme la connexion éventuelle à la fin du contexte Flask."""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    """Crée le schéma initial dans la base configurée."""
    schema_path = Path(current_app.root_path).parent / "schema.sql"
    get_db().executescript(schema_path.read_text(encoding="utf-8"))


@click.command("init-db")
@with_appcontext
def init_db_command() -> None:
    """Crée les tables absentes sans effacer les données existantes."""
    init_db()
    click.echo("Base de données ClasseXP initialisée.")


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
