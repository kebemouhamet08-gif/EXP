import io
import uuid

import pytest

import app as application_module


@pytest.fixture()
def app(tmp_path):
    application = application_module.app
    application.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        DATABASE=str(tmp_path / "classexp.sqlite"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )
    application_module.init_db()
    yield application
    with application.app_context():
        application_module.close_connection(None)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def professor(client):
    email = f"prof-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/inscription",
        data={"nom": "Professeur Test", "email": email, "mot_de_passe": "motdepasse123", "role": "PROFESSEUR"},
    )
    assert response.status_code == 302
    assert client.post("/connexion", data={"email": email, "mot_de_passe": "motdepasse123"}).status_code == 302
    return {"email": email, "client": client}


@pytest.fixture()
def student(app):
    student_client = app.test_client()
    email = f"eleve-{uuid.uuid4().hex}@example.com"
    response = student_client.post(
        "/inscription",
        data={"nom": "Eleve Test", "email": email, "mot_de_passe": "motdepasse123", "role": "ELEVE"},
    )
    assert response.status_code == 302
    assert student_client.post("/connexion", data={"email": email, "mot_de_passe": "motdepasse123"}).status_code == 302
    return {"email": email, "client": student_client}


@pytest.fixture()
def file_factory():
    def make(name="copie.pdf", content=b"contenu"):
        return {"copie": (io.BytesIO(content), name)}

    return make
