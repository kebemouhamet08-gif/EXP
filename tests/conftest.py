from pathlib import Path
from uuid import uuid4

import pytest

from classexp import create_app
from classexp import db


@pytest.fixture()
def app():
    database_path = Path.cwd() / "instance" / f"test-{uuid4().hex}.sqlite"
    application = create_app(
        {
            "TESTING": True,
            "DATABASE": str(database_path),
            "SECRET_KEY": "test-secret",
        }
    )
    with application.app_context():
        db.init_db()
    yield application
    database_path.unlink(missing_ok=True)


@pytest.fixture()
def client(app):
    return app.test_client()
