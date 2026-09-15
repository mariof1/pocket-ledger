"""Portable account records, excluding credentials and live sessions."""

import re
import sqlite3
from datetime import date, datetime

from commute import REGIONS, parse_dates


FORMAT = "pocket-ledger-account"
VERSION = 1
TABLE_FIELDS = {
    "transactions": ("id", "kind", "amount_cents", "category", "occurred_on", "note", "created_at"),
    "budgets": ("month", "category", "limit_cents"),
    "goals": ("name", "target_cents", "saved_cents", "monthly_cents", "target_date", "created_at"),
    "bills": ("id", "name", "category", "amount_cents", "day_of_month", "frequency", "first_due_on"),
    "commutes": ("name", "mode", "distance_hundredths", "mpg_hundredths", "fuel_price_cents",
                 "fare_cents", "weekdays", "excluded_dates", "bank_holiday_region",
                 "leave_mode", "annual_leave_days"),
    "categories": ("name",),
}
FREQUENCIES = {"daily", "weekly", "biweekly", "fourweekly", "monthly", "quarterly", "yearly"}


def export_account(conn, user_id):
    profiles = []
    for profile in conn.execute(
            "SELECT id, name, currency, created_at FROM profiles WHERE user_id = ? ORDER BY id",
            (user_id,)):
        item = {"name": profile["name"], "currency": profile["currency"],
                "created_at": profile["created_at"]}
        for table, fields in TABLE_FIELDS.items():
            columns = ", ".join(fields)
            item[table] = [dict(row) for row in conn.execute(
                f"SELECT {columns} FROM {table} WHERE profile_id = ? ORDER BY id",
                (profile["id"],))]
        item["bill_imports"] = [dict(row) for row in conn.execute(
            """SELECT bill_imports.bill_id, bill_imports.due_on, bill_imports.transaction_id
               FROM bill_imports JOIN bills ON bills.id = bill_imports.bill_id
               JOIN transactions ON transactions.id = bill_imports.transaction_id
               WHERE bills.profile_id = ? AND transactions.profile_id = ?
               ORDER BY bill_imports.bill_id, bill_imports.due_on""",
            (profile["id"], profile["id"]))]
        profiles.append(item)
    return {"format": FORMAT, "version": VERSION, "profiles": profiles}


def record(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def records(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def text(value, label, maximum, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or (not optional and not value.strip()):
        raise ValueError(f"{label} is missing or too long.")
    return value


def integer(value, label, maximum=10_000_000_000, zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1) or value > maximum:
        raise ValueError(f"{label} is out of range.")
    return value


def iso_date(value, label, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} must be a valid date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must be a valid date.")
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be a valid date.")
    return value


def month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{3}-(0[1-9]|1[0-2])", value):
        raise ValueError("Budget month must use YYYY-MM.")
    return value


def timestamp(value):
    if not isinstance(value, str) or len(value) != 19:
        raise ValueError("Export creation time is invalid.")
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("Export creation time is invalid.")
    return value


def destination_profile(conn, user_id):
    profiles = conn.execute("SELECT id FROM profiles WHERE user_id = ?", (user_id,)).fetchall()
    if len(profiles) != 1:
        raise ValueError("Import requires a new account with one empty profile.")
    profile_id = profiles[0]["id"]
    for table in TABLE_FIELDS:
        if conn.execute(f"SELECT 1 FROM {table} WHERE profile_id = ? LIMIT 1",
                        (profile_id,)).fetchone():
            raise ValueError("Import requires a new account with one empty profile.")
    return profile_id


def import_account(conn, user_id, document):
    record(document, "Export")
    if document.get("format") != FORMAT or type(document.get("version")) is not int or document["version"] != VERSION:
        raise ValueError("Choose a Pocket Ledger account export (version 1).")
    profiles = records(document.get("profiles"), "Profiles")
    if not 1 <= len(profiles) <= 10:
        raise ValueError("An export must contain between 1 and 10 profiles.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        first_profile_id = destination_profile(conn, user_id)
        names = set()
        counts = {table: 0 for table in (*TABLE_FIELDS, "bill_imports")}
        for index, raw in enumerate(profiles):
            profile = record(raw, "Profile")
            name = text(profile.get("name"), "Profile name", 40).strip()
            if name in names:
                raise ValueError("Export profile names must be unique.")
            names.add(name)
            currency = profile.get("currency")
            if currency not in ("GBP", "EUR", "USD"):
                raise ValueError("Export profile currency is invalid.")
            created_at = timestamp(profile.get("created_at"))
            if index == 0:
                profile_id = first_profile_id
                conn.execute("UPDATE profiles SET name=?, currency=?, created_at=? WHERE id=?",
                             (name, currency, created_at, profile_id))
            else:
                profile_id = conn.execute(
                    "INSERT INTO profiles(user_id, name, currency, created_at) VALUES(?, ?, ?, ?)",
                    (user_id, name, currency, created_at)).lastrowid
            transaction_ids, bill_ids = {}, {}
            for row in records(profile.get("transactions"), "Transactions"):
                item = record(row, "Transaction")
                old_id = integer(item.get("id"), "Transaction reference")
                if old_id in transaction_ids:
                    raise ValueError("Export transaction references must be unique.")
                kind = item.get("kind")
                if kind not in ("income", "expense"):
                    raise ValueError("Export transaction type is invalid.")
                amount = integer(item.get("amount_cents"), "Transaction amount")
                category = text(item.get("category"), "Transaction category", 40).strip()
                occurred_on = iso_date(item.get("occurred_on"), "Transaction date")
                note = text(item.get("note"), "Transaction note", 200, optional=True)
                if note is None:
                    raise ValueError("Transaction note must be text.")
                created_at = timestamp(item.get("created_at"))
                transaction_ids[old_id] = conn.execute(
                    """INSERT INTO transactions(profile_id, kind, amount_cents, category,
                       occurred_on, note, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (profile_id, kind, amount, category, occurred_on, note, created_at)).lastrowid
                counts["transactions"] += 1
            for row in records(profile.get("budgets"), "Budgets"):
                item = record(row, "Budget")
                conn.execute(
                    "INSERT INTO budgets(profile_id, month, category, limit_cents) VALUES(?, ?, ?, ?)",
                    (profile_id, month(item.get("month")),
                     text(item.get("category"), "Budget category", 40).strip(),
                     integer(item.get("limit_cents"), "Budget limit")))
                counts["budgets"] += 1
            for row in records(profile.get("goals"), "Goals"):
                item = record(row, "Goal")
                conn.execute(
                    """INSERT INTO goals(profile_id, name, target_cents, saved_cents,
                       monthly_cents, target_date, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (profile_id, text(item.get("name"), "Goal name", 60).strip(),
                     integer(item.get("target_cents"), "Goal target"),
                     integer(item.get("saved_cents"), "Goal savings", zero=True),
                     integer(item.get("monthly_cents"), "Goal contribution", zero=True),
                     iso_date(item.get("target_date"), "Goal target date", optional=True),
                     timestamp(item.get("created_at"))))
                counts["goals"] += 1
            for row in records(profile.get("bills"), "Bills"):
                item = record(row, "Bill")
                old_id = integer(item.get("id"), "Bill reference")
                if old_id in bill_ids:
                    raise ValueError("Export bill references must be unique.")
                frequency = item.get("frequency")
                if not isinstance(frequency, str) or frequency not in FREQUENCIES:
                    raise ValueError("Export bill frequency is invalid.")
                bill_ids[old_id] = conn.execute(
                    """INSERT INTO bills(profile_id, name, category, amount_cents, day_of_month,
                       frequency, first_due_on) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                    (profile_id, text(item.get("name"), "Bill name", 60).strip(),
                     text(item.get("category"), "Bill category", 40).strip(),
                     integer(item.get("amount_cents"), "Bill amount"),
                     integer(item.get("day_of_month"), "Bill day", 31),
                     frequency, iso_date(item.get("first_due_on"), "First payment date", optional=True)
                     )).lastrowid
                counts["bills"] += 1
            for row in records(profile.get("commutes"), "Commutes"):
                item = record(row, "Commute")
                mode = item.get("mode")
                if mode not in ("car", "public"):
                    raise ValueError("Export commute mode is invalid.")
                weekdays = text(item.get("weekdays"), "Commuting weekdays", 13)
                days = weekdays.split(",")
                if any(day not in {str(i) for i in range(7)} for day in days) or len(days) != len(set(days)):
                    raise ValueError("Export commuting weekdays are invalid.")
                region = item.get("bank_holiday_region")
                if not isinstance(region, str) or region not in REGIONS:
                    raise ValueError("Export bank holiday region is invalid.")
                leave_mode = item.get("leave_mode")
                if leave_mode not in ("dates", "annual"):
                    raise ValueError("Export leave mode is invalid.")
                excluded_dates = text(item.get("excluded_dates"), "Dates off", 10000, optional=True)
                if excluded_dates is None:
                    raise ValueError("Dates off must be text.")
                parse_dates(excluded_dates)
                annual_days = integer(item.get("annual_leave_days"), "Annual leave days", 365, zero=True)
                if (leave_mode == "annual" and excluded_dates.strip()) or (leave_mode == "dates" and annual_days):
                    raise ValueError("Export leave modes cannot be combined.")
                distance = integer(item.get("distance_hundredths"), "Distance", 50000, zero=mode == "public")
                mpg = integer(item.get("mpg_hundredths"), "Fuel economy", 20000, zero=mode == "public")
                fuel = integer(item.get("fuel_price_cents"), "Fuel price", zero=mode == "public")
                fare = integer(item.get("fare_cents"), "Fare", zero=mode == "car")
                if (mode == "car" and fare) or (mode == "public" and (distance or mpg or fuel)):
                    raise ValueError("Export commute costs do not match travel mode.")
                conn.execute(
                    """INSERT INTO commutes(profile_id, name, mode, distance_hundredths, mpg_hundredths,
                       fuel_price_cents, fare_cents, weekdays, excluded_dates, bank_holiday_region,
                       leave_mode, annual_leave_days) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (profile_id, text(item.get("name"), "Commute name", 60).strip(), mode,
                     distance, mpg, fuel, fare, weekdays, excluded_dates, region, leave_mode,
                     annual_days))
                counts["commutes"] += 1
            for row in records(profile.get("categories"), "Categories"):
                item = record(row, "Category")
                conn.execute("INSERT INTO categories(profile_id, name) VALUES(?, ?)",
                             (profile_id, text(item.get("name"), "Category name", 40).strip()))
                counts["categories"] += 1
            for row in records(profile.get("bill_imports"), "Bill imports"):
                item = record(row, "Bill import")
                bill_id = bill_ids.get(integer(item.get("bill_id"), "Bill import bill reference"))
                transaction_id = transaction_ids.get(integer(
                    item.get("transaction_id"), "Bill import transaction reference"))
                if bill_id is None or transaction_id is None:
                    raise ValueError("An imported payment refers to a missing bill or transaction.")
                conn.execute(
                    "INSERT INTO bill_imports(bill_id, due_on, transaction_id) VALUES(?, ?, ?)",
                    (bill_id, iso_date(item.get("due_on"), "Bill payment date"), transaction_id))
                counts["bill_imports"] += 1
        conn.commit()
        return {"profiles": len(profiles), "counts": counts, "profile_id": first_profile_id}
    except Exception:
        conn.rollback()
        raise
