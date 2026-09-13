"""Upload legacy local files and replace DB paths with object storage keys."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from storage import S3CompatibleStorageBackend, StorageError, required_r2_values


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def references(connection):
    for row in connection.execute(text(
        "SELECT id, sujet_pdf FROM devoirs WHERE sujet_pdf IS NOT NULL"
    )).mappings():
        yield "devoirs", row["id"], "sujet_pdf", row["sujet_pdf"], "subjects"
    for row in connection.execute(text(
        "SELECT id, correction_pdf FROM devoirs WHERE correction_pdf IS NOT NULL"
    )).mappings():
        yield "devoirs", row["id"], "correction_pdf", row["correction_pdf"], "corrections"
    for row in connection.execute(text(
        "SELECT id, devoir_id, fichier_copie FROM sessions_examen WHERE fichier_copie IS NOT NULL"
    )).mappings():
        yield "sessions_examen", row["id"], "fichier_copie", row["fichier_copie"], "copies"


def locate(root, table, record_id, old_path, kind, devoir_id=None):
    candidates = [root / old_path]
    if "/" not in old_path and kind in {"subjects", "corrections"}:
        candidates.append(root / ("sujets" if kind == "subjects" else "corrections") / old_path)
    if "/" not in old_path and kind == "copies":
        candidates.extend((root / "copies" / str(devoir_id or "") / old_path, root / "copies" / old_path))
    return next((path for path in candidates if path.is_file()), None)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--uploads", default="uploads")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL ou --database-url est obligatoire.")
    config = {
        "R2_ENDPOINT_URL": os.environ.get("R2_ENDPOINT_URL"),
        "R2_ACCESS_KEY_ID": os.environ.get("R2_ACCESS_KEY_ID"),
        "R2_SECRET_ACCESS_KEY": os.environ.get("R2_SECRET_ACCESS_KEY"),
        "R2_BUCKET": os.environ.get("R2_BUCKET"),
        "R2_REGION": os.environ.get("R2_REGION", "auto"),
    }
    if not args.dry_run and required_r2_values(config):
        raise SystemExit("Credentials R2 incomplets.")
    engine = create_engine(args.database_url, pool_pre_ping=True)
    try:
        root = Path(args.uploads).resolve()
        report = {"FOUND": 0, "MISSING_SOURCE_FILE": 0, "ALREADY_OBJECT_KEY": 0, "MIGRATED": 0}
        storage = S3CompatibleStorageBackend(config) if not args.dry_run else None
        with engine.connect() as connection:
            rows = list(references(connection))
            connection.rollback()
            for table, record_id, column, old_path, kind in rows:
                if old_path.startswith(("subjects/", "copies/", "corrections/")):
                    report["ALREADY_OBJECT_KEY"] += 1
                    continue
                devoir_id = record_id
                if table == "sessions_examen":
                    devoir_id = connection.execute(
                        text("SELECT devoir_id FROM sessions_examen WHERE id=:id"), {"id": record_id}
                    ).scalar_one()
                source = locate(root, table, record_id, old_path, kind, devoir_id)
                if source is None:
                    report["MISSING_SOURCE_FILE"] += 1
                    print(f"MISSING_SOURCE_FILE table={table} id={record_id} path={old_path}")
                    continue
                report["FOUND"] += 1
                if kind == "copies":
                    key = f"copies/devoir-{devoir_id}/session-{record_id}/{source.name}"
                else:
                    key = f"{kind}/devoir-{devoir_id}/{source.name}"
                checksum = sha256(source)
                print(f"FOUND table={table} id={record_id} size={source.stat().st_size} sha256={checksum} -> {key}")
                if args.dry_run:
                    continue
                try:
                    with source.open("rb") as stream:
                        storage.put(key, stream)
                    if not storage.exists(key) or storage.size(key) != source.stat().st_size:
                        raise StorageError("Objet absent ou taille incorrecte apres upload.")
                    with engine.begin() as write_connection:
                        write_connection.execute(
                            text(f"UPDATE {table} SET {column}=:key WHERE id=:id AND {column}=:old"),
                            {"key": key, "id": record_id, "old": old_path},
                        )
                    report["MIGRATED"] += 1
                except Exception:
                    try:
                        storage.delete(key)
                    except StorageError:
                        pass
                    raise
        print("Rapport:", report)
        print("Les fichiers locaux originaux n'ont pas ete supprimes.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
