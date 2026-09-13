import pytest

from database import redact_database_url, validate_production_database
from storage import validate_production_storage


def test_production_rejects_missing_or_sqlite_database():
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        validate_production_database('production', '')
    with pytest.raises(RuntimeError, match="SQLite n'est pas autorisee"):
        validate_production_database('production', 'sqlite:///lost.db')


def test_production_rejects_local_or_incomplete_object_storage():
    with pytest.raises(RuntimeError, match="stockage local n'est pas autorise"):
        validate_production_storage('production', 'local', {})
    with pytest.raises(RuntimeError, match='incomplete'):
        validate_production_storage('production', 'r2', {})


def test_database_url_redaction_hides_password():
    redacted = redact_database_url('postgresql+psycopg://user:top-secret@db.example/test')
    assert 'top-secret' not in redacted
    assert '***' in redacted
