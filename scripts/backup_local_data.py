"""Create a timestamped ZIP backup without modifying local data."""

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="database/classexp.db")
    parser.add_argument("--uploads", default="uploads")
    parser.add_argument("--output", default="backup")
    args = parser.parse_args()
    database = Path(args.database).resolve()
    uploads = Path(args.uploads).resolve()
    output = Path(args.output).resolve()
    if not database.is_file():
        raise SystemExit(f"Base SQLite introuvable: {database}")
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    staging = output / f"classexp-{timestamp}"
    staging.mkdir()
    shutil.copy2(database, staging / "classexp.db")
    if uploads.is_dir():
        shutil.copytree(uploads, staging / "uploads")
    archive = shutil.make_archive(str(staging), "zip", staging)
    shutil.rmtree(staging)
    print(f"Backup cree: {archive}")


if __name__ == "__main__":
    main()
