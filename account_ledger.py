"""Profile account ownership and balances calculated from ledger activity."""

from datetime import date


ACCOUNT_KINDS = {"current", "savings", "card"}


def default_account(conn, profile_id):
    row = conn.execute("""SELECT id FROM accounts WHERE profile_id = ?
        ORDER BY CASE WHEN kind = 'current' THEN 0 ELSE 1 END, id LIMIT 1""",
        (profile_id,)).fetchone()
    if not row:
        raise ValueError("Create an account in this profile first.")
    return row["id"]


def owned_account(conn, profile_id, value, optional_default=False):
    if optional_default and (value is None or value == ""):
        return default_account(conn, profile_id)
    if isinstance(value, bool) or not isinstance(value, (int, str)) or \
            not str(value).isdigit() or int(value) <= 0:
        raise ValueError("Choose an account in this profile.")
    row = conn.execute("SELECT id FROM accounts WHERE id = ? AND profile_id = ?",
                       (int(value), profile_id)).fetchone()
    if not row:
        raise ValueError("Choose an account in this profile.")
    return row["id"]


def balances(conn, profile_id, as_of=None):
    """Opening balance + real income/expense + transfers through the date."""
    as_of = as_of or date.today().isoformat()
    accounts = [dict(row) for row in conn.execute("""SELECT id, name, kind,
        opening_balance_cents, created_at FROM accounts WHERE profile_id = ?
        ORDER BY CASE kind WHEN 'current' THEN 0 WHEN 'savings' THEN 1 ELSE 2 END,
        id""", (profile_id,))]
    movement = {account["id"]: 0 for account in accounts}
    for row in conn.execute("""SELECT account_id,
        COALESCE(SUM(CASE kind WHEN 'income' THEN amount_cents ELSE -amount_cents END), 0) AS net
        FROM transactions WHERE profile_id = ? AND occurred_on <= ? GROUP BY account_id""",
        (profile_id, as_of)):
        if row["account_id"] in movement:
            movement[row["account_id"]] += row["net"]
    for row in conn.execute("""SELECT source_account_id, target_account_id, amount_cents
        FROM transfers WHERE profile_id = ? AND occurred_on <= ?""",
        (profile_id, as_of)):
        movement[row["source_account_id"]] -= row["amount_cents"]
        movement[row["target_account_id"]] += row["amount_cents"]
    for account in accounts:
        account["balance_cents"] = account["opening_balance_cents"] + movement[account["id"]]
    return accounts
