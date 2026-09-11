import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app as application_module


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def register(client, *, name="Camille", role="ELEVE", password="motdepasse123"):
    email = f"{name.lower()}-{id(client)}-{role.lower()}@example.com"
    response = client.post(
        "/inscription",
        data={"nom": name, "email": email, "mot_de_passe": password, "role": role},
    )
    return email, response


def login(client, email, password="motdepasse123"):
    return client.post("/connexion", data={"email": email, "mot_de_passe": password})


def response_status(client, path):
    response = client.get(path)
    try:
        return response.status_code
    finally:
        response.close()


def create_class(client, name="Classe Test"):
    response = client.post("/professeur/classe/nouvelle", data={"nom": name})
    assert response.status_code == 302
    with application_module.app.app_context():
        row = application_module.get_db().execute(
            "SELECT id, code FROM classes ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["id"], row["code"]


def create_assignment(client, class_id, *, opening=None, duration="3600", filename="sujet.pdf"):
    opening = opening or (utc_now() - timedelta(minutes=1)).isoformat(timespec="minutes")
    return client.post(
        "/professeur/devoir/nouveau",
        data={
            "titre": "Contrôle de fonctions",
            "description": "Sujet de test",
            "classe_id": str(class_id),
            "date_ouverture": opening,
            "duree": duration,
            "sujet": (pytest.importorskip("io").BytesIO(b"PDF"), filename),
        },
        content_type="multipart/form-data",
    )


def test_public_pages_and_anonymous_access(client):
    assert client.get("/").status_code == 200
    assert b"Apprendre" in client.get("/").data
    assert client.get("/connexion").status_code == 200
    assert client.get("/inscription").status_code == 200
    for path in ("/dashboard", "/eleve", "/professeur", "/professeur/classe/nouvelle"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/connexion" in response.location


def test_database_constraints_and_foreign_keys(app):
    with app.app_context():
        connection = application_module.get_db()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?)",
                ("Invalide", "bad@example.com", "hash", "ADMIN"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO classe_eleves (classe_id, eleve_id) VALUES (?, ?)",
                (9999, 9999),
            )


def test_init_db_is_explicit_reset(app):
    with app.app_context():
        connection = application_module.get_db()
        connection.execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?)",
            ("Compte", "compte@example.com", "hash", "ELEVE"),
        )
        connection.commit()
    application_module.init_db()
    with app.app_context():
        assert application_module.get_db().execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0] == 0


def test_professor_dashboard_class_creation_and_isolation(professor, app):
    client = professor["client"]
    class_id, code = create_class(client, "Mathématiques")
    response = client.get("/professeur")
    assert response.status_code == 200
    assert b"Math" in response.data and code.encode() in response.data
    other = app.test_client()
    email, _ = register(other, name="AutreProf", role="PROFESSEUR")
    assert login(other, email).status_code == 302
    assert b"Math" not in other.get("/professeur").data
    assert other.get(f"/professeur/devoir/{class_id}/copies").status_code == 404


def test_assignment_creation_upload_and_duration(professor, app):
    client = professor["client"]
    class_id, _ = create_class(client)
    response = create_assignment(client, class_id, duration="18000", filename="Sujet.PDF")
    assert response.status_code == 302
    with app.app_context():
        row = application_module.get_db().execute(
            "SELECT titre, duree, sujet_pdf, date_ouverture FROM devoirs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["duree"] == 18000
    assert row["sujet_pdf"] == "Sujet.PDF"
    assert Path(app.config["UPLOAD_FOLDER"], "sujets", "Sujet.PDF").exists()


def test_assignment_rejects_invalid_file_and_missing_file(professor):
    client = professor["client"]
    class_id, _ = create_class(client)
    assert create_assignment(client, class_id, filename="sujet.exe").status_code == 200
    response = client.post(
        "/professeur/devoir/nouveau",
        data={"titre": "Sans sujet", "classe_id": str(class_id), "date_ouverture": "2026-09-11T10:00", "duree": "3600"},
    )
    assert response.status_code == 200
    assert b"obligatoires" in response.data


def test_student_join_class_and_duplicate_is_idempotent(professor, student, app):
    class_id, code = create_class(professor["client"])
    client = student["client"]
    assert client.post("/eleve/classe/rejoindre", data={"code": code[:3] + "-" + code[3:]}).status_code == 302
    assert client.post("/eleve/classe/rejoindre", data={"code": code}).status_code == 302
    with app.app_context():
        count = application_module.get_db().execute(
            "SELECT COUNT(*) FROM classe_eleves WHERE classe_id = ?", (class_id,)
        ).fetchone()[0]
    assert count == 1
    assert b"Classe Test" in client.get("/eleve").data


def test_student_rejects_unknown_class_code(student):
    response = student["client"].post("/eleve/classe/rejoindre", data={"code": "UNKNOWN"})
    assert response.status_code == 404
    assert b"Code de classe invalide" in response.data


def test_role_permissions_and_logout(professor, student):
    assert professor["client"].get("/eleve").status_code == 302
    assert student["client"].get("/professeur").status_code == 302
    assert professor["client"].get("/deconnexion").status_code == 302
    assert "/connexion" in professor["client"].get("/professeur").location


def test_student_assignment_lifecycle_and_expiration(professor, student, app):
    class_id, _ = create_class(professor["client"])
    with app.app_context():
        code = application_module.get_db().execute("SELECT code FROM classes WHERE id = ?", (class_id,)).fetchone()["code"]
    assert student["client"].post("/eleve/classe/rejoindre", data={"code": code}).status_code == 302
    assert create_assignment(professor["client"], class_id, duration="60").status_code == 302
    with app.app_context():
        assignment = application_module.get_db().execute("SELECT id FROM devoirs ORDER BY id DESC LIMIT 1").fetchone()
        assignment_id = assignment["id"]
    client = student["client"]
    assert client.post(f"/devoir/{assignment_id}/commencer").status_code == 302
    assert client.get(f"/devoir/{assignment_id}").status_code == 200
    assert client.post(f"/devoir/{assignment_id}/commencer").status_code == 302
    with app.app_context():
        application_module.get_db().execute("UPDATE sessions_examen SET heure_debut = ?", ((utc_now() - timedelta(minutes=2)).isoformat(),))
        application_module.get_db().commit()
    response = client.post("/rendre_copie", data={"devoir_id": str(assignment_id), "copie": (pytest.importorskip("io").BytesIO(b"x"), "copy.pdf")}, content_type="multipart/form-data")
    assert response.status_code == 403


def test_student_submission_and_teacher_copies(professor, student, app, file_factory):
    class_id, code = create_class(professor["client"])
    student["client"].post("/eleve/classe/rejoindre", data={"code": code})
    create_assignment(professor["client"], class_id)
    with app.app_context():
        assignment_id = application_module.get_db().execute("SELECT id FROM devoirs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    student["client"].post(f"/devoir/{assignment_id}/commencer")
    response = student["client"].post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), **file_factory("../../copie.pdf", b"copie")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    copies = professor["client"].get(f"/professeur/devoir/{assignment_id}/copies")
    assert copies.status_code == 200 and b"Remise" in copies.data
    assert b".." not in copies.data


def test_upload_types_and_download_path_security(professor, student, app):
    class_id, code = create_class(professor["client"])
    student["client"].post("/eleve/classe/rejoindre", data={"code": code})
    for extension in ("pdf", "jpg", "png", "docx"):
        assert create_assignment(professor["client"], class_id, filename=f"sujet.{extension}").status_code == 302
    assert professor["client"].get("/uploads/../../schema.sql").status_code in {404, 400}


def test_ui_shell_and_static_assets(client):
    home = client.get("/")
    assert home.status_code == 200
    assert b"La classe continue" in home.data
    assert b'id="fonctionnalites"' in home.data
    assert b'href="/connexion"' in home.data
    assert b'href="/inscription"' in home.data
    css = client.get("/static/css/app.css")
    javascript = client.get("/static/js/app.js")
    try:
        assert css.mimetype == "text/css"
        assert javascript.mimetype == "text/javascript"
    finally:
        css.close()
        javascript.close()

    registration = client.get("/inscription")
    assert b'name="role" value="ELEVE"' in registration.data
    assert b'name="role" value="PROFESSEUR"' in registration.data
    assert b"data-password-toggle" in registration.data


def test_uploaded_files_are_limited_to_authorized_users(professor, student, app, file_factory):
    class_id, code = create_class(professor["client"])
    student["client"].post("/eleve/classe/rejoindre", data={"code": code})
    create_assignment(professor["client"], class_id, filename="sujet-prive.pdf")
    with app.app_context():
        assignment_id = application_module.get_db().execute(
            "SELECT id FROM devoirs ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
    student["client"].post(f"/devoir/{assignment_id}/commencer")
    student["client"].post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), **file_factory("copie-privee.pdf")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        copy_name = application_module.get_db().execute(
            "SELECT fichier_copie FROM sessions_examen WHERE devoir_id = ?", (assignment_id,)
        ).fetchone()["fichier_copie"]

    subject_path = "/uploads/sujets/sujet-prive.pdf"
    copy_path = f"/uploads/copies/{assignment_id}/{copy_name}"
    assert response_status(professor["client"], subject_path) == 200
    assert response_status(student["client"], subject_path) == 200
    assert response_status(professor["client"], copy_path) == 200
    assert response_status(student["client"], copy_path) == 200

    stranger = app.test_client()
    stranger_email, _ = register(stranger, name="ProfEtranger", role="PROFESSEUR")
    login(stranger, stranger_email)
    assert response_status(stranger, subject_path) == 403
    assert response_status(stranger, copy_path) == 403
    assert response_status(app.test_client(), copy_path) == 302
