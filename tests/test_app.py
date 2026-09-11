import sqlite3

import pytest

from classexp import db


def test_pages_are_reachable(client):
    for path in ("/", "/connexion"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"ClasseXP" in response.data


def test_private_pages_redirect_anonymous_user(client):
    for path in ("/eleve", "/professeur"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/connexion" in response.headers["Location"]


def test_static_asset_is_reachable(client):
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"


def test_unknown_api_route_returns_json(client):
    response = client.get("/api/inconnue")
    assert response.status_code == 404
    assert response.json == {
        "error": "not_found",
        "message": "Ressource introuvable.",
    }


def test_init_db_creates_schema_and_is_idempotent(app):
    runner = app.test_cli_runner()
    first_result = runner.invoke(args=["init-db"])
    assert first_result.exit_code == 0

    with app.app_context():
        connection = db.get_db()
        connection.execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) "
            "VALUES (?, ?, ?, ?)",
            ("Compte conservé", "conserve@example.com", "hash", "STUDENT"),
        )
        connection.commit()

    second_result = runner.invoke(args=["init-db"])
    assert second_result.exit_code == 0

    with app.app_context():
        connection = db.get_db()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"utilisateurs", "classes", "devoirs", "sessions_examen"} <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0] == 1


def test_database_rejects_invalid_role(app):
    with app.app_context():
        db.init_db()
        with pytest.raises(sqlite3.IntegrityError):
            db.get_db().execute(
                "INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) "
                "VALUES (?, ?, ?, ?)",
                ("Test", "test@example.com", "hash", "INCONNU"),
            )
