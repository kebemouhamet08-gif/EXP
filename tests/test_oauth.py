import pytest
from authlib.integrations.base_client.errors import OAuthError

import app as application_module


def oauth_profile(provider, subject, email=None, name="Utilisateur OAuth", verified=True):
    return {"provider": provider, "subject": subject, "email": email, "name": name, "email_verified": verified}


def callback(client, monkeypatch, profile, *, method="get"):
    monkeypatch.setattr(application_module, "exchange_external_profile", lambda provider: profile)
    route = f"/auth/{profile['provider']}/callback"
    return client.post(route, data={"code": "mock-code"}) if method == "post" else client.get(route + "?code=mock-code")


def csrf_from(client, path):
    assert client.get(path).status_code == 200
    with client.session_transaction() as flask_session:
        return flask_session["_csrf_token"]


def finish(client, *, name="OAuth Test", email=None, role="ELEVE"):
    token = csrf_from(client, "/auth/finaliser")
    data = {"_csrf_token": token, "nom": name, "role": role}
    if email:
        data["email"] = email
    return client.post("/auth/finaliser", data=data)


@pytest.mark.parametrize("provider", ["google", "facebook", "microsoft"])
def test_external_provider_creates_then_recognizes_stable_identity(client, app, monkeypatch, provider):
    profile = oauth_profile(provider, f"{provider}-stable-sub", f"{provider}@example.com")
    first = callback(client, monkeypatch, profile)
    assert first.status_code == 302 and "/auth/finaliser" in first.location
    assert finish(client, role="PROFESSEUR").status_code == 302
    assert client.get("/professeur").status_code == 200
    client.get("/deconnexion")

    second = callback(client, monkeypatch, {**profile, "name": None, "email": None})
    assert second.status_code == 302 and "/dashboard" in second.location
    assert client.get("/professeur").status_code == 200
    with app.app_context():
        assert application_module.get_db().execute(
            "SELECT COUNT(*) FROM identites_externes WHERE provider = ? AND provider_subject = ?",
            (provider, profile["subject"]),
        ).fetchone()[0] == 1


@pytest.mark.parametrize("email", ["apple@example.com", "relay@privaterelay.appleid.com"])
def test_apple_normal_and_private_relay_email_then_missing_one_time_fields(client, monkeypatch, email):
    profile = oauth_profile("apple", "apple-stable-sub-" + email, email, "Apple Test")
    assert callback(client, monkeypatch, profile, method="post").status_code == 302
    assert finish(client).status_code == 302
    client.get("/deconnexion")
    no_repeat_fields = oauth_profile("apple", profile["subject"], None, None, False)
    assert callback(client, monkeypatch, no_repeat_fields, method="post").status_code == 302
    assert client.get("/eleve").status_code == 200


def test_external_email_collision_is_never_automatically_linked(client, app, monkeypatch):
    client.post("/inscription", data={
        "nom": "Compte local", "email": "same@example.com",
        "mot_de_passe": "motdepasse123", "role": "ELEVE",
    })
    profile = oauth_profile("google", "google-collision", "same@example.com")
    response = callback(client, monkeypatch, profile)
    assert "/auth/lier-compte-existant" in response.location
    with app.app_context():
        assert application_module.get_db().execute("SELECT COUNT(*) FROM identites_externes").fetchone()[0] == 0

    token = csrf_from(client, "/auth/lier-compte-existant")
    linked = client.post("/auth/lier-compte-existant", data={
        "_csrf_token": token, "mot_de_passe": "motdepasse123", "confirm_link": "1",
    })
    assert linked.status_code == 302 and "/mon-compte" in linked.location
    with app.app_context():
        assert application_module.get_db().execute("SELECT COUNT(*) FROM identites_externes").fetchone()[0] == 1


def test_google_to_local_switch_replaces_current_user(client, monkeypatch):
    profile = oauth_profile("google", "google-a", "google-a@example.com", "Google A")
    callback(client, monkeypatch, profile)
    finish(client)
    client.get("/changer-compte")
    client.post("/inscription", data={
        "nom": "Local B", "email": "local-b@example.com",
        "mot_de_passe": "motdepasse123", "role": "ELEVE",
    })
    assert client.post("/connexion", data={"email": "local-b@example.com", "mot_de_passe": "motdepasse123"}).status_code == 302
    page = client.get("/eleve")
    assert b"Local B" in page.data
    assert b"Google A" not in page.data


def test_callback_security_errors(client, monkeypatch):
    assert client.get("/auth/inconnu/callback?code=x").status_code == 404
    assert client.get("/auth/google/callback").status_code == 400
    monkeypatch.setattr(
        application_module, "exchange_external_profile",
        lambda provider: (_ for _ in ()).throw(OAuthError(error="mismatching_state")),
    )
    assert client.get("/auth/google/callback?code=x").status_code == 400
    incomplete = oauth_profile("google", None, "x@example.com")
    assert callback(client, monkeypatch, incomplete).status_code == 400


def test_cannot_link_identity_owned_by_another_user(client, app, monkeypatch):
    profile = oauth_profile("facebook", "facebook-owned", "owner@example.com")
    callback(client, monkeypatch, profile)
    finish(client)
    client.get("/deconnexion")
    client.post("/inscription", data={
        "nom": "Second", "email": "second@example.com",
        "mot_de_passe": "motdepasse123", "role": "ELEVE",
    })
    client.post("/connexion", data={"email": "second@example.com", "mot_de_passe": "motdepasse123"})
    with client.session_transaction() as flask_session:
        flask_session["oauth_link_user_id"] = 2
    assert callback(client, monkeypatch, profile).status_code == 409


def test_oauth_only_account_cannot_unlink_its_last_login_method(client, app, monkeypatch):
    profile = oauth_profile("google", "last-method", "only-google@example.com")
    callback(client, monkeypatch, profile)
    finish(client)
    token = csrf_from(client, "/mon-compte")
    response = client.post("/mon-compte/delier/google", data={"_csrf_token": token})
    assert response.status_code == 409
    with app.app_context():
        assert application_module.get_db().execute(
            "SELECT COUNT(*) FROM identites_externes WHERE provider_subject = 'last-method'"
        ).fetchone()[0] == 1


def test_auth_migration_is_idempotent_and_preserves_users(client, app):
    client.post("/inscription", data={
        "nom": "Avant Migration", "email": "migration@example.com",
        "mot_de_passe": "motdepasse123", "role": "ELEVE",
    })
    application_module.migrate_auth_schema()
    application_module.migrate_auth_schema()
    with app.app_context():
        db = application_module.get_db()
        assert db.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM identites_externes").fetchone()[0] == 0
        if application_module.database_backend(
            application_module.database_url_from_config(app.config)
        ) == "sqlite":
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        else:
            assert db.execute(
                '''SELECT COUNT(*) FROM identites_externes i
                   LEFT JOIN utilisateurs u ON u.id = i.utilisateur_id
                   WHERE u.id IS NULL'''
            ).fetchone()[0] == 0


def test_unconfigured_provider_is_disabled_without_breaking_startup(client):
    page = client.get("/connexion")
    assert page.status_code == 200
    assert b"Non configur" in page.data
    assert client.get("/auth/google").status_code == 503


def test_oauth_only_account_cannot_unlink_its_last_method(client, monkeypatch):
    profile = oauth_profile("microsoft", "msa-personal-stable", "personal@outlook.com")
    callback(client, monkeypatch, profile)
    finish(client)
    token = csrf_from(client, "/mon-compte")
    response = client.post("/mon-compte/delier/microsoft", data={"_csrf_token": token})
    assert response.status_code == 409


def test_unconfigured_providers_are_visible_but_disabled(client):
    page = client.get("/connexion")
    assert page.status_code == 200
    for provider in (b"Google", b"Facebook", b"Apple", b"Microsoft"):
        assert provider in page.data
    assert page.data.count(b"Non configur") == 4
