import uuid

import app as application_module
from werkzeug.security import check_password_hash


def register(client, *, role="ELEVE", email=None, password="motdepasse123", name="Utilisateur Test"):
    email = email or f"user-{uuid.uuid4().hex}@example.com"
    return email, client.post(
        "/inscription",
        data={"nom": name, "email": email, "mot_de_passe": password, "role": role},
    )


def login(client, email, password="motdepasse123", *, remember=False):
    data = {"email": email, "mot_de_passe": password}
    if remember:
        data["remember"] = "1"
    return client.post("/connexion", data=data)


def test_registration_persists_user_and_hashes_password(client, app):
    email, response = register(client, email="  Camille@Example.COM  ")
    assert response.status_code == 302

    with app.app_context():
        row = application_module.get_db().execute(
            "SELECT nom, email, mot_de_passe_hash, role FROM utilisateurs WHERE email = ?",
            ("camille@example.com",),
        ).fetchone()
    assert row is not None
    assert row["email"] == "camille@example.com"
    assert row["role"] == "ELEVE"
    assert row["mot_de_passe_hash"] != "motdepasse123"
    assert check_password_hash(row["mot_de_passe_hash"], "motdepasse123")


def test_student_and_teacher_registration(client):
    student_email, student_response = register(client, role="ELEVE")
    teacher_email, teacher_response = register(client, role="PROFESSEUR")
    assert student_response.status_code == 302
    assert teacher_response.status_code == 302
    assert login(client, teacher_email).status_code == 302
    assert client.get("/professeur").status_code == 200
    assert student_email != teacher_email


def test_duplicate_email_does_not_create_second_account(client, app):
    email, response = register(client)
    assert response.status_code == 302
    duplicate = register(client, email=email.upper())[1]
    assert duplicate.status_code == 200
    assert b"Un compte existe deja" in duplicate.data
    assert b"Se connecter" in duplicate.data
    with app.app_context():
        count = application_module.get_db().execute(
            "SELECT COUNT(*) FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()[0]
    assert count == 1


def test_registration_rejects_invalid_role_and_short_password(client):
    assert register(client, role="ADMIN")[1].status_code == 200
    assert register(client, password="court")[1].status_code == 200


def test_login_accepts_valid_credentials_and_rejects_invalid_ones(client):
    email, _ = register(client)
    assert login(client, email, "mauvais-mot-de-passe").status_code == 200
    assert login(client, "inconnu@example.com").status_code == 200
    response = login(client, email)
    assert response.status_code == 302
    with client.session_transaction() as flask_session:
        assert flask_session["_user_id"] == "1"
        assert "role" not in flask_session
        assert "mot_de_passe" not in flask_session
    assert client.get("/dashboard").status_code == 302
    assert client.get("/connexion").status_code == 302


def test_user_survives_new_client_and_startup_check(client, app):
    email, _ = register(client)
    application_module.ensure_db_initialized()

    new_client = app.test_client()
    assert login(new_client, email).status_code == 302
    assert new_client.get("/eleve").status_code == 200
    with app.app_context():
        assert application_module.get_db().execute(
            "SELECT COUNT(*) FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()[0] == 1


def test_secret_key_is_stable_between_application_starts(tmp_path, monkeypatch):
    monkeypatch.delenv("CLASSEXP_SECRET_KEY", raising=False)
    monkeypatch.delenv("CLASSEXP_HTTPS", raising=False)
    first = application_module.resolve_secret_key(str(tmp_path))
    second = application_module.resolve_secret_key(str(tmp_path))
    assert first
    assert first == second


def test_remember_cookie_restores_login_in_new_client(client, app):
    email, _ = register(client)
    normal_response = login(client, email)
    assert normal_response.status_code == 302
    assert client.get_cookie("remember_token") is None
    client.get("/deconnexion")

    remembered_response = login(client, email, remember=True)
    assert remembered_response.status_code == 302
    remember_cookie = client.get_cookie("remember_token")
    assert remember_cookie is not None
    assert remember_cookie.expires is not None
    assert remember_cookie.http_only is True
    assert remember_cookie.same_site == "Lax"

    reopened_client = app.test_client()
    reopened_client.set_cookie("remember_token", remember_cookie.value)
    assert reopened_client.get("/eleve").status_code == 200


def test_logout_clears_session_and_remember_cookie(client):
    email, _ = register(client)
    login(client, email, remember=True)
    assert client.get_cookie("remember_token") is not None
    response = client.get("/deconnexion")
    assert response.status_code == 302
    assert client.get_cookie("remember_token") is None
    with client.session_transaction() as flask_session:
        assert not flask_session
    protected = client.get("/eleve")
    assert protected.status_code == 302
    assert "/connexion" in protected.location


def test_protected_endpoints_require_authentication(client):
    for path in ("/dashboard", "/eleve", "/professeur", "/rendre_copie"):
        response = client.get(path) if path != "/rendre_copie" else client.post(path)
        assert response.status_code == 302
        assert "/connexion" in response.location


def test_role_redirects_prevent_cross_dashboard_access(client):
    student_email, _ = register(client, role="ELEVE")
    login(client, student_email)
    assert client.get("/eleve").status_code == 200
    assert client.get("/professeur").status_code == 302
    client.get("/deconnexion")

    teacher_email, _ = register(client, role="PROFESSEUR")
    login(client, teacher_email)
    assert client.get("/professeur").status_code == 200
    assert client.get("/eleve").status_code == 302


def test_kolemm14_remember_switches_to_another_account_and_restores_only_new_user(client, app):
    email_a, _ = register(client, email="kolemm14@example.com", name="Kolemm14")
    email_b, _ = register(client, email="utilisateur-b@example.com", name="Utilisateur B")
    assert login(client, email_a, remember=True).status_code == 302
    assert b"Kolemm14" in client.get("/eleve").data

    switch = client.get("/changer-compte")
    assert switch.status_code == 302 and "switch=1" in switch.location
    assert client.get_cookie("remember_token") is None

    assert login(client, email_b, remember=True).status_code == 302
    dashboard = client.get("/eleve")
    assert b"Utilisateur B" in dashboard.data
    assert b"Kolemm14" not in dashboard.data
    remember_b = client.get_cookie("remember_token")
    assert remember_b is not None

    reopened = app.test_client()
    reopened.set_cookie("remember_token", remember_b.value)
    restored = reopened.get("/eleve")
    assert b"Utilisateur B" in restored.data
    assert b"Kolemm14" not in restored.data


def test_post_login_replaces_authenticated_user_and_a_to_b_to_c_then_logout(client):
    accounts = [(register(client, email=f"switch-{letter}@example.com", name=f"Compte {letter.upper()}")[0], f"Compte {letter.upper()}") for letter in "abc"]
    for email, name in accounts:
        assert login(client, email, remember=True).status_code == 302
        page = client.get("/eleve")
        assert name.encode() in page.data
        assert all(other_name.encode() not in page.data for _, other_name in accounts if other_name != name)
    assert client.get("/deconnexion").status_code == 302
    assert client.get_cookie("remember_token") is None
    with client.session_transaction() as flask_session:
        assert not flask_session
