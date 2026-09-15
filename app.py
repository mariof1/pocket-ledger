"""Pocket Ledger: a local, multi-account budgeting server."""

from __future__ import annotations

import os
import hashlib
import re
import secrets
import sqlite3
import time
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from bill_import import due_dates as bill_due_dates
from bill_status import month_bill_status
from commute import REGIONS, estimate as commute_estimate, official_holidays, parse_dates, positive_hundredths
from data_transfer import destination_profile, export_account, import_account


BASE = Path(__file__).resolve().parent
INSTANCE = Path(os.environ.get("LEDGER_INSTANCE", BASE / "instance"))
INSTANCE.mkdir(parents=True, exist_ok=True)
DATABASE = INSTANCE / "ledger.sqlite3"
SECRET_FILE = INSTANCE / "secret.key"
if "LEDGER_SECRET_KEY" in os.environ:
    secret_key = os.environ["LEDGER_SECRET_KEY"]
elif SECRET_FILE.exists():
    secret_key = SECRET_FILE.read_text(encoding="utf-8")
else:
    secret_key = secrets.token_hex(32)
    SECRET_FILE.write_text(secret_key, encoding="utf-8")

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("LEDGER_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    MAX_CONTENT_LENGTH=32 * 1024,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'GBP',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, name)
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  category TEXT NOT NULL, occurred_on TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_transactions_profile_date ON transactions(profile_id, occurred_on DESC);
CREATE TABLE IF NOT EXISTS budgets (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  month TEXT NOT NULL, category TEXT NOT NULL,
  limit_cents INTEGER NOT NULL CHECK(limit_cents > 0),
  UNIQUE(profile_id, month, category)
);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL, target_cents INTEGER NOT NULL CHECK(target_cents > 0),
  saved_cents INTEGER NOT NULL DEFAULT 0 CHECK(saved_cents >= 0),
  monthly_cents INTEGER NOT NULL DEFAULT 0 CHECK(monthly_cents >= 0),
  target_date TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL, category TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
  day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 31),
  frequency TEXT NOT NULL DEFAULT 'monthly' CHECK(frequency IN
    ('daily','weekly','biweekly','fourweekly','monthly','quarterly','yearly')),
  first_due_on TEXT
);
CREATE TABLE IF NOT EXISTS bill_imports (
  bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  due_on TEXT NOT NULL,
  transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
  PRIMARY KEY(bill_id, due_on)
);
CREATE TABLE IF NOT EXISTS commutes (
  id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('car','public')),
  distance_hundredths INTEGER NOT NULL DEFAULT 0,
  mpg_hundredths INTEGER NOT NULL DEFAULT 0,
  fuel_price_cents INTEGER NOT NULL DEFAULT 0,
  fare_cents INTEGER NOT NULL DEFAULT 0,
  weekdays TEXT NOT NULL, excluded_dates TEXT NOT NULL DEFAULT '',
  bank_holiday_region TEXT NOT NULL DEFAULT 'none',
  leave_mode TEXT NOT NULL DEFAULT 'dates' CHECK(leave_mode IN ('dates','annual')),
  annual_leave_days INTEGER NOT NULL DEFAULT 0 CHECK(annual_leave_days BETWEEN 0 AND 365)
);
CREATE INDEX IF NOT EXISTS idx_commutes_profile ON commutes(profile_id);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL COLLATE NOCASE,
  UNIQUE(profile_id, name)
);
CREATE TABLE IF NOT EXISTS login_attempts (
  key TEXT PRIMARY KEY, count INTEGER NOT NULL, first_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


with app.app_context():
    db().executescript(SCHEMA)
    bill_columns = {row["name"] for row in db().execute("PRAGMA table_info(bills)")}
    if "frequency" not in bill_columns:
        db().execute("""ALTER TABLE bills ADD COLUMN frequency TEXT NOT NULL DEFAULT 'monthly'
            CHECK(frequency IN ('daily','weekly','biweekly','fourweekly','monthly','quarterly','yearly'))""")
    if "first_due_on" not in bill_columns:
        db().execute("ALTER TABLE bills ADD COLUMN first_due_on TEXT")
    commute_columns = {row["name"] for row in db().execute("PRAGMA table_info(commutes)")}
    if "leave_mode" not in commute_columns:
        db().execute("""ALTER TABLE commutes ADD COLUMN leave_mode TEXT NOT NULL DEFAULT 'dates'
            CHECK(leave_mode IN ('dates','annual'))""")
    if "annual_leave_days" not in commute_columns:
        db().execute("""ALTER TABLE commutes ADD COLUMN annual_leave_days INTEGER NOT NULL DEFAULT 0
            CHECK(annual_leave_days BETWEEN 0 AND 365)""")
    for source in ("transactions", "budgets", "bills"):
        db().execute(f"INSERT OR IGNORE INTO categories(profile_id, name) SELECT profile_id, category FROM {source}")
    db().commit()


def fail(message, status=400):
    return jsonify(error=message), status


@app.errorhandler(RequestEntityTooLarge)
def transfer_too_large(_error):
    return fail("The file is too large. Account imports can be up to 50 MB.", 413)


def payload():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def clean_text(value, label, maximum=80):
    if not isinstance(value, str):
        raise ValueError(f"{label} is required.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} characters.")
    return value


def valid_password(value):
    return isinstance(value, str) and 12 <= len(value) <= 128


def reset_account_password(email, new_password):
    if not valid_password(new_password):
        raise ValueError("Password must be 12 to 128 characters.")
    with app.app_context():
        user = db().execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        if not user:
            return False
        db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (generate_password_hash(new_password), user["id"]))
        db().execute("DELETE FROM auth_sessions WHERE user_id = ?", (user["id"],))
        db().commit()
        return True


def money(value, label, allow_zero=False):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount.as_tuple().exponent < -2:
            raise ValueError
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be a valid amount with at most two decimals.")
    if cents < (0 if allow_zero else 1) or cents > 10_000_000_000:
        raise ValueError(f"{label} is out of range.")
    return cents


BILL_FREQUENCIES = {
    "daily": (365, 12), "weekly": (52, 12), "biweekly": (26, 12),
    "fourweekly": (13, 12), "monthly": (1, 1),
    "quarterly": (1, 3), "yearly": (1, 12),
}


def monthly_bill_cents(amount_cents, frequency):
    numerator, denominator = BILL_FREQUENCIES[frequency]
    return (amount_cents * numerator + denominator // 2) // denominator


def iso_date(value, label, optional=False):
    if optional and (value is None or value == ""):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid date.")


def month_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value) or value[:4] == "0000":
        raise ValueError("Month must use YYYY-MM format.")
    return value


def month_span(month):
    year, number = map(int, month.split("-"))
    next_year, next_number = (year + 1, 1) if number == 12 else (year, number + 1)
    upper = f"{next_year:04d}-{next_number:02d}-01" if next_year <= 9999 else "9999-12-32"
    keys = []
    for back in range(5, -1, -1):
        previous_year, previous_month = divmod(year * 12 + number - 1 - back, 12)
        keys.append(f"{previous_year:04d}-{previous_month + 1:02d}")
    return f"{month}-01", upper, keys


def current_user():
    user_id = session.get("user_id")
    token = session.get("auth_token")
    if not user_id or not isinstance(token, str):
        return None
    return db().execute("""SELECT users.id, users.email FROM users
        JOIN auth_sessions ON auth_sessions.user_id = users.id
        WHERE users.id = ? AND auth_sessions.token_hash = ?
        AND auth_sessions.created_at > ?""",
        (user_id, hashlib.sha256(token.encode()).hexdigest(), int(time.time()) - 30 * 24 * 60 * 60)
    ).fetchone()


def start_session(user_id, profile_id):
    token = secrets.token_urlsafe(32)
    db().execute("INSERT INTO auth_sessions(token_hash, user_id, created_at) VALUES(?, ?, ?)",
                 (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time())))
    db().commit()
    session.clear()
    session.update(user_id=user_id, profile_id=profile_id, auth_token=token,
                   csrf=secrets.token_urlsafe(32))
    session.permanent = True


def current_profile():
    user = current_user()
    if not user:
        return None
    profile = db().execute(
        "SELECT * FROM profiles WHERE id = ? AND user_id = ?",
        (session.get("profile_id"), user["id"]),
    ).fetchone()
    if profile:
        return profile
    profile = db().execute(
        "SELECT * FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)
    ).fetchone()
    if profile:
        session["profile_id"] = profile["id"]
    return profile


def remember_category(profile_id, name):
    existing = db().execute("SELECT name FROM categories WHERE profile_id = ? AND name = ?",
                            (profile_id, name)).fetchone()
    if existing:
        return existing["name"]
    db().execute("INSERT INTO categories(profile_id, name) VALUES(?, ?)", (profile_id, name))
    return name


@app.before_request
def protect_api():
    if not request.path.startswith("/api/"):
        return None
    if request.endpoint == "restore_account":
        request.max_content_length = 50 * 1024 * 1024
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf", "")):
            return fail("Session check failed. Refresh the page and try again.", 403)
    if request.endpoint not in ("bootstrap", "register", "login") and not current_user():
        return fail("Please sign in.", 401)
    return None


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    if os.environ.get("LEDGER_HTTPS") == "1":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


@app.get("/static/<path:filename>")
def static_file(filename):
    return send_from_directory(BASE / "static", filename)


@app.get("/api/bootstrap")
def bootstrap():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    user = current_user()
    if not user:
        return jsonify(csrf=session["csrf"], user=None)
    profiles = [dict(row) for row in db().execute(
        "SELECT id, name, currency FROM profiles WHERE user_id = ? ORDER BY id", (user["id"],)
    )]
    profile = current_profile()
    try:
        destination_profile(db(), user["id"])
        import_ready = True
    except ValueError:
        import_ready = False
    return jsonify(csrf=session["csrf"], user=dict(user), profiles=profiles,
                   profile_id=profile["id"] if profile else None,
                   import_ready=import_ready)


@app.get("/api/account/export")
def download_account():
    document = export_account(db(), session["user_id"])
    response = jsonify(document)
    response.headers["Content-Disposition"] = (
        f'attachment; filename="pocket-ledger-{date.today().isoformat()}.json"')
    return response


@app.post("/api/account/import")
def restore_account():
    try:
        result = import_account(db(), session["user_id"], payload())
        session["profile_id"] = result["profile_id"]
        return jsonify(profiles=result["profiles"], counts=result["counts"]), 201
    except sqlite3.IntegrityError:
        return fail("The export contains conflicting records. No data was imported.")
    except ValueError as error:
        return fail(str(error))


@app.post("/api/register")
def register():
    data = payload()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        return fail("Enter a valid email address.")
    if not valid_password(password):
        return fail("Password must be 12 to 128 characters.")
    try:
        cursor = db().execute("INSERT INTO users(email, password_hash) VALUES(?, ?)",
                              (email, generate_password_hash(password)))
        user_id = cursor.lastrowid
        profile_id = db().execute("INSERT INTO profiles(user_id, name, currency) VALUES(?, 'Personal', 'GBP')",
                                  (user_id,)).lastrowid
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return fail("An account with that email already exists.", 409)
    start_session(user_id, profile_id)
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    data = payload()
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    address = request.remote_addr or "unknown"
    attempt_key = f"email:{address}:{email[:254]}"
    address_key = f"ip:{address}"
    now = int(time.time())
    db().execute("DELETE FROM login_attempts WHERE first_at <= ?", (now - 15 * 60,))
    db().commit()
    attempt = db().execute("SELECT count FROM login_attempts WHERE key = ?", (attempt_key,)).fetchone()
    address_attempt = db().execute("SELECT count FROM login_attempts WHERE key = ?", (address_key,)).fetchone()
    if (attempt and attempt["count"] >= 5) or (address_attempt and address_attempt["count"] >= 30):
        return fail("Too many sign-in attempts. Try again in 15 minutes.", 429)
    user = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not isinstance(password, str) or not check_password_hash(user["password_hash"], password):
        for key in (attempt_key, address_key):
            db().execute("""INSERT INTO login_attempts(key, count, first_at) VALUES(?, 1, ?)
                ON CONFLICT(key) DO UPDATE SET count=count+1""", (key, now))
        db().commit()
        return fail("Email or password is incorrect.", 401)
    db().execute("DELETE FROM login_attempts WHERE key = ?", (attempt_key,))
    db().commit()
    profile = db().execute("SELECT id FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
    start_session(user["id"], profile["id"] if profile else None)
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    token = session.get("auth_token")
    if isinstance(token, str):
        db().execute("DELETE FROM auth_sessions WHERE token_hash = ?",
                     (hashlib.sha256(token.encode()).hexdigest(),))
        db().commit()
    session.clear()
    return jsonify(ok=True)


@app.post("/api/password")
def change_password():
    data = payload()
    current = data.get("current_password")
    new = data.get("new_password")
    if not valid_password(new):
        return fail("New password must be 12 to 128 characters.")
    user_id = session["user_id"]
    user = db().execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if not isinstance(current, str) or not user or not check_password_hash(user["password_hash"], current):
        return fail("Current password is incorrect.")
    if check_password_hash(user["password_hash"], new):
        return fail("Choose a different new password.")
    profile_id = current_profile()["id"]
    db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(new), user_id))
    db().execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
    db().commit()
    start_session(user_id, profile_id)
    return jsonify(ok=True)


@app.post("/api/profiles")
def add_profile():
    try:
        data = payload()
        name = clean_text(data.get("name"), "Profile name", 40)
        currency = data.get("currency", "GBP")
        if currency not in ("GBP", "EUR", "USD"):
            raise ValueError("Choose GBP, EUR, or USD.")
        if db().execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()[0] >= 10:
            raise ValueError("An account can have up to 10 profiles.")
        cursor = db().execute("INSERT INTO profiles(user_id, name, currency) VALUES(?, ?, ?)",
                              (session["user_id"], name, currency))
        db().commit()
        session["profile_id"] = cursor.lastrowid
        return jsonify(id=cursor.lastrowid), 201
    except sqlite3.IntegrityError:
        return fail("A profile with that name already exists.", 409)
    except ValueError as error:
        return fail(str(error))


@app.post("/api/profiles/<int:profile_id>/select")
def select_profile(profile_id):
    row = db().execute("SELECT id FROM profiles WHERE id = ? AND user_id = ?",
                       (profile_id, session["user_id"])).fetchone()
    if not row:
        return fail("Profile not found.", 404)
    session["profile_id"] = profile_id
    return jsonify(ok=True)


@app.delete("/api/profiles/<int:profile_id>")
def delete_profile(profile_id):
    owned = db().execute("SELECT id FROM profiles WHERE id = ? AND user_id = ?",
                         (profile_id, session["user_id"])).fetchone()
    if not owned:
        return fail("Profile not found.", 404)
    if db().execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()[0] <= 1:
        return fail("Keep at least one profile.")
    db().execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    db().commit()
    if session.get("profile_id") == profile_id:
        session.pop("profile_id", None)
        current_profile()
    return jsonify(ok=True)


@app.get("/api/data")
def data():
    profile = current_profile()
    if not profile:
        return fail("Create a profile first.", 404)
    try:
        month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
    except ValueError as error:
        return fail(str(error))
    conn = db()
    lower, upper, keys = month_span(month)
    today = date.today().isoformat()
    monthly_totals = {"income": 0, "expense": 0}
    for row in conn.execute("""SELECT kind, SUM(amount_cents) AS total FROM transactions
            WHERE profile_id = ? AND occurred_on >= ? AND occurred_on < ?
            AND occurred_on <= ? GROUP BY kind""",
            (profile["id"], lower, upper, today)):
        monthly_totals[row["kind"]] = row["total"]
    chart_totals = {key: {"key": key, "income": 0, "expense": 0} for key in keys}
    for row in conn.execute("""SELECT substr(occurred_on, 1, 7) AS month, kind,
            SUM(amount_cents) AS total FROM transactions WHERE profile_id = ?
            AND occurred_on >= ? AND occurred_on < ? AND occurred_on <= ? GROUP BY month, kind""",
            (profile["id"], f"{keys[0]}-01", upper, today)):
        if row["month"] in chart_totals:
            chart_totals[row["month"]][row["kind"]] = row["total"]
    spending = [dict(row) for row in conn.execute("""SELECT
            COALESCE(MAX(categories.name), MIN(transactions.category)) AS category,
            SUM(transactions.amount_cents) AS amount_cents
            FROM transactions LEFT JOIN categories ON categories.profile_id = transactions.profile_id
            AND categories.name = transactions.category
            WHERE transactions.profile_id = ? AND transactions.kind = 'expense'
            AND transactions.occurred_on >= ? AND transactions.occurred_on < ?
            AND transactions.occurred_on <= ?
            GROUP BY transactions.category COLLATE NOCASE ORDER BY amount_cents DESC""",
            (profile["id"], lower, upper, today))]
    recent = [dict(row) for row in conn.execute("""SELECT id, kind, amount_cents, category,
            occurred_on, note FROM transactions WHERE profile_id = ? AND occurred_on >= ?
            AND occurred_on < ? AND occurred_on <= ?
            ORDER BY occurred_on DESC, id DESC LIMIT 5""",
            (profile["id"], lower, upper, today))]
    budgets = [dict(row) for row in conn.execute(
        "SELECT id, month, category, limit_cents FROM budgets WHERE profile_id = ? AND month = ? ORDER BY category",
        (profile["id"], month))]
    goals = [dict(row) for row in conn.execute(
        "SELECT id, name, target_cents, saved_cents, monthly_cents, target_date FROM goals WHERE profile_id = ? ORDER BY id DESC",
        (profile["id"],))]
    bills = [dict(row) for row in conn.execute(
        """SELECT id, name, category, amount_cents, day_of_month, frequency, first_due_on FROM bills
           WHERE profile_id = ? ORDER BY CASE WHEN frequency = 'monthly' THEN 0 ELSE 1 END,
           day_of_month, id""",
        (profile["id"],))]
    for bill in bills:
        bill["monthly_cents"] = monthly_bill_cents(bill["amount_cents"], bill["frequency"])
    monthly_bills_cents = sum(bill["monthly_cents"] for bill in bills)
    linked_bill_payments = [dict(row) for row in conn.execute("""SELECT
        bill_imports.bill_id, bill_imports.due_on, transactions.amount_cents
        FROM bill_imports JOIN bills ON bills.id = bill_imports.bill_id
        JOIN transactions ON transactions.id = bill_imports.transaction_id
        WHERE bills.profile_id = ? AND transactions.profile_id = ?
        AND bill_imports.due_on >= ? AND bill_imports.due_on < ?""",
        (profile["id"], profile["id"], lower, upper))]
    bill_status = month_bill_status(bills, linked_bill_payments, month, today)
    commutes = [dict(row) for row in conn.execute(
        """SELECT id, name, mode, distance_hundredths, mpg_hundredths,
                  fuel_price_cents, fare_cents, weekdays, excluded_dates,
                  bank_holiday_region, leave_mode, annual_leave_days
                  FROM commutes WHERE profile_id = ? ORDER BY id DESC""",
        (profile["id"],))]
    holidays, holiday_error = (official_holidays() if any(
        plan["bank_holiday_region"] != "none" for plan in commutes) else (None, None))
    for plan in commutes:
        plan.update(commute_estimate(plan, month, holidays, holiday_error))
    monthly_commuting_cents = sum(plan["monthly_cents"] for plan in commutes)
    monthly_bills_cents += monthly_commuting_cents
    categories = [row["name"] for row in conn.execute(
        "SELECT name FROM categories WHERE profile_id = ? ORDER BY name COLLATE NOCASE", (profile["id"],))]
    return jsonify(profile=dict(profile), month=month, monthly_totals=monthly_totals,
                   chart=list(chart_totals.values()), spending=spending, recent=recent,
                   budgets=budgets, goals=goals, bills=bills, bill_status=bill_status,
                   commutes=commutes,
                   monthly_commuting_cents=monthly_commuting_cents,
                   monthly_bills_cents=monthly_bills_cents, categories=categories)


@app.get("/api/transactions")
def list_transactions():
    profile = current_profile()
    if not profile:
        return fail("Create a profile first.", 404)
    kind = request.args.get("kind", "all")
    search = request.args.get("search", "").strip()
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        return fail("Invalid page.")
    if kind not in ("all", "income", "expense") or len(search) > 80 or not 0 <= offset <= 10_000_000:
        return fail("Invalid transaction filter.")
    conditions = ["profile_id = ?"]
    values = [profile["id"]]
    if kind != "all":
        conditions.append("kind = ?")
        values.append(kind)
    if search:
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("(LOWER(note) LIKE ? ESCAPE '\\' OR LOWER(category) LIKE ? ESCAPE '\\' OR occurred_on LIKE ? ESCAPE '\\')")
        values.extend([f"%{escaped}%"] * 3)
    where = " AND ".join(conditions)
    total = db().execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", values).fetchone()[0]
    rows = [dict(row) for row in db().execute(f"""SELECT id, kind, amount_cents, category,
        occurred_on, note FROM transactions WHERE {where}
        ORDER BY occurred_on DESC, id DESC LIMIT 50 OFFSET ?""", (*values, offset))]
    return jsonify(transactions=rows, total=total, offset=offset, limit=50)


def transaction_fields(data):
    kind = data.get("kind")
    if kind not in ("income", "expense"):
        raise ValueError("Choose income or expense.")
    note = data.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str) or len(note.strip()) > 200:
        raise ValueError("Note must be at most 200 characters.")
    occurred_on = iso_date(data.get("occurred_on"), "Date")
    if occurred_on > date.today().isoformat():
        raise ValueError("Transactions are for payments that have happened. Choose today or earlier.")
    return (kind, money(data.get("amount"), "Amount"), clean_text(data.get("category"), "Category", 40),
            occurred_on, note.strip())


@app.post("/api/transactions")
def add_transaction():
    try:
        fields = transaction_fields(payload())
        profile_id = current_profile()["id"]
        category = remember_category(profile_id, fields[2])
        fields = (fields[0], fields[1], category, fields[3], fields[4])
        cursor = db().execute(
            "INSERT INTO transactions(profile_id, kind, amount_cents, category, occurred_on, note) VALUES(?, ?, ?, ?, ?, ?)",
            (profile_id, *fields))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201
    except ValueError as error:
        return fail(str(error))


@app.put("/api/transactions/<int:item_id>")
def update_transaction(item_id):
    try:
        fields = transaction_fields(payload())
        profile_id = current_profile()["id"]
        cursor = db().execute(
            "UPDATE transactions SET kind=?, amount_cents=?, category=?, occurred_on=?, note=? WHERE id=? AND profile_id=?",
            (*fields, item_id, profile_id))
        if not cursor.rowcount:
            return fail("Transaction not found.", 404)
        category = remember_category(profile_id, fields[2])
        if category != fields[2]:
            db().execute("UPDATE transactions SET category=? WHERE id=?", (category, item_id))
        db().commit()
        return jsonify(ok=True)
    except ValueError as error:
        return fail(str(error))


@app.delete("/api/transactions/<int:item_id>")
def delete_transaction(item_id):
    return delete_owned("transactions", item_id)


def delete_owned(table, item_id):
    if table not in ("transactions", "budgets", "goals", "bills", "commutes"):
        raise ValueError("Invalid table")
    cursor = db().execute(f"DELETE FROM {table} WHERE id = ? AND profile_id = ?",
                          (item_id, current_profile()["id"]))
    if not cursor.rowcount:
        return fail("Item not found.", 404)
    db().commit()
    return jsonify(ok=True)


@app.post("/api/budgets")
def add_budget():
    try:
        data = payload()
        month = month_value(data.get("month"))
        category = clean_text(data.get("category"), "Category", 40)
        limit = money(data.get("limit"), "Budget")
        profile_id = current_profile()["id"]
        category = remember_category(profile_id, category)
        db().execute("""INSERT INTO budgets(profile_id, month, category, limit_cents)
                        VALUES(?, ?, ?, ?) ON CONFLICT(profile_id, month, category)
                        DO UPDATE SET limit_cents=excluded.limit_cents""",
                     (profile_id, month, category, limit))
        db().commit()
        return jsonify(ok=True), 201
    except ValueError as error:
        return fail(str(error))


@app.delete("/api/budgets/<int:item_id>")
def delete_budget(item_id):
    return delete_owned("budgets", item_id)


def goal_fields(data):
    target = money(data.get("target"), "Target")
    saved = money(data.get("saved", 0), "Saved", allow_zero=True)
    monthly = money(data.get("monthly", 0), "Monthly contribution", allow_zero=True)
    return (clean_text(data.get("name"), "Goal name", 60), target, saved, monthly,
            iso_date(data.get("target_date"), "Target date", optional=True))


@app.post("/api/goals")
def add_goal():
    try:
        fields = goal_fields(payload())
        cursor = db().execute(
            "INSERT INTO goals(profile_id, name, target_cents, saved_cents, monthly_cents, target_date) VALUES(?, ?, ?, ?, ?, ?)",
            (current_profile()["id"], *fields))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201
    except ValueError as error:
        return fail(str(error))


@app.put("/api/goals/<int:item_id>")
def update_goal(item_id):
    try:
        fields = goal_fields(payload())
        cursor = db().execute(
            "UPDATE goals SET name=?, target_cents=?, saved_cents=?, monthly_cents=?, target_date=? WHERE id=? AND profile_id=?",
            (*fields, item_id, current_profile()["id"]))
        if not cursor.rowcount:
            return fail("Goal not found.", 404)
        db().commit()
        return jsonify(ok=True)
    except ValueError as error:
        return fail(str(error))


@app.delete("/api/goals/<int:item_id>")
def delete_goal(item_id):
    return delete_owned("goals", item_id)


def bill_fields(data):
    frequency = data.get("frequency", "monthly")
    if not isinstance(frequency, str) or frequency not in BILL_FREQUENCIES:
        raise ValueError("Choose a valid bill frequency.")
    raw_day = data.get("day_of_month", 1 if frequency != "monthly" else None)
    if isinstance(raw_day, bool) or not isinstance(raw_day, (int, str)) or not re.fullmatch(r"\d{1,2}", str(raw_day)):
        raise ValueError("Bill day must be a whole number from 1 to 31.")
    try:
        day = int(raw_day)
    except (TypeError, ValueError):
        raise ValueError("Bill day must be a whole number from 1 to 31.")
    if day < 1 or day > 31:
        raise ValueError("Bill day must be a whole number from 1 to 31.")
    first_due = iso_date(data.get("first_due_on"), "First payment date", optional=True)
    if frequency == "monthly":
        first_due = None
    return (clean_text(data.get("name"), "Bill name", 60),
            clean_text(data.get("category"), "Category", 40),
            money(data.get("amount"), "Amount each time"), day, frequency, first_due)


@app.post("/api/bills")
def add_bill():
    try:
        fields = bill_fields(payload())
        profile_id = current_profile()["id"]
        category = remember_category(profile_id, fields[1])
        fields = (fields[0], category, fields[2], fields[3], fields[4], fields[5])
        cursor = db().execute(
            "INSERT INTO bills(profile_id, name, category, amount_cents, day_of_month, frequency, first_due_on) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (profile_id, *fields))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201
    except ValueError as error:
        return fail(str(error))


@app.put("/api/bills/<int:item_id>")
def update_bill(item_id):
    try:
        fields = bill_fields(payload())
        profile_id = current_profile()["id"]
        cursor = db().execute(
            "UPDATE bills SET name=?, category=?, amount_cents=?, day_of_month=?, frequency=?, first_due_on=? WHERE id=? AND profile_id=?",
            (*fields, item_id, profile_id))
        if not cursor.rowcount:
            return fail("Bill not found.", 404)
        category = remember_category(profile_id, fields[1])
        if category != fields[1]:
            db().execute("UPDATE bills SET category=? WHERE id=?", (category, item_id))
        db().commit()
        return jsonify(ok=True)
    except ValueError as error:
        return fail(str(error))


@app.delete("/api/bills/<int:item_id>")
def delete_bill(item_id):
    return delete_owned("bills", item_id)


def bill_payment_candidates(profile_id, month):
    bills = [dict(row) for row in db().execute("""SELECT id, name, category,
        amount_cents, day_of_month, frequency, first_due_on FROM bills
        WHERE profile_id = ? ORDER BY name COLLATE NOCASE, id""", (profile_id,))]
    items, needs_schedule = [], []
    for bill in bills:
        if bill["frequency"] != "monthly" and not bill["first_due_on"]:
            needs_schedule.append({"id": bill["id"], "name": bill["name"],
                                   "frequency": bill["frequency"]})
            continue
        for due_on in bill_due_dates(bill, month):
            items.append({"bill_id": bill["id"], "name": bill["name"],
                          "category": bill["category"], "frequency": bill["frequency"],
                          "amount_cents": bill["amount_cents"], "due_on": due_on})
    items.sort(key=lambda item: (item["due_on"], item["name"].casefold(), item["bill_id"]))
    return items, needs_schedule


@app.get("/api/bills/import-preview")
def preview_bill_import():
    try:
        month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
    except ValueError as error:
        return fail(str(error))
    profile_id = current_profile()["id"]
    items, needs_schedule = bill_payment_candidates(profile_id, month)
    lower, upper, _ = month_span(month)
    imported = {(row["bill_id"], row["due_on"]) for row in db().execute("""
        SELECT bill_imports.bill_id, bill_imports.due_on FROM bill_imports
        JOIN bills ON bills.id = bill_imports.bill_id
        WHERE bills.profile_id = ? AND bill_imports.due_on >= ? AND bill_imports.due_on < ?""",
        (profile_id, lower, upper))}
    recorded = {(row["occurred_on"], row["amount_cents"], row["category"].casefold())
                for row in db().execute("""SELECT occurred_on, amount_cents, category
                    FROM transactions WHERE profile_id = ? AND kind = 'expense'
                    AND occurred_on >= ? AND occurred_on < ?
                    AND id NOT IN (SELECT transaction_id FROM bill_imports)""",
                    (profile_id, lower, upper))}
    today = date.today().isoformat()
    for item in items:
        item["already_imported"] = (item["bill_id"], item["due_on"]) in imported
        item["possible_duplicate"] = (item["due_on"], item["amount_cents"],
                                      item["category"].casefold()) in recorded
        item["future"] = item["due_on"] > today
    return jsonify(month=month, today=today, items=items, needs_schedule=needs_schedule)


@app.post("/api/bills/import")
def import_bill_payments():
    try:
        data = payload()
        month = month_value(data.get("month"))
        selected = data.get("items")
        if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
            raise ValueError("Select between 1 and 500 bill payments to import.")
        requests = []
        for item in selected:
            if not isinstance(item, dict) or isinstance(item.get("bill_id"), bool) or not isinstance(item.get("bill_id"), int) or item["bill_id"] <= 0:
                raise ValueError("Choose valid bill payments from the preview.")
            due_on = iso_date(item.get("due_on"), "Payment date")
            if not due_on.startswith(f"{month}-") or due_on > date.today().isoformat():
                raise ValueError("Choose payments due on or before today in the selected month.")
            requests.append((item["bill_id"], due_on))
        if len(set(requests)) != len(requests):
            raise ValueError("Choose each bill payment only once.")
        conn = db()
        conn.execute("BEGIN IMMEDIATE")
        try:
            candidates, _ = bill_payment_candidates(current_profile()["id"], month)
            available = {(item["bill_id"], item["due_on"]): item for item in candidates}
            if any(key not in available for key in requests):
                raise ValueError("A selected bill payment is no longer available. Refresh the preview.")
            imported_count = skipped_count = 0
            for key in requests:
                bill_id, due_on = key
                if conn.execute("SELECT 1 FROM bill_imports WHERE bill_id = ? AND due_on = ?",
                                key).fetchone():
                    skipped_count += 1
                    continue
                item = available[key]
                cursor = conn.execute("""INSERT INTO transactions(profile_id, kind,
                    amount_cents, category, occurred_on, note) VALUES(?, 'expense', ?, ?, ?, ?)""",
                    (current_profile()["id"], item["amount_cents"], item["category"],
                     due_on, item["name"]))
                conn.execute("INSERT INTO bill_imports(bill_id, due_on, transaction_id) VALUES(?, ?, ?)",
                             (bill_id, due_on, cursor.lastrowid))
                imported_count += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return jsonify(imported_count=imported_count, skipped_count=skipped_count), 201
    except ValueError as error:
        return fail(str(error))


def commute_fields(data):
    mode = data.get("mode")
    if mode not in ("car", "public"):
        raise ValueError("Choose Car or Public transport.")
    raw_days = data.get("weekdays")
    if not isinstance(raw_days, list) or not raw_days or len(raw_days) > 7 or any(
            isinstance(day, bool) or str(day) not in {str(i) for i in range(7)}
            for day in raw_days):
        raise ValueError("Choose at least one commuting weekday.")
    days = sorted({int(day) for day in raw_days})
    region = data.get("bank_holiday_region", "none")
    if not isinstance(region, str) or region not in REGIONS:
        raise ValueError("Choose a valid UK bank holiday option.")
    leave_mode = data.get("leave_mode", "dates")
    if leave_mode not in ("dates", "annual"):
        raise ValueError("Choose annual leave days or exact dates.")
    leave_dates = data.get("excluded_dates", "")
    if leave_mode == "annual":
        raw_annual = data.get("annual_leave_days")
        if isinstance(raw_annual, bool) or not isinstance(raw_annual, (int, str)) or not re.fullmatch(r"\d{1,3}", str(raw_annual)):
            raise ValueError("Annual leave days must be a whole number from 0 to 365.")
        annual_days = int(raw_annual)
        if annual_days > 365:
            raise ValueError("Annual leave days must be a whole number from 0 to 365.")
        if not isinstance(leave_dates, str) or leave_dates.strip():
            raise ValueError("Use annual leave days or exact dates, not both.")
        leave_dates = ""
    else:
        parse_dates(leave_dates)
        annual_days = 0
        if data.get("annual_leave_days") not in (None, "", 0, "0"):
            raise ValueError("Use annual leave days or exact dates, not both.")
    if mode == "car":
        distance = positive_hundredths(data.get("distance"), "Daily round-trip distance", 500)
        mpg = positive_hundredths(data.get("mpg"), "UK miles per gallon", 200)
        fuel_price = money(data.get("fuel_price"), "Fuel price per litre")
        fare = 0
    else:
        distance = mpg = fuel_price = 0
        fare = money(data.get("fare"), "Daily return fare")
    return (clean_text(data.get("name"), "Commute name", 60), mode,
            distance, mpg, fuel_price, fare, ",".join(str(day) for day in days),
            leave_dates, region, leave_mode, annual_days)


@app.post("/api/commutes/preview")
def preview_commute():
    try:
        data = payload()
        month = month_value(data.get("month"))
        fields = commute_fields(data)
        keys = ("name", "mode", "distance_hundredths", "mpg_hundredths",
                "fuel_price_cents", "fare_cents", "weekdays", "excluded_dates",
                "bank_holiday_region", "leave_mode", "annual_leave_days")
        plan = dict(zip(keys, fields))
        holidays, error = (official_holidays() if plan["bank_holiday_region"] != "none"
                           else (None, None))
        return jsonify(commute_estimate(plan, month, holidays, error))
    except ValueError as error:
        return fail(str(error))


@app.post("/api/commutes")
def add_commute():
    try:
        fields = commute_fields(payload())
        cursor = db().execute("""INSERT INTO commutes(profile_id, name, mode,
            distance_hundredths, mpg_hundredths, fuel_price_cents, fare_cents,
            weekdays, excluded_dates, bank_holiday_region, leave_mode, annual_leave_days)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (current_profile()["id"], *fields))
        db().commit()
        return jsonify(id=cursor.lastrowid), 201
    except ValueError as error:
        return fail(str(error))


@app.put("/api/commutes/<int:item_id>")
def update_commute(item_id):
    try:
        fields = commute_fields(payload())
        cursor = db().execute("""UPDATE commutes SET name=?, mode=?,
            distance_hundredths=?, mpg_hundredths=?, fuel_price_cents=?, fare_cents=?,
            weekdays=?, excluded_dates=?, bank_holiday_region=?, leave_mode=?, annual_leave_days=?
            WHERE id=? AND profile_id=?""",
            (*fields, item_id, current_profile()["id"]))
        if not cursor.rowcount:
            return fail("Commute not found.", 404)
        db().commit()
        return jsonify(ok=True)
    except ValueError as error:
        return fail(str(error))


@app.delete("/api/commutes/<int:item_id>")
def delete_commute(item_id):
    return delete_owned("commutes", item_id)


if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("LEDGER_HOST", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Pocket Ledger binds to loopback only. Use a local HTTPS reverse proxy for remote access.")
    serve(app, host=host,
          port=int(os.environ.get("LEDGER_PORT", "5000")), threads=4)
