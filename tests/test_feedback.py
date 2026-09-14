from datetime import datetime, timedelta, timezone


def _flash_categories(client):
    with client.session_transaction() as session:
        return [category for category, _message in session.get("_flashes", [])]


def _consume_feedback(client, path="/dashboard"):
    response = client.get(path, follow_redirects=True)
    response.close()


def test_base_contains_global_accessible_toast_components(client):
    response = client.get("/connexion")
    try:
        page = response.get_data(as_text=True)
        assert 'data-toast-region' in page
        assert 'aria-label="Notifications"' in page
        assert "static/js/app.js" in page
    finally:
        response.close()


def test_successful_post_flashes_success(professor):
    client = professor["client"]
    _consume_feedback(client)
    response = client.post("/professeur/classe/nouvelle", data={"nom": "Terminale A"})
    assert response.status_code == 302
    assert "success" in _flash_categories(client)


def test_failed_post_flashes_and_renders_error(professor):
    client = professor["client"]
    _consume_feedback(client)
    response = client.post("/professeur/classe/nouvelle", data={"nom": ""})
    try:
        page = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "toast--error" in page
        assert "Le nom de la classe est obligatoire" in page
    finally:
        response.close()


def test_upload_error_never_renders_success_feedback(professor, app):
    client = professor["client"]
    _consume_feedback(client)
    response = client.post("/professeur/classe/nouvelle", data={"nom": "Classe upload"})
    response.close()
    _consume_feedback(client)
    with app.app_context():
        import app as application_module

        class_id = application_module.get_db().execute(
            "SELECT id FROM classes ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]

    opening = (datetime.now(timezone.utc) + timedelta(minutes=5)).replace(tzinfo=None)
    response = client.post(
        "/professeur/devoir/nouveau",
        data={
            "titre": "Sujet sans fichier",
            "classe_id": str(class_id),
            "date_ouverture": opening.isoformat(timespec="minutes"),
            "duree": "3600",
        },
    )
    try:
        page = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "toast--error" in page
        assert "toast--success" not in page
    finally:
        response.close()


def test_oauth_error_renders_error_toast(client):
    response = client.get("/auth/google/callback?error=access_denied")
    try:
        page = response.get_data(as_text=True)
        assert response.status_code == 400
        assert "toast--error" in page
        assert "Connexion impossible" in page
    finally:
        response.close()


def test_feedback_assets_include_loading_validation_and_reduced_motion():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    styles = (root / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "data-action-feedback" in script
    assert "form.checkValidity()" in script
    assert "navigator.onLine" in script
    assert ".spinner" in styles
    assert ".skeleton" in styles
    assert "prefers-reduced-motion: reduce" in styles
