import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from werkzeug.security import check_password_hash, generate_password_hash

from models import metadata, utilisateurs
from database import _engine, _engines, dispose_engines


def migration_fixture(path):
    connection = sqlite3.connect(path)
    connection.executescript(Path('schema.sql').read_text(encoding='utf-8'))
    password_hash = generate_password_hash('motdepasse123')
    connection.execute(
        "INSERT INTO utilisateurs VALUES (1, 'Prof', 'prof@example.com', ?, 'PROFESSEUR', CURRENT_TIMESTAMP)",
        (password_hash,),
    )
    connection.execute(
        "INSERT INTO utilisateurs VALUES (2, 'Eleve', 'eleve@example.com', ?, 'ELEVE', CURRENT_TIMESTAMP)",
        (generate_password_hash('elevepass123'),),
    )
    connection.execute("INSERT INTO classes VALUES (10, '6A', 1, 'ABC123')")
    connection.execute("INSERT INTO classe_eleves VALUES (10, 2)")
    connection.execute(
        "INSERT INTO devoirs VALUES (20, 'Test', '', 1, 10, 'sujet.pdf', CURRENT_TIMESTAMP, 3600, NULL)"
    )
    connection.execute(
        "INSERT INTO sessions_examen VALUES (30, 2, 20, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'TERMINE', 'copie.pdf', 15, 'Bien')"
    )
    connection.execute(
        "INSERT INTO identites_externes VALUES (40, 2, 'google', 'subject-2', 'eleve@example.com', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    connection.commit()
    connection.close()
    return password_hash


def run_migration(*arguments):
    return subprocess.run(
        [sys.executable, 'scripts/migrate_sqlite_to_postgres.py', *arguments],
        cwd=Path.cwd(), text=True, capture_output=True, check=False,
    )


def test_sqlite_migration_dry_run_reports_every_entity(tmp_path):
    source = tmp_path / 'source.sqlite'
    migration_fixture(source)
    result = run_migration('--source', str(source), '--dry-run')
    assert result.returncode == 0, result.stderr
    for expected in (
        'utilisateurs: 2', 'classes: 1', 'classe_eleves: 1', 'devoirs: 1',
        'sessions_examen: 1', 'identites_externes: 1', 'DRY-RUN',
    ):
        assert expected in result.stdout


def test_sqlite_migration_accepts_admin_users(tmp_path):
    source = tmp_path / 'source.sqlite'
    connection = sqlite3.connect(source)
    connection.executescript(Path('schema.sql').read_text(encoding='utf-8'))
    connection.execute(
        "INSERT INTO utilisateurs VALUES (1, 'Admin', 'admin@example.com', ?, 'ADMIN', CURRENT_TIMESTAMP)",
        (generate_password_hash('adminpass123'),),
    )
    connection.commit()
    connection.close()

    result = run_migration('--source', str(source), '--dry-run')
    assert result.returncode == 0, result.stderr
    assert 'utilisateurs: 1' in result.stdout
    assert 'DRY-RUN' in result.stdout


def test_dispose_engines_clears_engine_cache(tmp_path):
    _engine(f"sqlite:///{tmp_path / 'lifecycle.sqlite'}")
    assert _engines
    dispose_engines()
    assert not _engines


@pytest.mark.skipif(
    not os.environ.get('CLASSEXP_TEST_DATABASE_URL'),
    reason='PostgreSQL reel disponible dans le job CI postgres',
)
def test_sqlite_to_real_postgres_preserves_ids_hashes_and_relations(tmp_path):
    target_url = os.environ['CLASSEXP_TEST_DATABASE_URL']
    target = create_engine(target_url)
    try:
        metadata.drop_all(target)
        metadata.create_all(target)
        source = tmp_path / 'source.sqlite'
        expected_hash = migration_fixture(source)
        result = run_migration('--source', str(source), '--target-url', target_url)
        assert result.returncode == 0, result.stdout + result.stderr
        with target.connect() as connection:
            assert connection.execute(select(func.count()).select_from(utilisateurs)).scalar_one() == 2
            row = connection.execute(
                select(utilisateurs).where(utilisateurs.c.id == 1)
            ).mappings().one()
            assert row['mot_de_passe_hash'] == expected_hash
            assert check_password_hash(row['mot_de_passe_hash'], 'motdepasse123')
    finally:
        target.dispose()
