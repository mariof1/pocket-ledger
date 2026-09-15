"""Create a consistent online SQLite backup without loading or migrating the app."""

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def create_backup(database, destination):
    source = Path(database).resolve()
    target = Path(destination).resolve()
    if not source.is_file():
        raise ValueError(f"Database does not exist: {source}")
    if target == source or target.exists():
        raise ValueError("Choose a new backup filename different from the source database.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    if temporary.exists():
        raise ValueError(f"An incomplete backup already exists: {temporary}")
    try:
        with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(temporary)) as backup:
            live.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("The backup failed its integrity check.")
            if backup.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("The backup contains foreign-key errors.")
        temporary.rename(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description="Create and verify an online Pocket Ledger backup")
    instance = Path(os.environ.get("LEDGER_INSTANCE", Path(__file__).parent / "instance"))
    parser.add_argument("--database", type=Path, default=instance / "ledger.sqlite3")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.database.parent / "backups" / (
        "ledger-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".sqlite3")
    print(create_backup(args.database, output))


if __name__ == "__main__":
    main()
