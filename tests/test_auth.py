import uuid


def register(client, *, role="ELEVE", email=None, password="motdepasse123"):
    email = email or f"user-{uuid.uuid4().hex}@example.com"
    return email, client.post(
        "/inscription",
        data={"nom": "Utilisateur Test", "email": email, "mot_de_passe": password, "role": role},
    )


def login(client, email, password="motdepasse123"):
    return client.post("/connexion", data={"email": email, "mot_de_passe": password})


def test_student_and_teacher_registration(client):
    student_email, student_response = register(client, role="ELEVE")
    teacher_email, teacher_response = register(client, role="PROFESSEUR")
    assert student_response.status_code == 302
    assert teacher_response.status_code == 302
    assert login(client, teacher_email).status_code == 302
    assert client.get("/professeur").status_code == 200
    assert student_email != teacher_email


def test_duplicate_email_and_invalid_registration(client):
    email, response = register(client)
    assert response.status_code == 302
    assert register(client, email=email)[1].status_code == 200
    assert register(client, role="ADMIN")[1].status_code == 200
    assert register(client, password="court")[1].status_code == 200


def test_login_wrong_password_and_session(client):
    email, _ = register(client)
    assert login(client, email, "mauvais-mot-de-passe").status_code == 200
    response = login(client, email)
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["role"] == "ELEVE"
        assert "utilisateur_id" in session
    assert client.get("/dashboard").status_code == 302
    assert client.get("/deconnexion").status_code == 302
    with client.session_transaction() as session:
        assert not session


def test_protected_endpoints_require_authentication(client):
    for path in ("/dashboard", "/eleve", "/professeur", "/rendre_copie"):
        response = client.get(path) if path != "/rendre_copie" else client.post(path)
        assert response.status_code in {302, 400}
        if response.status_code == 302:
            assert "/connexion" in response.location


def test_role_redirects_prevent_cross_dashboard_access(client):
    student_email, _ = register(client, role="ELEVE")
    login(client, student_email)
    assert client.get("/professeur").status_code == 302
    client.get("/deconnexion")
    teacher_email, _ = register(client, role="PROFESSEUR")
    login(client, teacher_email)
    assert client.get("/eleve").status_code == 302
