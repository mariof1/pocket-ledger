import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from backup_database import create_backup
from migrations import LATEST_VERSION, MIGRATIONS, migrate


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "ledger.sqlite3"
        self.conn = sqlite3.connect(self.source)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(self.conn.close)

    def test_versions_are_idempotent_and_online_backup_is_consistent(self):
        from app import SCHEMA
        self.assertEqual(migrate(self.conn, SCHEMA), LATEST_VERSION)
        self.assertEqual(migrate(self.conn, SCHEMA), LATEST_VERSION)
        self.assertTrue({"auth_source", "directory_id", "display_name"}.issubset(
            {row["name"] for row in self.conn.execute("PRAGMA table_info(users)")}))
        self.conn.execute("INSERT INTO users(email, password_hash) VALUES('test@example.com', 'hash')")
        self.conn.commit()
        target = Path(self.directory.name) / "backup.sqlite3"
        self.assertEqual(create_backup(self.source, target), target.resolve())
        with closing(sqlite3.connect(target)) as copy:
            self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], LATEST_VERSION)
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            create_backup(self.source, target)
        self.conn.execute("INSERT INTO users(email, password_hash) VALUES('later@example.com', 'hash')")
        self.conn.commit()
        self.conn.close()  # Windows requires the source handle closed before replacing it.
        shutil.copy2(target, self.source)
        with closing(sqlite3.connect(self.source)) as restored:
            self.assertEqual(restored.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)

    def test_failed_upgrade_rolls_back_and_future_versions_are_rejected(self):
        from app import SCHEMA
        with patch.dict(MIGRATIONS, {3: lambda conn: (_ for _ in ()).throw(RuntimeError("test failure"))}):
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                migrate(self.conn, SCHEMA)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertIsNone(self.conn.execute(
            "SELECT name FROM sqlite_master WHERE name='users'").fetchone())
        self.conn.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(RuntimeError, "newer"):
            migrate(self.conn, SCHEMA)


if __name__ == "__main__":
    unittest.main()
