"""Copy an existing ClasseXP SQLite database into an empty PostgreSQL schema."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, inspect, select, text
from werkzeug.security import check_password_hash

from models import (
    classe_eleves,
    classes,
    devoirs,
    fichiers,
    identites_externes,
    metadata,
    sessions_examen,
    utilisateurs,
)


TABLES = [
    utilisateurs,
    identites_externes,
    classes,
    classe_eleves,
    devoirs,
    sessions_examen,
    fichiers,
]
DATE_COLUMNS = {
    "utilisateurs": {"created_at"},
    "identites_externes": {"created_at", "last_login_at"},
    "devoirs": {"date_ouverture"},
    "sessions_examen": {"heure_debut", "heure_fin"},
    "fichiers": {"created_at"},
}


def source_rows(connection, table):
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table.name,)
    ).fetchone()
    if not exists:
        return []
    source_columns = {
        row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')
    }
    wanted = [column.name for column in table.columns if column.name in source_columns]
    rows = []
    for row in connection.execute(
        f'SELECT {", ".join(wanted)} FROM "{table.name}" ORDER BY 1'
    ):
        item = dict(zip(wanted, row))
        for name in DATE_COLUMNS.get(table.name, set()):
            value = item.get(name)
            if value and not isinstance(value, datetime):
                item[name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if table.name == "identites_externes" and "email_verified" in item:
            item["email_verified"] = bool(item["email_verified"])
        rows.append(item)
    return rows


def validate_source(source, collected):
    errors = source.execute("PRAGMA foreign_key_check").fetchall()
    if errors:
        raise RuntimeError(f"La source SQLite contient des FK invalides: {errors}")
    for user in collected["utilisateurs"]:
        if user.get("role") not in {"ELEVE", "PROFESSEUR"}:
            raise RuntimeError(f"Role invalide pour utilisateur {user.get('id')}")


def target_must_be_empty(connection):
    missing = [table.name for table in TABLES if not inspect(connection).has_table(table.name)]
    if missing:
        raise RuntimeError("Executez d'abord 'alembic upgrade head'. Tables absentes: " + ", ".join(missing))
    populated = {
        table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
        for table in TABLES
    }
    populated = {name: count for name, count in populated.items() if count}
    if populated:
        raise RuntimeError(f"La cible n'est pas vide; migration refusee: {populated}")


def verify_target(connection, collected):
    for table in TABLES:
        expected = collected[table.name]
        actual_count = connection.execute(select(func.count()).select_from(table)).scalar_one()
        if actual_count != len(expected):
            raise RuntimeError(f"Comptage incorrect pour {table.name}: {actual_count} != {len(expected)}")
        if "id" in table.c and expected:
            actual_ids = set(connection.execute(select(table.c.id)).scalars())
            expected_ids = {row["id"] for row in expected}
            if actual_ids != expected_ids:
                raise RuntimeError(f"IDs non preserves pour {table.name}")
    orphan_checks = {
        "classes.professeur_id": "SELECT COUNT(*) FROM classes c LEFT JOIN utilisateurs u ON u.id=c.professeur_id WHERE c.professeur_id IS NOT NULL AND u.id IS NULL",
        "classe_eleves": "SELECT COUNT(*) FROM classe_eleves ce LEFT JOIN classes c ON c.id=ce.classe_id LEFT JOIN utilisateurs u ON u.id=ce.eleve_id WHERE c.id IS NULL OR u.id IS NULL",
        "devoirs": "SELECT COUNT(*) FROM devoirs d LEFT JOIN classes c ON c.id=d.classe_id LEFT JOIN utilisateurs u ON u.id=d.professeur_id WHERE c.id IS NULL OR u.id IS NULL",
        "sessions_examen": "SELECT COUNT(*) FROM sessions_examen s LEFT JOIN devoirs d ON d.id=s.devoir_id LEFT JOIN utilisateurs u ON u.id=s.eleve_id WHERE d.id IS NULL OR u.id IS NULL",
        "identites_externes": "SELECT COUNT(*) FROM identites_externes i LEFT JOIN utilisateurs u ON u.id=i.utilisateur_id WHERE u.id IS NULL",
    }
    for label, query in orphan_checks.items():
        if connection.execute(text(query)).scalar_one():
            raise RuntimeError(f"Cle etrangere invalide apres migration: {label}")


def reset_postgres_sequences(connection):
    for table in TABLES:
        if "id" not in table.c:
            continue
        connection.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
            f"EXISTS(SELECT 1 FROM {table.name}))"
        ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="database/classexp.db")
    parser.add_argument("--target-url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-password", action="append", default=[], metavar="EMAIL=PASSWORD")
    args = parser.parse_args()
    source_path = Path(args.source)
    if not source_path.is_file():
        raise SystemExit(f"Source SQLite introuvable: {source_path}")
    source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    collected = {table.name: source_rows(source, table) for table in TABLES}
    validate_source(source, collected)
    for table in TABLES:
        print(f"{table.name}: {len(collected[table.name])}")
    if args.dry_run:
        print("DRY-RUN: aucune ecriture effectuee.")
        return
    if not args.target_url or not args.target_url.startswith("postgresql"):
        raise SystemExit("--target-url PostgreSQL est obligatoire hors dry-run.")
    engine = create_engine(args.target_url, pool_pre_ping=True)
    with engine.begin() as target:
        target_must_be_empty(target)
        for table in TABLES:
            if collected[table.name]:
                target.execute(table.insert(), collected[table.name])
        verify_target(target, collected)
        reset_postgres_sequences(target)
        for check in args.verify_password:
            email, password = check.split("=", 1)
            user = next((row for row in collected["utilisateurs"] if row["email"] == email), None)
            if not user or not user.get("mot_de_passe_hash") or not check_password_hash(user["mot_de_passe_hash"], password):
                raise RuntimeError(f"Verification de mot de passe echouee pour {email}")
    print("Migration validee et commitee.")


if __name__ == "__main__":
    main()
