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


def create_assignment(
    client, class_id, *, opening=None, duration="3600", filename="sujet.pdf",
    title="Contrôle de fonctions", content=b"PDF",
):
    opening = opening or (utc_now() - timedelta(minutes=1)).isoformat(timespec="minutes")
    return client.post(
        "/professeur/devoir/nouveau",
        data={
            "titre": title,
            "description": "Sujet de test",
            "classe_id": str(class_id),
            "date_ouverture": opening,
            "duree": duration,
            "sujet": (pytest.importorskip("io").BytesIO(content), filename),
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
    assert row["sujet_pdf"] != "Sujet.PDF"
    assert row["sujet_pdf"].endswith(".pdf")
    assert len(row["sujet_pdf"]) == 36
    assert Path(app.config["UPLOAD_FOLDER"], "sujets", row["sujet_pdf"]).exists()


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
    response = student["client"].post(
        "/eleve/classe/rejoindre", data={"code": "UNKNOWN"}, follow_redirects=True,
    )
    assert response.status_code == 200
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
    grace_page = client.get(f"/devoir/{assignment_id}")
    assert b"D\xc3\xa9lai de remise" in grace_page.data
    response = client.post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), "copie": (pytest.importorskip("io").BytesIO(b"x"), "copy.pdf")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Copie envoy" in response.data
    with app.app_context():
        application_module.get_db().execute("UPDATE sessions_examen SET heure_debut = ?", ((utc_now() - timedelta(minutes=7)).isoformat(),))
        application_module.get_db().commit()
    response = client.post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), "copie": (pytest.importorskip("io").BytesIO(b"y"), "late.pdf")},
        content_type="multipart/form-data", follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"d\xc3\xa9lai de remise de 5 minutes est" in response.data


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
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Copie envoy" in response.data
    assert b"Copie remise" in response.data
    assert b"Remplacer ma copie" in response.data
    assert b"/copie-deposee" not in response.data
    with app.app_context():
        stored = application_module.get_db().execute(
            "SELECT id, fichier_copie, heure_fin, statut FROM sessions_examen WHERE devoir_id = ?", (assignment_id,)
        ).fetchone()
        stored_copy = stored["fichier_copie"]
        session_id = stored["id"]
    assert stored["statut"] == "TERMINE"
    assert stored["heure_fin"] is not None
    assert stored_copy.endswith(".pdf")
    assert len(stored_copy) == 36
    assert Path(app.config["UPLOAD_FOLDER"], "copies", str(assignment_id), stored_copy).exists()
    copies = professor["client"].get(f"/professeur/devoir/{assignment_id}/copies")
    assert copies.status_code == 200 and b"Remise" in copies.data
    assert b".." not in copies.data
    grade = professor["client"].post(
        f"/professeur/session/{session_id}/noter",
        data={"note": "16", "commentaire": "Bon travail"}, follow_redirects=True,
    )
    assert grade.status_code == 200
    assert b"Note et correction enregistr" in grade.data


def test_repeated_copy_names_receive_distinct_storage_names(professor, student, app, file_factory):
    class_id, code = create_class(professor["client"])
    student["client"].post("/eleve/classe/rejoindre", data={"code": code})
    create_assignment(professor["client"], class_id)
    with app.app_context():
        assignment_id = application_module.get_db().execute(
            "SELECT id FROM devoirs ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
    student["client"].post(f"/devoir/{assignment_id}/commencer")

    student["client"].post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), **file_factory("copie.pdf", b"premiere")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        first_name = application_module.get_db().execute(
            "SELECT fichier_copie FROM sessions_examen WHERE devoir_id = ?", (assignment_id,)
        ).fetchone()["fichier_copie"]

    student["client"].post(
        "/rendre_copie",
        data={"devoir_id": str(assignment_id), **file_factory("copie.pdf", b"seconde")},
        content_type="multipart/form-data",
    )
    with app.app_context():
        second_name = application_module.get_db().execute(
            "SELECT fichier_copie FROM sessions_examen WHERE devoir_id = ?", (assignment_id,)
        ).fetchone()["fichier_copie"]

    copy_folder = Path(app.config["UPLOAD_FOLDER"], "copies", str(assignment_id))
    assert first_name != second_name
    assert (copy_folder / first_name).read_bytes() == b"premiere"
    assert (copy_folder / second_name).read_bytes() == b"seconde"


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
        assert b"toast--success" in css.data
        assert b"data-toast-close" in javascript.data
        assert b"Vous avez 5 minutes" in javascript.data
    finally:
        css.close()
        javascript.close()

    registration = client.get("/inscription")
    assert b'name="role" value="ELEVE"' in registration.data
    assert b'name="role" value="PROFESSEUR"' in registration.data
    assert b"data-password-toggle" in registration.data
    assert b"data-toast-container" in registration.data


def test_professor_creation_actions_use_success_toasts(professor, app):
    client = professor["client"]
    created_class = client.post(
        "/professeur/classe/nouvelle", data={"nom": "Classe Toast"}, follow_redirects=True,
    )
    assert created_class.status_code == 200
    assert b"Classe cr" in created_class.data and b"toast--success" in created_class.data
    with app.app_context():
        class_id = application_module.get_db().execute(
            "SELECT id FROM classes WHERE nom = 'Classe Toast'"
        ).fetchone()["id"]
    created_assignment = create_assignment(client, class_id, title="Devoir Toast")
    assert created_assignment.status_code == 302
    dashboard = client.get(created_assignment.location)
    assert b"Devoir cr" in dashboard.data and b"toast--success" in dashboard.data


def test_confirmation_route_was_removed(client):
    assert client.get("/copie-deposee").status_code == 404


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

    with app.app_context():
        subject_name = application_module.get_db().execute(
            "SELECT sujet_pdf FROM devoirs WHERE id = ?", (assignment_id,)
        ).fetchone()["sujet_pdf"]
    subject_path = f"/uploads/sujets/{subject_name}"
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


def test_identical_subject_names_never_overwrite_each_other(professor, app):
    professor_a = professor["client"]
    class_a, _ = create_class(professor_a, "Classe A")

    professor_b = app.test_client()
    email_b, _ = register(professor_b, name="ProfB", role="PROFESSEUR")
    login(professor_b, email_b)
    class_b, _ = create_class(professor_b, "Classe B")

    create_assignment(
        professor_a, class_a, filename="controle.pdf", title="Sujet A", content=b"contenu-A",
    )
    create_assignment(
        professor_b, class_b, filename="controle.pdf", title="Sujet B", content=b"contenu-B",
    )
    create_assignment(
        professor_a, class_a, filename="controle.pdf", title="Sujet A bis", content=b"contenu-A-bis",
    )

    with app.app_context():
        rows = application_module.get_db().execute(
            "SELECT titre, sujet_pdf FROM devoirs ORDER BY id"
        ).fetchall()
    stored_names = [row["sujet_pdf"] for row in rows]
    assert len(set(stored_names)) == 3
    assert all(name.endswith(".pdf") and len(name) == 36 for name in stored_names)

    subject_folder = Path(app.config["UPLOAD_FOLDER"], "sujets")
    assert (subject_folder / rows[0]["sujet_pdf"]).read_bytes() == b"contenu-A"
    assert (subject_folder / rows[1]["sujet_pdf"]).read_bytes() == b"contenu-B"
    assert (subject_folder / rows[2]["sujet_pdf"]).read_bytes() == b"contenu-A-bis"

    path_a = f'/uploads/sujets/{rows[0]["sujet_pdf"]}'
    path_b = f'/uploads/sujets/{rows[1]["sujet_pdf"]}'
    assert response_status(professor_a, path_a) == 200
    assert response_status(professor_b, path_b) == 200
    assert response_status(professor_a, path_b) == 403
    assert response_status(professor_b, path_a) == 403
