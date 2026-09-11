from werkzeug.security import check_password_hash

from classexp import db


def csrf(client):
    return client.get("/api/auth/csrf").json["csrf_token"]


def register(client, *, email="eleve@example.com", role="STUDENT", password="mot-de-passe-solide"):
    return client.post(
        "/api/auth/register",
        json={"name": "Camille", "email": email, "password": password, "role": role},
        headers={"X-CSRF-Token": csrf(client)},
    )


def login(client, *, email="eleve@example.com", password="mot-de-passe-solide"):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf(client)},
    )


def test_register_hashes_password(client, app):
    response = register(client)
    assert response.status_code == 201
    assert response.json["role"] == "STUDENT"

    with app.app_context():
        row = db.get_db().execute(
            "SELECT mot_de_passe_hash FROM utilisateurs WHERE email = ?",
            ("eleve@example.com",),
        ).fetchone()
        assert row["mot_de_passe_hash"] != "mot-de-passe-solide"
        assert check_password_hash(row["mot_de_passe_hash"], "mot-de-passe-solide")


def test_register_validates_fields_and_duplicate_email(client):
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    response = register(client, email="incorrect", password="court", role="ADMIN")
    assert response.status_code == 400
    assert set(response.json["fields"]) == {"email", "password", "role"}


def test_mutation_rejects_missing_csrf(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "Camille", "email": "a@example.com", "password": "assez-long-123", "role": "STUDENT"},
    )
    assert response.status_code == 400
    assert response.json["error"] == "invalid_csrf"


def test_login_and_logout(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    assert client.get("/api/auth/me").json["email"] == "eleve@example.com"
    assert client.get("/eleve").status_code == 200

    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_bad_password(client):
    register(client)
    response = login(client, password="mauvais-mot-de-passe")
    assert response.status_code == 401
    assert response.json["error"] == "invalid_credentials"


def test_student_cannot_open_teacher_dashboard(client):
    register(client)
    login(client)
    assert client.get("/professeur").status_code == 403


def test_teacher_cannot_open_student_dashboard(client):
    register(client, email="prof@example.com", role="TEACHER")
    login(client, email="prof@example.com")
    assert client.get("/professeur").status_code == 200
    assert client.get("/eleve").status_code == 403
