"""Transactional, versioned upgrades for Pocket Ledger SQLite databases."""

from account_ledger import default_account


LATEST_VERSION = 6


def columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def migration_2_recurring_bills(conn):
    bill_columns = columns(conn, "bills")
    if "frequency" not in bill_columns:
        conn.execute("""ALTER TABLE bills ADD COLUMN frequency TEXT NOT NULL DEFAULT 'monthly'
            CHECK(frequency IN ('daily','weekly','biweekly','fourweekly','monthly','quarterly','yearly'))""")
    if "first_due_on" not in bill_columns:
        conn.execute("ALTER TABLE bills ADD COLUMN first_due_on TEXT")


def migration_3_commute_leave(conn):
    commute_columns = columns(conn, "commutes")
    if "leave_mode" not in commute_columns:
        conn.execute("""ALTER TABLE commutes ADD COLUMN leave_mode TEXT NOT NULL DEFAULT 'dates'
            CHECK(leave_mode IN ('dates','annual'))""")
    if "annual_leave_days" not in commute_columns:
        conn.execute("""ALTER TABLE commutes ADD COLUMN annual_leave_days INTEGER NOT NULL DEFAULT 0
            CHECK(annual_leave_days BETWEEN 0 AND 365)""")


def migration_4_accounts(conn):
    if "account_id" not in columns(conn, "transactions"):
        conn.execute("ALTER TABLE transactions ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
    for profile in conn.execute("SELECT id FROM profiles").fetchall():
        account = conn.execute("SELECT id FROM accounts WHERE profile_id = ? ORDER BY id LIMIT 1",
                               (profile["id"],)).fetchone()
        account_id = default_account(conn, profile["id"]) if account else conn.execute(
            "INSERT INTO accounts(profile_id, name, kind) VALUES(?, 'Current account', 'current')",
            (profile["id"],)).lastrowid
        conn.execute("UPDATE transactions SET account_id = ? WHERE profile_id = ? AND account_id IS NULL",
                     (account_id, profile["id"]))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, occurred_on)")


def migration_5_directory_accounts(conn):
    user_columns = columns(conn, "users")
    if "auth_source" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN auth_source TEXT NOT NULL DEFAULT 'local'")
    if "directory_id" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN directory_id TEXT")
    if "display_name" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_users_directory_identity
        ON users(auth_source, directory_id) WHERE directory_id IS NOT NULL""")


def migration_6_directory_photo(conn):
    user_columns = columns(conn, "users")
    if "photo" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN photo BLOB")
    if "photo_mime" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN photo_mime TEXT")
    if "photo_revision" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN photo_revision INTEGER NOT NULL DEFAULT 0")


MIGRATIONS = {
    2: migration_2_recurring_bills,
    3: migration_3_commute_leave,
    4: migration_4_accounts,
    5: migration_5_directory_accounts,
    6: migration_6_directory_photo,
}


def migrate(conn, schema):
    """Apply all missing stages atomically; never open a newer database."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > LATEST_VERSION:
        raise RuntimeError(f"Database version {current} is newer than this app supports ({LATEST_VERSION}).")
    if current == LATEST_VERSION:
        return current
    try:
        # Include BEGIN in executescript: sqlite3 otherwise commits an earlier transaction.
        conn.executescript("BEGIN IMMEDIATE;\n" + schema)
        for version in range(max(current + 1, 2), LATEST_VERSION + 1):
            MIGRATIONS[version](conn)
            conn.execute(f"PRAGMA user_version = {version}")
        for source in ("transactions", "budgets", "bills"):
            conn.execute(f"""INSERT OR IGNORE INTO categories(profile_id, name)
                SELECT profile_id, category FROM {source}""")
        conn.execute(f"PRAGMA user_version = {LATEST_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return LATEST_VERSION
